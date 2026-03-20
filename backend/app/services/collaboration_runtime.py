import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.run_step import RunStep

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_DENIED = "denied"

PERMISSION_ORDER = {
    "default": 0,
    "plan": 0,
    "acceptEdits": 1,
    "bypassPermissions": 2,
}

_PERMISSION_ERROR_MARKERS = (
    "permission denied",
    "approval required",
    "requires approval",
    "sandbox",
    "not allowed",
    "danger-full-access",
    "dangerously-bypass",
    "dangerously skip permissions",
    "cannot write",
    "read-only",
)


@dataclass(slots=True)
class PermissionEscalationRequired(RuntimeError):
    agent_name: str
    requested_permission_mode: str
    reason: str
    error_text: str

    def __str__(self) -> str:
        return self.reason


def dumps_payload(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=True)


def loads_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def permission_rank(permission_mode: str | None) -> int:
    if permission_mode is None:
        return 0
    return PERMISSION_ORDER.get(permission_mode, 0)


def pick_higher_permission(*permission_modes: str | None) -> str:
    ranked = [(permission_rank(mode), mode or "plan") for mode in permission_modes]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def next_permission_mode(current_mode: str | None, error_text: str | None = None) -> str:
    text = (error_text or "").lower()
    if current_mode in {"plan", "default", None}:
        return "acceptEdits"
    if "sandbox" in text or "danger" in text or "permission denied" in text:
        return "bypassPermissions"
    return "bypassPermissions"


def is_permission_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(marker in lowered for marker in _PERMISSION_ERROR_MARKERS)


async def get_run_permission_override(
    db: AsyncSession,
    run_id: str,
    agent_name: str,
) -> str | None:
    stmt = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.run_id == run_id,
            ApprovalRequest.agent_name == agent_name,
            ApprovalRequest.status == APPROVAL_STATUS_APPROVED,
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    result = await db.execute(stmt)
    approved = list(result.scalars().all())
    if not approved:
        return None
    return pick_higher_permission(
        *(item.requested_permission_mode for item in approved),
    )


async def create_run_step(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    step_type: str,
    status: str,
    agent_name: str | None = None,
    source_message: Message | None = None,
    title: str | None = None,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunStep:
    step = RunStep(
        run_id=run.id,
        room_id=run.room_id,
        source_message_id=source_message.id if source_message else None,
        agent_name=agent_name,
        step_type=step_type,
        status=status,
        title=title,
        content=content,
        metadata_json=dumps_payload(metadata),
    )
    db.add(step)
    await db.flush()
    return step


async def update_run_step(
    db: AsyncSession,
    step: RunStep,
    *,
    status: str | None = None,
    title: str | None = None,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunStep:
    if status is not None:
        step.status = status
    if title is not None:
        step.title = title
    if content is not None:
        step.content = content
    if metadata is not None:
        step.metadata_json = dumps_payload(metadata)
    step.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return step


async def create_agent_event(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    event_type: str,
    agent_name: str | None = None,
    step: RunStep | None = None,
    source_message: Message | None = None,
    content: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentEvent:
    event = AgentEvent(
        run_id=run.id,
        room_id=run.room_id,
        step_id=step.id if step else None,
        source_message_id=source_message.id if source_message else None,
        agent_name=agent_name,
        event_type=event_type,
        content=content,
        payload_json=dumps_payload(payload),
    )
    db.add(event)
    await db.flush()
    return event


async def create_approval_request(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    agent_name: str,
    requested_permission_mode: str,
    reason: str,
    step: RunStep | None = None,
    source_message: Message | None = None,
    resume_kind: str | None = None,
    resume_payload: dict[str, Any] | None = None,
    error_text: str | None = None,
) -> ApprovalRequest:
    approval = ApprovalRequest(
        run_id=run.id,
        room_id=run.room_id,
        step_id=step.id if step else None,
        source_message_id=source_message.id if source_message else None,
        agent_name=agent_name,
        requested_permission_mode=requested_permission_mode,
        status=APPROVAL_STATUS_PENDING,
        reason=reason,
        resume_kind=resume_kind,
        resume_payload=dumps_payload(resume_payload),
        error_text=error_text,
    )
    db.add(approval)
    await db.flush()
    return approval


def resolve_approval(approval: ApprovalRequest, status: str) -> ApprovalRequest:
    approval.status = status
    approval.resolved_at = datetime.now(timezone.utc)
    return approval
