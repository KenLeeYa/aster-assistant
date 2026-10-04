from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ky_jarvis_core.domain.policy import RiskLevel
from ky_jarvis_core.domain.skills import READ_ONLY_RISKS

MUTATING_TOOL_TERMS = (
    "create",
    "delete",
    "execute",
    "hard-stop",
    "modify",
    "move",
    "publish",
    "send",
    "write",
)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: int = Field(ge=0, le=3)
    backoff_seconds: int = Field(ge=1, le=3600)


class AutomationTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    enabled: bool = False
    owner: str
    schedule: str
    timezone: str
    inputs: tuple[str, ...]
    tools: tuple[str, ...]
    permission_level: RiskLevel
    approval_behavior: str
    retry_policy: RetryPolicy
    maximum_duration_seconds: int = Field(ge=5, le=3600)
    output_destination: str
    failure_notification: str
    audit_link: bool

    @model_validator(mode="after")
    def validate_gate(self) -> AutomationTemplate:
        if self.permission_level not in READ_ONLY_RISKS and self.approval_behavior != "central":
            raise ValueError("mutating automation must use the central approval gateway")
        mutating_tools = tuple(
            tool
            for tool in self.tools
            if any(term in tool.casefold() for term in MUTATING_TOOL_TERMS)
        )
        if mutating_tools and (
            self.permission_level in READ_ONLY_RISKS or self.approval_behavior != "central"
        ):
            raise ValueError("mutating automation tools must be risk-rated and centrally gated")
        if not self.audit_link:
            raise ValueError("automations must preserve an audit link")
        return self


def load_templates(path: Path) -> tuple[AutomationTemplate, ...]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("automations"), list):
        raise ValueError("automation file must contain an automations list")
    return tuple(AutomationTemplate.model_validate(item) for item in payload["automations"])


class LocalAutomationScheduler:
    def __init__(self, *, timezone: str = "Asia/Taipei") -> None:
        self._scheduler = AsyncIOScheduler(timezone=timezone)

    def register(
        self,
        template: AutomationTemplate,
        callback: Callable[[], Awaitable[None]],
    ) -> bool:
        if not template.enabled:
            return False
        trigger = CronTrigger.from_crontab(template.schedule, timezone=template.timezone)
        self._scheduler.add_job(
            callback,
            trigger,
            id=template.id,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
            replace_existing=True,
        )
        return True

    def start(self) -> None:
        self._scheduler.start()

    def registered_job_ids(self) -> tuple[str, ...]:
        return tuple(sorted(job.id for job in self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
