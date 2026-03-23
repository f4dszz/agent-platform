"""Step-level agent execution helpers.

This module owns the lifecycle of a single run step: approval gating, provider
invocation, artifact extraction, persistence, and failure handling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.run_step import RunStep
from app.services.agent_execution import (
    AgentExecutionFailed,
    build_transient_agent_message,
    call_agent,
    create_agent_artifact,
    format_agent_failure_message,
    persist_agent_response,
    persist_system_message,
    sync_runtime_to_memory,
)
from app.services.artifact_extractor import ExtractedArtifact, extract_artifact
from app.services.collaboration_policy import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_FAILED,
    register_review_round,
    register_step,
    stop_run,
)
from app.services.collaboration_runtime import (
    PermissionEscalationRequired,
    create_agent_event,
    create_approval_request,
    create_run_step,
    get_run_permission_override,
    permission_rank,
    pick_higher_permission,
    update_run_step,
)
from app.services.run_hooks import RunHooks

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentStepResult:
    message: Message | None
    raw_content: str | None
    extracted: ExtractedArtifact | None
    step: RunStep
    paused: bool = False
    failed: bool = False
    approval: ApprovalRequest | None = None


async def _run_agent_call(
    db: AsyncSession,
    room_id: str,
    agent_config: AgentConfig,
    prompt: str,
    hooks: RunHooks,
    stream_message: Message | None = None,
    *,
    manage_room_memory: bool = True,
    override_permission_mode: str | None = None,
) -> tuple[AgentConfig, str]:
    await hooks.emit_status(agent_config.name, "working")

    async def handle_stream(content: str) -> None:
        if stream_message:
            await hooks.emit_stream(stream_message, content)

    try:
        if hooks.on_stream and stream_message:
            return await call_agent(
                agent_config,
                prompt,
                on_stream=handle_stream,
                db=db,
                room_id=room_id,
                manage_room_memory=manage_room_memory,
                override_permission_mode=override_permission_mode,
            )
        return await call_agent(
            agent_config,
            prompt,
            db=db,
            room_id=room_id,
            manage_room_memory=manage_room_memory,
            override_permission_mode=override_permission_mode,
        )
    finally:
        await hooks.emit_status(agent_config.name, "idle")


async def _handle_agent_step_failure(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    step: RunStep,
    step_type: str,
    agent_config: AgentConfig,
    error: AgentExecutionFailed,
    hooks: RunHooks,
    emit_run_update: bool,
) -> AgentStepResult:
    failure_message = format_agent_failure_message(agent_config, step_type, error)
    system_message = await persist_system_message(
        db,
        run.room_id,
        content=failure_message,
    )
    await update_run_step(
        db,
        step,
        status="failed",
        content=failure_message,
        metadata={
            "error_type": error.error_type,
            "error_text": error.error_text,
        },
    )
    failed_event = await create_agent_event(
        db,
        run,
        event_type="step_failed",
        agent_name=agent_config.name,
        step=step,
        source_message=system_message,
        content=failure_message,
        payload={
            "step_type": step_type,
            "error_type": error.error_type,
        },
    )
    stop_run(run, RUN_STATUS_FAILED, f"{step_type}_failed")
    await db.flush()
    if emit_run_update:
        await hooks.emit_run_update(run)
    await hooks.emit_step(step)
    await hooks.emit_event(failed_event)
    await hooks.emit_response(system_message)
    return AgentStepResult(
        message=system_message,
        raw_content=None,
        extracted=None,
        step=step,
        failed=True,
    )


async def _resolve_effective_permission_mode(
    db: AsyncSession,
    run: CollaborationRun,
    agent_config: AgentConfig,
) -> str:
    override_mode = await get_run_permission_override(db, run.id, agent_config.name)
    return pick_higher_permission(agent_config.permission_mode, override_mode)


async def _pause_for_approval(
    db: AsyncSession,
    run: CollaborationRun,
    step: RunStep,
    *,
    source_message: Message,
    agent_config: AgentConfig,
    requested_permission_mode: str,
    reason: str,
    resume_kind: str,
    resume_payload: dict[str, Any],
    error_text: str | None,
    hooks: RunHooks,
) -> ApprovalRequest:
    await update_run_step(
        db,
        step,
        status="pending_approval",
        content=reason,
        metadata={
            "requested_permission_mode": requested_permission_mode,
            "error_text": error_text,
        },
    )
    approval = await create_approval_request(
        db,
        run,
        agent_name=agent_config.name,
        requested_permission_mode=requested_permission_mode,
        reason=reason,
        step=step,
        source_message=source_message,
        resume_kind=resume_kind,
        resume_payload=resume_payload,
        error_text=error_text,
    )
    event = await create_agent_event(
        db,
        run,
        event_type="approval_requested",
        agent_name=agent_config.name,
        step=step,
        source_message=source_message,
        content=reason,
        payload={
            "requested_permission_mode": requested_permission_mode,
            "approval_id": approval.id,
        },
    )
    stop_run(run, RUN_STATUS_BLOCKED, "approval_required")
    await db.flush()
    await hooks.emit_step(step)
    await hooks.emit_approval(approval)
    await hooks.emit_event(event)
    await hooks.emit_run_update(run)
    return approval


async def execute_agent_step(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    source_message: Message,
    agent_config: AgentConfig,
    prompt: str,
    step_type: str,
    step_title: str,
    hooks: RunHooks,
    default_artifact_type: str | None = None,
    default_status: str | None = None,
    count_as_review: bool = False,
    required_permission_mode: str | None = None,
    allow_approval: bool = False,
    emit_run_update: bool = True,
    resume_kind: str | None = None,
    resume_payload: dict[str, Any] | None = None,
    run_agent_call_impl: Callable[..., Awaitable[tuple[AgentConfig, str]]] | None = None,
) -> AgentStepResult:
    step = await create_run_step(
        db,
        run,
        step_type=step_type,
        status="working",
        agent_name=agent_config.name,
        source_message=source_message,
        title=step_title,
        content=None,
        metadata={"phase": step_type},
    )
    started_event = await create_agent_event(
        db,
        run,
        event_type="step_started",
        agent_name=agent_config.name,
        step=step,
        source_message=source_message,
        content=step_title,
        payload={"step_type": step_type},
    )
    await hooks.emit_step(step)
    await hooks.emit_event(started_event)

    effective_permission_mode = await _resolve_effective_permission_mode(
        db,
        run,
        agent_config,
    )
    if (
        allow_approval
        and required_permission_mode
        and permission_rank(required_permission_mode)
        > permission_rank(effective_permission_mode)
    ):
        approval = await _pause_for_approval(
            db,
            run,
            step,
            source_message=source_message,
            agent_config=agent_config,
            requested_permission_mode=required_permission_mode,
            reason=(
                f"{agent_config.display_name} needs {required_permission_mode} "
                "permission before continuing this step."
            ),
            resume_kind=resume_kind or "target_cycle",
            resume_payload=resume_payload or {},
            error_text=None,
            hooks=hooks,
        )
        return AgentStepResult(
            message=None,
            raw_content=None,
            extracted=None,
            step=step,
            paused=True,
            approval=approval,
        )

    transient_message = build_transient_agent_message(run.room_id, agent_config)
    run_agent_call = run_agent_call_impl or _run_agent_call
    try:
        _, response_text = await run_agent_call(
            db,
            run.room_id,
            agent_config,
            prompt,
            hooks,
            stream_message=transient_message,
            manage_room_memory=False,
            override_permission_mode=effective_permission_mode,
        )
    except PermissionEscalationRequired as exc:
        if allow_approval:
            approval = await _pause_for_approval(
                db,
                run,
                step,
                source_message=source_message,
                agent_config=agent_config,
                requested_permission_mode=exc.requested_permission_mode,
                reason=exc.reason,
                resume_kind=resume_kind or "target_cycle",
                resume_payload=resume_payload or {},
                error_text=exc.error_text,
                hooks=hooks,
            )
            return AgentStepResult(
                message=None,
                raw_content=None,
                extracted=None,
                step=step,
                paused=True,
                approval=approval,
            )
        logger.error("Permission escalation required but approval disabled: %s", exc)
        return await _handle_agent_step_failure(
            db,
            run,
            step=step,
            step_type=step_type,
            agent_config=agent_config,
            error=AgentExecutionFailed(
                agent_name=agent_config.name,
                agent_display_name=agent_config.display_name,
                error_type="permission_denied",
                error_text=exc.error_text,
            ),
            hooks=hooks,
            emit_run_update=emit_run_update,
        )
    except AgentExecutionFailed as exc:
        return await _handle_agent_step_failure(
            db,
            run,
            step=step,
            step_type=step_type,
            agent_config=agent_config,
            error=exc,
            hooks=hooks,
            emit_run_update=emit_run_update,
        )

    extracted = extract_artifact(
        response_text,
        default_artifact_type=default_artifact_type,
        default_status=default_status,
    )
    agent_message = await persist_agent_response(
        db,
        run.room_id,
        transient_message,
        agent_config,
        response_text,
        extracted,
    )
    register_step(run)
    if count_as_review:
        register_review_round(run)
    await sync_runtime_to_memory(db, run.room_id, agent_config.name)
    artifact = await create_agent_artifact(
        db,
        run,
        agent_message,
        agent_config.name,
        extracted,
        hooks=hooks,
    )
    step.source_message_id = agent_message.id
    await update_run_step(
        db,
        step,
        status="completed",
        title=extracted.title or step_title,
        content=extracted.clean_content,
        metadata={
            "artifact_type": extracted.artifact_type,
            "artifact_status": extracted.status,
            "artifact_id": artifact.id if artifact else None,
        },
    )
    completed_event = await create_agent_event(
        db,
        run,
        event_type="step_completed",
        agent_name=agent_config.name,
        step=step,
        source_message=agent_message,
        content=extracted.title or extracted.clean_content[:160],
        payload={
            "step_type": step_type,
            "artifact_type": extracted.artifact_type,
            "status": extracted.status,
        },
    )
    await db.flush()
    if emit_run_update:
        await hooks.emit_run_update(run)
    await hooks.emit_step(step)
    await hooks.emit_event(completed_event)
    await hooks.emit_response(agent_message)
    return AgentStepResult(
        message=agent_message,
        raw_content=response_text,
        extracted=extracted,
        step=step,
    )
