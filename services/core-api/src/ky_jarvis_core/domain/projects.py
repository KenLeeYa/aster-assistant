from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WorkItemStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class Requirement(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    statement: str
    acceptance_criteria: tuple[str, ...]
    source_message_id: str
    revision: int = 1


class WorkItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    description: str
    priority: int = Field(default=3, ge=1, le=5)
    estimate_minutes: int = Field(default=60, ge=15)
    status: WorkItemStatus = WorkItemStatus.DRAFT
    dependencies: tuple[UUID, ...] = ()
    risks: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    source_requirement_ids: tuple[UUID, ...]
    external_provider_id: str | None = None
    synchronization_status: str = "disabled"


class ProjectDecision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    rationale: str
    source_requirement_ids: tuple[UUID, ...]
    status: str = "draft"
    revision: int = 1


class ProjectPlan(BaseModel):
    project_id: UUID
    title: str
    requirements: tuple[Requirement, ...]
    decisions: tuple[ProjectDecision, ...] = ()
    work_items: tuple[WorkItem, ...]
    risks: tuple[str, ...]
    created_at: datetime
    approval_required: bool = True


class DeterministicProjectPlanner:
    def __init__(self) -> None:
        self._plans: dict[UUID, ProjectPlan] = {}

    @property
    def plans(self) -> tuple[ProjectPlan, ...]:
        return tuple(self._plans.values())

    def get(self, project_id: UUID) -> ProjectPlan:
        try:
            return self._plans[project_id]
        except KeyError as exc:
            raise KeyError(f"unknown project: {project_id}") from exc

    def create_preview(
        self,
        *,
        request: str,
        source_message_id: str,
        created_at: datetime,
        project_id: UUID | None = None,
    ) -> ProjectPlan:
        selected_project_id = project_id or uuid4()
        title = request.strip().splitlines()[0][:80] or "未命名專案"
        requirement = Requirement(
            project_id=selected_project_id,
            title=title,
            statement=request.strip(),
            acceptance_criteria=(
                "需求與來源訊息可追溯",
                "相關測試與驗證證據已記錄",
            ),
            source_message_id=source_message_id,
        )
        discovery = WorkItem(
            project_id=selected_project_id,
            title="確認需求與安全邊界",
            description="整理需求、依賴、風險與不可自動執行的操作。",
            estimate_minutes=60,
            source_requirement_ids=(requirement.id,),
            acceptance_criteria=("需求與風險清單可供審閱",),
        )
        implementation = WorkItem(
            project_id=selected_project_id,
            title="實作最小可驗證切片",
            description="依核准需求建立程式、契約與失敗先行測試。",
            estimate_minutes=180,
            dependencies=(discovery.id,),
            source_requirement_ids=(requirement.id,),
            acceptance_criteria=("相關品質門檻通過",),
        )
        verification = WorkItem(
            project_id=selected_project_id,
            title="執行驗證並保存證據",
            description="執行測試、安全檢查與可回復性驗證。",
            estimate_minutes=90,
            dependencies=(implementation.id,),
            source_requirement_ids=(requirement.id,),
            acceptance_criteria=("PASS、FAIL、BLOCKED 與 NOT RUN 狀態分明",),
        )
        decision = ProjectDecision(
            project_id=selected_project_id,
            title="外部同步維持停用",
            rationale="Calendar 與 Plane 寫入必須在預覽後通過獨立核准。",
            source_requirement_ids=(requirement.id,),
        )
        plan = ProjectPlan(
            project_id=selected_project_id,
            title=title,
            requirements=(requirement,),
            decisions=(decision,),
            work_items=(discovery, implementation, verification),
            risks=(
                "外部寫入未核准",
                "缺少憑證或裝置時不得宣稱 live 驗證成功",
            ),
            created_at=created_at,
        )
        self._plans[plan.project_id] = plan
        return plan
