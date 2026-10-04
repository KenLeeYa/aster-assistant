from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, MutableMapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.approvals import (
    ApprovalRequest,
    ApprovalService,
    ApprovalState,
    canonical_action_hash,
)
from ky_jarvis_core.domain.audit import AuditChain, AuditRepositoryPort
from ky_jarvis_core.domain.devices import (
    DeviceRecord,
    DeviceSecurityService,
    DeviceTrustState,
    approval_signature_payload,
)
from ky_jarvis_core.domain.gateway import ToolResult, build_reference_gateway
from ky_jarvis_core.domain.memory import GovernedMemoryStore, MemoryRecord, MemoryType
from ky_jarvis_core.domain.mobile import MobileChannelService, MobileCommand
from ky_jarvis_core.domain.operator_authorization import (
    DesktopOperatorAuthorization,
    FileOperatorCredentialStore,
    MemoryOperatorCredentialStore,
)
from ky_jarvis_core.domain.policy import RiskLevel
from ky_jarvis_core.domain.projects import DeterministicProjectPlanner, ProjectPlan
from ky_jarvis_core.domain.realtime import (
    MockRealtimeProvider,
    RealtimeBroker,
    RealtimeSessionPolicy,
)
from ky_jarvis_core.domain.scheduling import DeterministicScheduler, ScheduleProposal, TimeBlock
from ky_jarvis_core.domain.voice import SttProvider, promote_final_transcript
from ky_jarvis_core.domain.workers import WorkerPresence, WorkerPresenceService, WorkerState
from ky_jarvis_core.integrations.adapters import (
    DisabledConnectorAdapter,
    FakeCalendarAdapter,
    FakePlaneAdapter,
)
from ky_jarvis_core.integrations.push import DisabledPushAdapter, PushDispatcher

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from ky_jarvis_core.agents.providers import StructuredModelProvider
    from ky_jarvis_core.agents.supervisor import AgentRunService
    from ky_jarvis_core.persistence.execution_ledger import ExecutionLedger


class ApplicationServices:
    def __init__(
        self,
        settings: Settings,
        *,
        model_provider: StructuredModelProvider | None = None,
        stt_provider: SttProvider | None = None,
    ) -> None:
        self._persistence_engine: Engine | None = None
        approval_requests: MutableMapping[UUID, ApprovalRequest] | None = None
        audit_repository: AuditRepositoryPort | None = None
        device_records: MutableMapping[UUID, DeviceRecord] | None = None
        memory_records: MutableMapping[UUID, MemoryRecord] | None = None
        self.execution_ledger: ExecutionLedger | None = None
        if settings.database_url is not None:
            from ky_jarvis_core.persistence.approval_repository import (
                ApprovalRepository,
                SqlApprovalMapping,
            )
            from ky_jarvis_core.persistence.audit_repository import AuditRepository
            from ky_jarvis_core.persistence.database import create_database_engine
            from ky_jarvis_core.persistence.device_repository import SqlDeviceMapping
            from ky_jarvis_core.persistence.execution_ledger import ExecutionLedger
            from ky_jarvis_core.persistence.memory_repository import SqlMemoryMapping

            self._persistence_engine = create_database_engine(
                settings.database_url.get_secret_value()
            )
            approval_requests = SqlApprovalMapping(ApprovalRepository(self._persistence_engine))
            audit_repository = AuditRepository(self._persistence_engine)
            device_records = SqlDeviceMapping(self._persistence_engine)
            memory_records = SqlMemoryMapping(self._persistence_engine)
            self.execution_ledger = ExecutionLedger(self._persistence_engine)
        self.memory = GovernedMemoryStore(memory_records)
        self.approvals = ApprovalService(requests=approval_requests)
        self.audit = AuditChain(audit_repository)
        self.gateway = build_reference_gateway()
        self.devices = DeviceSecurityService(devices=device_records)
        credential_store = (
            FileOperatorCredentialStore(settings.operator_credential_path)
            if settings.operator_credential_path is not None
            else MemoryOperatorCredentialStore()
        )
        self.operator = DesktopOperatorAuthorization(
            credential_store=credential_store,
            rp_id=settings.operator_rp_id,
            origin=settings.operator_origin,
            bootstrap_secret=(
                settings.operator_bootstrap_secret.get_secret_value()
                if settings.operator_bootstrap_secret is not None
                else None
            ),
            challenge_ttl=timedelta(seconds=settings.operator_challenge_ttl_seconds),
            grant_ttl=timedelta(seconds=settings.operator_grant_ttl_seconds),
        )
        self.push = PushDispatcher(
            devices=self.devices,
            adapter=DisabledPushAdapter(),
            enabled=settings.enable_push_notifications,
        )
        self.projects = DeterministicProjectPlanner()
        self.scheduler = DeterministicScheduler()
        self.mobile = MobileChannelService()
        self.workers = WorkerPresenceService()
        self.local_worker_id = "local-agent"
        self.voice_max_seconds = settings.voice_max_seconds
        self.voice_slot = asyncio.Semaphore(1)
        self.calendar = FakeCalendarAdapter(enabled=settings.enable_google_calendar)
        self.plane = FakePlaneAdapter(enabled=settings.enable_plane)
        self.github = DisabledConnectorAdapter(
            name="github",
            capabilities=("repository.read", "issue.preview", "issue.create"),
        )
        self.gmail = DisabledConnectorAdapter(
            name="gmail",
            capabilities=("message.read", "draft.preview", "message.send"),
        )
        self.google_drive = DisabledConnectorAdapter(
            name="google-drive",
            capabilities=("file.read", "file.preview", "file.write"),
        )
        self.microsoft_graph = DisabledConnectorAdapter(
            name="microsoft-graph",
            capabilities=("calendar.read", "mail.read", "file.read"),
        )
        self.n8n = DisabledConnectorAdapter(
            name="n8n",
            capabilities=("webhook.preview", "webhook.invoke"),
        )
        self.local_files = DisabledConnectorAdapter(
            name="local-files",
            capabilities=("file.inventory", "file.read"),
        )
        self.realtime = RealtimeBroker(
            devices=self.devices,
            provider=MockRealtimeProvider(),
            policy=RealtimeSessionPolicy(
                max_duration_seconds=settings.realtime_max_session_seconds,
                max_concurrent_sessions=settings.realtime_max_concurrent_sessions,
                daily_soft_limit_units=settings.realtime_daily_soft_limit_units,
                daily_hard_limit_units=settings.realtime_daily_hard_limit_units,
            ),
            enabled=settings.enable_openai_realtime,
        )
        provider = model_provider
        if provider is None:
            if settings.local_model_provider == "colibri" and settings.colibri_model:
                from ky_jarvis_core.agents.providers import ColibriGatewayProvider

                provider = ColibriGatewayProvider(
                    base_url=str(settings.colibri_base_url),
                    model=settings.colibri_model,
                )
            elif settings.local_model_provider == "ollama" and settings.ollama_model:
                from ky_jarvis_core.agents.providers import OllamaProvider

                provider = OllamaProvider(
                    base_url=str(settings.ollama_base_url),
                    model=settings.ollama_model,
                )
        self.agent_runs: AgentRunService | None = None
        if provider is not None:
            from ky_jarvis_core.agents.supervisor import AgentRunService, build_supervisor

            self.agent_runs = AgentRunService(build_supervisor(provider))
            self.workers.register(
                self.local_worker_id,
                display_name="Windows local agent",
                capabilities=("chat", "projects", "scheduling", "voice"),
            )
        self.stt = stt_provider
        if self.stt is None and settings.enable_voice:
            from ky_jarvis_core.integrations.stt import FasterWhisperSttProvider

            self.stt = FasterWhisperSttProvider(model_name=settings.stt_model)

    def close(self) -> None:
        if self._persistence_engine is not None:
            self._persistence_engine.dispose()

    def execute_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        approved: bool = False,
        approval_id: UUID | None = None,
    ) -> ToolResult:
        definition = self.gateway.definition(tool_name)
        if definition.requires_approval:
            if approval_id is None or not approved:
                raise PermissionError("approved action is required")
            request = self.approvals.get(approval_id)
            if (
                request.state is not ApprovalState.APPROVED
                or request.tool_name != tool_name
                or request.idempotency_key != idempotency_key
                or request.preview != payload
            ):
                raise PermissionError("approved action no longer matches")
            action_hash = request.action_hash
        else:
            action_hash = canonical_action_hash(
                {"tool_name": tool_name, "payload": payload, "idempotency_key": idempotency_key}
            )
        if self.execution_ledger is not None:
            cached = self.execution_ledger.reserve(
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                action_hash=action_hash,
                approval_id=approval_id,
            )
            if cached is not None:
                return cached
        result = self.gateway.execute(
            tool_name, payload, idempotency_key=idempotency_key, approved=approved
        )
        if self.execution_ledger is not None:
            self.execution_ledger.complete(
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                action_hash=action_hash,
                result=result,
            )
        return result


class MemoryCreate(BaseModel):
    user_id: str = "local-user"
    project_id: UUID | None = None
    scope: str = "global"
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=20_000)
    source_type: str = "user_message"


class MemoryApprove(BaseModel):
    pass


class ProjectPreviewRequest(BaseModel):
    request: str = Field(min_length=1, max_length=20_000)
    source_message_id: str = Field(min_length=1, max_length=200)
    project_id: UUID | None = None


class SchedulePreviewRequest(BaseModel):
    work_item_id: UUID
    duration_minutes: int = Field(ge=30, le=8 * 60)
    earliest: datetime
    deadline: datetime
    busy: tuple[TimeBlock, ...] = ()
    timezone: str = Field(default="Asia/Taipei", min_length=1, max_length=80)


class ApprovalCreate(BaseModel):
    title: str
    reason: str
    target: str
    risk_level: RiskLevel
    permissions: tuple[str, ...]
    preview: dict[str, Any]
    side_effects: tuple[str, ...] = ()
    rollback_method: str
    originating_request: str
    tool_name: str
    idempotency_key: str


class ApprovalDecision(BaseModel):
    token: str
    action_payload: dict[str, Any]
    approved: bool


class ToolExecutionRequest(BaseModel):
    tool_name: str = Field(min_length=3, max_length=64)
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1_000)
    originating_request: str = Field(min_length=1, max_length=2_000)
    rollback_method: str = Field(min_length=1, max_length=1_000)


class ToolExecutionResume(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    approved: bool


class OperatorRegistrationStart(BaseModel):
    bootstrap_secret: SecretStr


class OperatorCredentialResponse(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=128)
    credential: dict[str, Any]


class OperatorAuthenticationStart(BaseModel):
    method: Literal["POST", "DELETE"]
    path: str = Field(min_length=1, max_length=512, pattern=r"^/api/v1/")
    body: dict[str, Any] = Field(default_factory=dict)


class PairingStart(BaseModel):
    server_fingerprint: str = Field(min_length=8, max_length=256)


class PairingComplete(BaseModel):
    session_id: UUID
    one_time_secret: str
    public_key_pem: str
    approval_public_key_pem: str | None = None
    proof_signature_b64: str
    user_id: str = "local-user"
    display_name: str
    app_version: str
    os_version: str
    capabilities: tuple[str, ...] = ()


class PairingConfirm(BaseModel):
    comparison_code: str = Field(pattern=r"^\d{6}$")


class PairingTokenClaim(BaseModel):
    one_time_secret: str
    proof_signature_b64: str


class RefreshRequest(BaseModel):
    family_id: UUID
    refresh_token: str


class RealtimeSecretRequest(BaseModel):
    requested_mode: str = "conversation"


class WorkerRegister(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    capabilities: tuple[str, ...] = ()


class WorkerHeartbeat(BaseModel):
    degraded: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: str = Field(default="local-conversation", min_length=1, max_length=200)


class MobileCommandCreate(BaseModel):
    device_id: UUID
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MobileCommandAck(BaseModel):
    receipt: str = Field(default="displayed", min_length=1, max_length=80)


class MobileApprovalDecision(BaseModel):
    decision: str = Field(pattern=r"^(approve|deny)$")
    timestamp: datetime
    signature_b64: str = Field(min_length=32, max_length=512)


def _domain_error(exc: Exception, *, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _approval_view(request: ApprovalRequest) -> dict[str, Any]:
    view = request.model_dump(mode="json")
    for internal_field in ("token_hash", "nonce", "action_hash"):
        view.pop(internal_field, None)
    return view


def _mobile_approval_view(request: ApprovalRequest) -> dict[str, Any]:
    view = request.model_dump(mode="json")
    view.pop("token_hash", None)
    return view


def _approval_action_payload(request: ApprovalRequest) -> dict[str, Any]:
    return {
        "target": request.target,
        "tool_name": request.tool_name,
        "preview": request.preview,
        "permissions": request.permissions,
        "idempotency_key": request.idempotency_key,
    }


def create_router(services: ApplicationServices) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def authenticated_device(authorization: str | None) -> DeviceRecord:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="device access token required")
        try:
            device = services.devices.authenticate_access_token(
                authorization.removeprefix("Bearer ")
            )
            return services.devices.mark_seen(device.id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail="invalid or expired device session",
            ) from exc

    def authenticated_operator(
        grant_token: str | None,
        *,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> str:
        try:
            return services.operator.authorize(
                grant_token,
                method=method,
                path=path,
                body=body,
            )
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail="desktop operator authorization required",
            ) from exc

    async def run_chat(body: ChatRequest, *, source: str) -> dict[str, Any]:
        if services.agent_runs is None:
            raise HTTPException(status_code=503, detail="local model is not configured")
        try:
            state = await services.agent_runs.run(body.message, thread_id=body.thread_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="local model is unavailable") from exc
        if state.get("status") != "completed" or not isinstance(state.get("result"), dict):
            raise HTTPException(status_code=502, detail="local model returned no valid result")
        services.audit.append(
            "chat.completed",
            {"thread_id": body.thread_id, "source": source, "route": state.get("route")},
        )
        return {
            "thread_id": body.thread_id,
            "source": source,
            "status": state["status"],
            "route": state.get("route"),
            **state["result"],
        }

    async def process_voice_turn(
        request: Request,
        *,
        source: str,
        device_id: UUID | None,
        sample_rate: int,
        locale: str,
    ) -> dict[str, Any]:
        if services.stt is None:
            raise HTTPException(status_code=503, detail="local speech recognition is disabled")
        if request.headers.get("content-type", "").split(";", maxsplit=1)[0] != (
            "application/octet-stream"
        ):
            raise HTTPException(status_code=415, detail="PCM16 octet-stream required")
        if sample_rate < 8_000 or sample_rate > 48_000:
            raise HTTPException(status_code=422, detail="unsupported audio sample rate")
        maximum_bytes = services.voice_max_seconds * sample_rate * 2
        content_length = request.headers.get("content-length")
        try:
            declared_bytes = int(content_length) if content_length is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid content length") from exc
        if declared_bytes is not None and declared_bytes > maximum_bytes:
            raise HTTPException(status_code=413, detail="voice turn exceeds duration limit")
        chunks: list[bytes] = []
        received_bytes = 0
        async for chunk in request.stream():
            received_bytes += len(chunk)
            if received_bytes > maximum_bytes:
                raise HTTPException(status_code=413, detail="voice turn exceeds duration limit")
            chunks.append(chunk)
        pcm16 = b"".join(chunks)
        if not pcm16 or len(pcm16) % 2:
            raise HTTPException(status_code=422, detail="invalid PCM16 audio")
        if len(pcm16) > maximum_bytes:
            raise HTTPException(status_code=413, detail="voice turn exceeds duration limit")
        from ky_jarvis_core.integrations.stt import pcm16_mono_to_wav

        wav_audio = pcm16_mono_to_wav(pcm16, sample_rate=sample_rate)
        pcm16 = b""
        try:
            async with services.voice_slot:
                transcript = await asyncio.to_thread(
                    services.stt.transcribe,
                    wav_audio,
                    locale=locale,
                )
                transcript = promote_final_transcript(transcript)
                reply = await run_chat(
                    ChatRequest(
                        message=transcript.text,
                        thread_id=f"voice:{transcript.voice_session_id}",
                    ),
                    source=source,
                )
        except (ImportError, ModuleNotFoundError) as exc:
            raise HTTPException(
                status_code=503,
                detail="local speech recognition package is unavailable",
            ) from exc
        except ValueError as exc:
            raise _domain_error(exc, status_code=422) from exc
        finally:
            wav_audio = b""
        audit_payload = {
            "voice_session_id": str(transcript.voice_session_id),
            "provider": transcript.provider,
            "source": source,
        }
        if device_id is not None:
            audit_payload["device_id"] = str(device_id)
        services.audit.append("voice.final_transcript_submitted", audit_payload)
        return {"transcript": transcript.model_dump(mode="json"), "reply": reply}

    @router.get("/operator/status", tags=["operator"])
    async def operator_status() -> dict[str, Any]:
        return services.operator.status()

    @router.post("/operator/registration/options", tags=["operator"])
    async def operator_registration_options(
        body: OperatorRegistrationStart,
    ) -> dict[str, Any]:
        try:
            return services.operator.begin_registration(body.bootstrap_secret.get_secret_value())
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="operator enrollment denied") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/operator/registration/verify", tags=["operator"])
    async def operator_registration_verify(
        body: OperatorCredentialResponse,
    ) -> dict[str, Any]:
        try:
            status = services.operator.finish_registration(body.challenge_id, body.credential)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="operator enrollment denied") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        services.audit.append("operator.registered", {"authenticator": "platform"})
        return status

    @router.post("/operator/authentication/options", tags=["operator"])
    async def operator_authentication_options(
        body: OperatorAuthenticationStart,
    ) -> dict[str, Any]:
        try:
            return services.operator.begin_authentication(**body.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="Windows Hello is required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/operator/authentication/verify", tags=["operator"])
    async def operator_authentication_verify(
        body: OperatorCredentialResponse,
    ) -> dict[str, Any]:
        try:
            verified = services.operator.finish_authentication(
                body.challenge_id,
                body.credential,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=401,
                detail="Windows Hello verification failed",
            ) from exc
        services.audit.append(
            "operator.action_authenticated",
            {"action_hash": verified["action_hash"]},
        )
        return verified

    @router.get("/memories", response_model=list[MemoryRecord], tags=["memory"])
    async def list_memories(user_id: str = Query(default="local-user")) -> list[MemoryRecord]:
        return list(services.memory.list_records(user_id=user_id))

    @router.post("/memories", response_model=MemoryRecord, tags=["memory"])
    async def create_memory(body: MemoryCreate) -> MemoryRecord:
        record = services.memory.propose(
            user_id=body.user_id,
            project_id=body.project_id,
            scope=body.scope,
            content=body.content,
            memory_type=body.memory_type,
            source_type=body.source_type,
            created_by=body.user_id,
        )
        services.audit.append("memory.proposed", {"memory_id": str(record.id)})
        return record

    @router.post("/memories/{memory_id}/approve", response_model=MemoryRecord, tags=["memory"])
    async def approve_memory(
        memory_id: UUID,
        body: MemoryApprove,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> MemoryRecord:
        operator_actor = authenticated_operator(
            operator_grant,
            method="POST",
            path=f"/api/v1/memories/{memory_id}/approve",
            body=body.model_dump(mode="json"),
        )
        try:
            record = services.memory.approve(memory_id, approved_by=operator_actor)
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "memory.approved",
            {"memory_id": str(memory_id), "actor": operator_actor},
        )
        return record

    @router.delete("/memories/{memory_id}", response_model=MemoryRecord, tags=["memory"])
    async def forget_memory(
        memory_id: UUID,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> MemoryRecord:
        operator_actor = authenticated_operator(
            operator_grant,
            method="DELETE",
            path=f"/api/v1/memories/{memory_id}",
            body={},
        )
        try:
            record = services.memory.forget(memory_id)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc
        services.audit.append(
            "memory.forgotten",
            {"memory_id": str(memory_id), "actor": operator_actor},
        )
        return record

    @router.post("/projects/preview", response_model=ProjectPlan, tags=["projects"])
    async def preview_project(body: ProjectPreviewRequest) -> ProjectPlan:
        plan = services.projects.create_preview(
            request=body.request,
            source_message_id=body.source_message_id,
            created_at=datetime.now(UTC),
            project_id=body.project_id,
        )
        services.audit.append("project.preview_created", {"project_id": str(plan.project_id)})
        return plan

    @router.get("/projects", response_model=list[ProjectPlan], tags=["projects"])
    async def projects() -> list[ProjectPlan]:
        return list(services.projects.plans)

    @router.get("/projects/{project_id}", response_model=ProjectPlan, tags=["projects"])
    async def project(project_id: UUID) -> ProjectPlan:
        try:
            return services.projects.get(project_id)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc

    @router.post("/schedules/preview", response_model=ScheduleProposal, tags=["scheduling"])
    async def preview_schedule(body: SchedulePreviewRequest) -> ScheduleProposal:
        try:
            proposal = services.scheduler.propose(
                work_item_id=body.work_item_id,
                duration_minutes=body.duration_minutes,
                earliest=body.earliest,
                deadline=body.deadline,
                busy=body.busy,
                timezone=body.timezone,
            )
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "schedule.preview_created",
            {"proposal_id": str(proposal.id), "work_item_id": str(body.work_item_id)},
        )
        return proposal

    @router.get("/schedules", response_model=list[ScheduleProposal], tags=["scheduling"])
    async def schedules() -> list[ScheduleProposal]:
        return list(services.scheduler.proposals)

    @router.get("/connectors", tags=["connectors"])
    async def connectors() -> list[dict[str, Any]]:
        return [
            services.calendar.status().model_dump(mode="json"),
            services.plane.status().model_dump(mode="json"),
            services.github.status().model_dump(mode="json"),
            services.gmail.status().model_dump(mode="json"),
            services.google_drive.status().model_dump(mode="json"),
            services.microsoft_graph.status().model_dump(mode="json"),
            services.n8n.status().model_dump(mode="json"),
            services.local_files.status().model_dump(mode="json"),
        ]

    @router.post("/chat", tags=["chat"])
    async def chat(body: ChatRequest) -> dict[str, Any]:
        return await run_chat(body, source="web")

    @router.get("/runs", tags=["chat"])
    async def runs() -> list[dict[str, Any]]:
        if services.agent_runs is None:
            return []
        return [item.model_dump(mode="json") for item in services.agent_runs.history]

    @router.post("/runs", tags=["chat"])
    async def start_run(body: ChatRequest) -> dict[str, Any]:
        agent_runs = services.agent_runs
        if agent_runs is None:
            raise HTTPException(status_code=503, detail="local model is not configured")
        record = agent_runs.start(body.message, thread_id=body.thread_id)
        services.audit.append(
            "chat.run_started",
            {"run_id": record.run_id, "thread_id": body.thread_id},
        )
        return record.model_dump(mode="json")

    @router.get("/runs/{run_id}", tags=["chat"])
    async def run_status(run_id: str) -> dict[str, Any]:
        agent_runs = services.agent_runs
        if agent_runs is None:
            raise HTTPException(status_code=503, detail="local model is not configured")
        try:
            return agent_runs.get(run_id).model_dump(mode="json")
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc

    @router.get("/runs/{run_id}/events", tags=["chat"])
    async def run_events(run_id: str) -> StreamingResponse:
        agent_runs = services.agent_runs
        if agent_runs is None:
            raise HTTPException(status_code=503, detail="local model is not configured")
        try:
            agent_runs.get(run_id)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc

        async def events() -> AsyncIterator[str]:
            async for record in agent_runs.watch(run_id):
                payload = json.dumps(
                    record.model_dump(mode="json"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/runs/{run_id}/cancel", tags=["chat"])
    async def cancel_run(run_id: str) -> dict[str, Any]:
        agent_runs = services.agent_runs
        if agent_runs is None:
            raise HTTPException(status_code=503, detail="local model is not configured")
        try:
            record = agent_runs.get(run_id)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc
        if not agent_runs.cancel(run_id):
            raise HTTPException(status_code=409, detail="agent run is not cancellable")
        services.audit.append("chat.run_cancel_requested", {"run_id": run_id})
        return {"accepted": True, "run": record.model_dump(mode="json")}

    @router.get("/approvals", tags=["approvals"])
    async def approvals() -> list[dict[str, Any]]:
        return [_approval_view(item) for item in services.approvals.list_requests()]

    @router.get("/tools", tags=["tools"])
    async def tools() -> list[dict[str, Any]]:
        return services.gateway.catalog()

    @router.post("/tool-executions", tags=["tools"])
    async def request_tool_execution(body: ToolExecutionRequest) -> dict[str, Any]:
        try:
            definition = services.gateway.definition(body.tool_name)
            services.gateway.validate_payload(body.tool_name, body.payload)
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc) from exc
        if not definition.requires_approval:
            result = services.execute_tool(
                body.tool_name,
                body.payload,
                idempotency_key=body.idempotency_key,
            )
            return {"approval": None, "decision_token": None, "result": result.model_dump()}
        request, token = services.approvals.create(
            title=f"Execute {definition.name}",
            reason=body.reason,
            target=f"{definition.connector}:{definition.name}",
            risk_level=definition.risk_level,
            permissions=definition.required_permissions,
            preview=body.payload,
            side_effects=definition.side_effects,
            rollback_method=body.rollback_method,
            originating_request=body.originating_request,
            agent_run_id=uuid4(),
            tool_name=definition.name,
            idempotency_key=body.idempotency_key,
        )
        services.audit.append(
            "tool.execution_paused",
            {"approval_id": str(request.id), "tool_name": definition.name},
        )
        return {
            "approval": _approval_view(request),
            "decision_token": token,
            "result": None,
        }

    @router.post("/tool-executions/{approval_id}/resume", tags=["tools"])
    async def resume_tool_execution(
        approval_id: UUID,
        body: ToolExecutionResume,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> dict[str, Any]:
        path = f"/api/v1/tool-executions/{approval_id}/resume"
        operator_actor = authenticated_operator(
            operator_grant,
            method="POST",
            path=path,
            body=body.model_dump(mode="json"),
        )
        try:
            request = services.approvals.get(approval_id)
            decided = services.approvals.decide(
                approval_id,
                token=body.token,
                action_payload=_approval_action_payload(request),
                approved=body.approved,
                decided_by=operator_actor,
            )
            if not body.approved:
                services.audit.append(
                    "tool.execution_denied",
                    {"approval_id": str(approval_id), "tool_name": request.tool_name},
                )
                return {"approval": _approval_view(decided), "result": None}
            result = services.execute_tool(
                request.tool_name,
                request.preview,
                idempotency_key=request.idempotency_key,
                approved=True,
                approval_id=approval_id,
            )
            consumed = services.approvals.consume(approval_id)
        except (KeyError, PermissionError, ValueError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "tool.execution_completed",
            {
                "approval_id": str(approval_id),
                "tool_name": request.tool_name,
                "idempotent_replay": result.idempotent_replay,
            },
        )
        return {
            "approval": _approval_view(consumed),
            "result": result.model_dump(mode="json"),
        }

    @router.post("/approvals", tags=["approvals"])
    async def create_approval(body: ApprovalCreate) -> dict[str, Any]:
        request, token = services.approvals.create(
            title=body.title,
            reason=body.reason,
            target=body.target,
            risk_level=body.risk_level,
            permissions=body.permissions,
            preview=body.preview,
            side_effects=body.side_effects,
            rollback_method=body.rollback_method,
            originating_request=body.originating_request,
            agent_run_id=uuid4(),
            tool_name=body.tool_name,
            idempotency_key=body.idempotency_key,
        )
        return {"request": _approval_view(request), "decision_token": token}

    @router.post("/approvals/{approval_id}/decision", tags=["approvals"])
    async def decide_approval(
        approval_id: UUID,
        body: ApprovalDecision,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> dict[str, Any]:
        operator_actor = authenticated_operator(
            operator_grant,
            method="POST",
            path=f"/api/v1/approvals/{approval_id}/decision",
            body=body.model_dump(mode="json"),
        )
        try:
            request = services.approvals.decide(
                approval_id,
                token=body.token,
                action_payload=body.action_payload,
                approved=body.approved,
                decided_by=operator_actor,
            )
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "approval.decided",
            {"approval_id": str(approval_id), "approved": body.approved},
        )
        return _approval_view(request)

    @router.post("/device-pairings", tags=["devices"])
    async def begin_pairing(
        body: PairingStart,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> dict[str, Any]:
        operator_actor = authenticated_operator(
            operator_grant,
            method="POST",
            path="/api/v1/device-pairings",
            body=body.model_dump(mode="json"),
        )
        offer = services.devices.begin_pairing(server_fingerprint=body.server_fingerprint)
        services.audit.append("device.pairing_started", {"actor": operator_actor})
        return offer.model_dump(mode="json")

    @router.post("/device-pairings/complete", tags=["devices"])
    async def complete_pairing(body: PairingComplete) -> dict[str, Any]:
        try:
            device = services.devices.complete_pairing(**body.model_dump())
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc) from exc
        return device.model_dump(mode="json")

    @router.post("/devices/{device_id}/confirm", tags=["devices"])
    async def confirm_device(
        device_id: UUID,
        body: PairingConfirm,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> dict[str, Any]:
        operator_actor = authenticated_operator(
            operator_grant,
            method="POST",
            path=f"/api/v1/devices/{device_id}/confirm",
            body=body.model_dump(mode="json"),
        )
        try:
            services.devices.confirm_device(
                device_id,
                comparison_code=body.comparison_code,
            )
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "device.confirmed",
            {"device_id": str(device_id), "actor": operator_actor},
        )
        return {"device_id": str(device_id), "status": "trusted", "tokens": "claim-on-device"}

    @router.post("/device-pairings/{session_id}/claim", tags=["devices"])
    async def claim_pairing_tokens(
        session_id: UUID,
        body: PairingTokenClaim,
    ) -> dict[str, Any]:
        try:
            tokens = services.devices.claim_pairing_tokens(
                session_id,
                one_time_secret=body.one_time_secret,
                proof_signature_b64=body.proof_signature_b64,
            )
        except (KeyError, ValueError) as exc:
            raise _domain_error(exc, status_code=401) from exc
        services.audit.append("device.tokens_claimed", {"device_id": str(tokens.device_id)})
        return tokens.model_dump(mode="json")

    @router.get("/devices", tags=["devices"])
    async def devices() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in services.devices.list_devices()]

    @router.delete("/devices/{device_id}", tags=["devices"])
    async def revoke_device(
        device_id: UUID,
        operator_grant: str | None = Header(
            default=None,
            alias="X-KY-JARVIS-Operator-Grant",
        ),
    ) -> dict[str, Any]:
        operator_actor = authenticated_operator(
            operator_grant,
            method="DELETE",
            path=f"/api/v1/devices/{device_id}",
            body={},
        )
        try:
            device = services.devices.revoke_device(device_id)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc
        services.approvals.invalidate_for_target(f"device:{device_id}")
        services.audit.append(
            "device.revoked",
            {"device_id": str(device_id), "actor": operator_actor},
        )
        return device.model_dump(mode="json")

    @router.post("/mobile/sessions/refresh", tags=["devices"])
    async def refresh_session(body: RefreshRequest) -> dict[str, Any]:
        try:
            tokens = services.devices.rotate_refresh_token(body.family_id, body.refresh_token)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail="invalid or expired device session",
            ) from exc
        return tokens.model_dump(mode="json")

    @router.post("/mobile/heartbeat", tags=["mobile"])
    async def mobile_heartbeat(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(authorization)
        pending_count = sum(
            item.state in {"queued", "delivered"}
            for item in services.mobile.list_commands(device_id=device.id)
        )
        return {
            "device_id": str(device.id),
            "last_seen_at": device.last_seen_at,
            "pending_count": pending_count,
        }

    @router.get("/mobile/projects", tags=["mobile"])
    async def mobile_projects(
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        authenticated_device(authorization)
        return [item.model_dump(mode="json") for item in services.projects.plans]

    @router.get("/mobile/agenda", tags=["mobile"])
    async def mobile_agenda(
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        authenticated_device(authorization)
        return [item.model_dump(mode="json") for item in services.scheduler.proposals]

    @router.get("/mobile/worker-presence", tags=["mobile"])
    async def mobile_worker_presence(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authenticated_device(authorization)
        if services.agent_runs is not None:
            services.workers.heartbeat(services.local_worker_id)
        workers = services.workers.list()
        if not workers:
            return {
                "worker_id": services.local_worker_id,
                "state": WorkerState.OFFLINE.value,
                "last_seen_at": None,
                "capabilities": [],
            }
        presence = next(
            (item for item in workers if item.state is WorkerState.ONLINE),
            workers[0],
        )
        return presence.model_dump(mode="json")

    @router.get("/mobile/approvals", tags=["mobile"])
    async def mobile_approvals(
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        authenticated_device(authorization)
        return [
            _mobile_approval_view(item)
            for item in services.approvals.list_requests()
            if item.state.value == "pending"
        ]

    @router.post("/mobile/approvals/{approval_id}/decision", tags=["mobile"])
    async def mobile_approval_decision(
        approval_id: UUID,
        body: MobileApprovalDecision,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(authorization)
        if body.timestamp.tzinfo is None:
            raise HTTPException(status_code=400, detail="approval timestamp requires timezone")
        timestamp = body.timestamp.astimezone(UTC)
        now = datetime.now(UTC)
        if abs(now - timestamp) > timedelta(minutes=2):
            raise HTTPException(status_code=400, detail="approval signature timestamp is stale")
        try:
            request = services.approvals.get(approval_id)
            payload = approval_signature_payload(
                approval_id=approval_id,
                action_hash=request.action_hash,
                nonce=request.nonce,
                decision=body.decision,
                device_id=device.id,
                timestamp=timestamp,
            )
            services.devices.verify_approval_signature(
                device.id,
                payload,
                body.signature_b64,
            )
            decided = services.approvals.decide_authenticated(
                approval_id,
                action_hash=request.action_hash,
                approved=body.decision == "approve",
                decided_by=f"device:{device.id}",
                now=now,
            )
            result: dict[str, Any] | None = None
            if body.decision == "approve":
                try:
                    services.gateway.definition(request.tool_name)
                except KeyError:
                    pass
                else:
                    execution = services.execute_tool(
                        request.tool_name,
                        request.preview,
                        idempotency_key=request.idempotency_key,
                        approved=True,
                        approval_id=approval_id,
                    )
                    decided = services.approvals.consume(approval_id)
                    result = execution.model_dump(mode="json")
        except (KeyError, PermissionError, ValueError) as exc:
            raise _domain_error(exc) from exc
        services.audit.append(
            "approval.mobile_decided",
            {
                "approval_id": str(approval_id),
                "device_id": str(device.id),
                "decision": body.decision,
            },
        )
        return {"approval": _mobile_approval_view(decided), "result": result}

    @router.post("/mobile/commands", response_model=MobileCommand, tags=["mobile"])
    async def create_mobile_command(
        body: MobileCommandCreate,
        x_correlation_id: str | None = Header(default=None),
    ) -> MobileCommand:
        try:
            device = services.devices.get_device(body.device_id)
            if device.trust_state is not DeviceTrustState.TRUSTED:
                raise ValueError("target device is not trusted")
            command = services.mobile.enqueue(
                **body.model_dump(),
                correlation_id=x_correlation_id or str(uuid4()),
            )
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc
        except ValueError as exc:
            raise _domain_error(exc, status_code=409) from exc
        services.audit.append(
            "mobile.command_queued",
            {"command_id": str(command.id), "device_id": str(command.device_id)},
        )
        return command

    @router.get("/mobile/commands", response_model=list[MobileCommand], tags=["mobile"])
    async def list_mobile_commands(
        device_id: UUID | None = None,
    ) -> list[MobileCommand]:
        return list(services.mobile.list_commands(device_id=device_id))

    @router.get(
        "/mobile/commands/pending",
        response_model=list[MobileCommand],
        tags=["mobile"],
    )
    async def pending_mobile_commands(
        authorization: str | None = Header(default=None),
    ) -> list[MobileCommand]:
        device = authenticated_device(authorization)
        return list(services.mobile.pending(device_id=device.id))

    @router.post(
        "/mobile/commands/{command_id}/ack",
        response_model=MobileCommand,
        tags=["mobile"],
    )
    async def acknowledge_mobile_command(
        command_id: UUID,
        body: MobileCommandAck,
        authorization: str | None = Header(default=None),
    ) -> MobileCommand:
        device = authenticated_device(authorization)
        try:
            command = services.mobile.acknowledge(
                command_id,
                device_id=device.id,
                receipt=body.receipt,
            )
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc
        except PermissionError as exc:
            raise _domain_error(exc, status_code=403) from exc
        except ValueError as exc:
            raise _domain_error(exc, status_code=409) from exc
        services.audit.append(
            "mobile.command_acknowledged",
            {"command_id": str(command.id), "device_id": str(command.device_id)},
        )
        return command

    @router.post("/mobile/messages", tags=["mobile"])
    async def mobile_message(
        body: ChatRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(authorization)
        return await run_chat(body, source=f"android:{device.id}")

    @router.post("/mobile/voice-turns", tags=["mobile", "voice"])
    async def mobile_voice_turn(
        request: Request,
        authorization: str | None = Header(default=None),
        x_audio_sample_rate: int = Header(default=16_000),
        x_audio_locale: str = Header(default="zh-TW"),
    ) -> dict[str, Any]:
        device = authenticated_device(authorization)
        return await process_voice_turn(
            request,
            source=f"android-voice:{device.id}",
            device_id=device.id,
            sample_rate=x_audio_sample_rate,
            locale=x_audio_locale,
        )

    @router.post("/voice-turns", tags=["voice"])
    async def desktop_voice_turn(
        request: Request,
        x_audio_sample_rate: int = Header(default=16_000),
        x_audio_locale: str = Header(default="zh-TW"),
    ) -> dict[str, Any]:
        return await process_voice_turn(
            request,
            source="desktop-voice",
            device_id=None,
            sample_rate=x_audio_sample_rate,
            locale=x_audio_locale,
        )

    @router.post("/realtime/client-secrets", tags=["realtime"])
    async def realtime_secret(
        body: RealtimeSecretRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="device access token required")
        try:
            access_token = authorization.removeprefix("Bearer ")
            device = services.devices.authenticate_access_token(access_token)
            response = services.realtime.request_client_secret(
                device_id=device.id,
                requested_mode=body.requested_mode,
            )
        except (KeyError, ValueError, PermissionError) as exc:
            raise _domain_error(exc, status_code=403) from exc
        return response.model_dump(mode="json")

    @router.post("/workers", response_model=WorkerPresence, tags=["workers"])
    async def register_worker(body: WorkerRegister) -> WorkerPresence:
        return services.workers.register(
            body.worker_id,
            display_name=body.display_name,
            capabilities=body.capabilities,
        )

    @router.post(
        "/workers/{worker_id}/heartbeat",
        response_model=WorkerPresence,
        tags=["workers"],
    )
    async def worker_heartbeat(worker_id: str, body: WorkerHeartbeat) -> WorkerPresence:
        try:
            return services.workers.heartbeat(worker_id, degraded=body.degraded)
        except KeyError as exc:
            raise _domain_error(exc, status_code=404) from exc

    @router.get("/workers", response_model=list[WorkerPresence], tags=["workers"])
    async def workers() -> list[WorkerPresence]:
        return list(services.workers.list())

    return router
