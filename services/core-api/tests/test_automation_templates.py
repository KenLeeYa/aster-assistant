import json
from pathlib import Path

import pytest
from ky_jarvis_core.domain.automations import LocalAutomationScheduler, load_templates


async def _noop() -> None:
    return None


def test_all_automation_templates_are_disabled_and_audited() -> None:
    templates = load_templates(Path("automations/templates.yaml"))
    scheduler = LocalAutomationScheduler()

    assert len(templates) == 1
    assert all(template.enabled is False for template in templates)
    assert all(template.audit_link is True for template in templates)
    assert all(scheduler.register(template, _noop) is False for template in templates)
    assert scheduler.registered_job_ids() == ()


def test_enabled_template_registers_with_local_scheduler() -> None:
    template = load_templates(Path("automations/templates.yaml"))[0]
    enabled = template.__class__.model_validate({**template.model_dump(), "enabled": True})
    scheduler = LocalAutomationScheduler()

    assert scheduler.register(enabled, _noop) is True
    assert scheduler.registered_job_ids() == ("morning-brief",)


def test_mutating_tool_cannot_be_disguised_as_read_only() -> None:
    template = load_templates(Path("automations/templates.yaml"))[0]

    with pytest.raises(ValueError, match="risk-rated and centrally gated"):
        template.__class__.model_validate(
            {
                **template.model_dump(),
                "tools": ["social.publish"],
                "permission_level": "R0_READ_LOCAL",
                "approval_behavior": "read-only",
            }
        )


def test_n8n_exports_are_inert_and_preserve_central_approval_boundary() -> None:
    exports = sorted(Path("automations/n8n").glob("*.json"))

    assert {path.name for path in exports} == {"project-review.json", "report-intake.json"}
    for path in exports:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        assert payload["active"] is False
        assert payload["meta"]["approvalBoundary"] == "KY-JARVIS central gateway"
        assert all(node["type"] == "n8n-nodes-base.manualTrigger" for node in payload["nodes"])
        assert "credentials" not in raw.casefold()
