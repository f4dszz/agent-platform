"""Message orchestrator for native agent collaboration runs."""

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.run_step import RunStep
from app.services.artifact_extractor import extract_artifact
from app.services.agent_execution import (
    AGENT_CLASSES,
    AgentExecutionFailed,
    build_transient_agent_message as _build_transient_agent_message,
    call_agent as _call_agent,
    create_agent_artifact as _create_agent_artifact,
    format_agent_failure_message as _format_agent_failure_message,
    hydrate_runtime_from_memory as _hydrate_runtime_from_memory,
    persist_agent_response as _persist_agent_response,
    persist_system_message as _persist_system_message,
    sync_runtime_to_memory as _sync_runtime_to_memory,
)
from app.services.collaboration_policy import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_STOPPED,
    finalize_run_from_artifact,
    register_review_round,
    register_step,
    should_stop_for_limits,
    stop_run,
)
from app.services.collaboration_runtime import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_DENIED,
    create_agent_event,
    create_run_step,
    is_permission_error,
    loads_payload,
    next_permission_mode,
    resolve_approval,
)
from app.services.message_parser import (
    extract_agent_handoff_request,
    extract_agent_handoff_targets,
    extract_mentions,
    extract_referenced_agent_names,
    extract_review_targets,
    strip_control_syntax,
)
from app.services.prompt_builder import (
    PLATFORM_AGENT_SYSTEM_PROMPT,
    build_decision_prompt,
    build_human_collaboration_hint,
    build_owner_confirmation_prompt,
    build_primary_step_prompt,
    build_prompt_with_history,
    build_review_prompt,
    build_revision_prompt,
    get_git_context,
)
from app.services.run_intent import CollaborationIntent, build_collaboration_intent
from app.services.run_hooks import (
    ArtifactCallback,
    ApprovalCallback,
    EventCallback,
    ResponseCallback,
    RunCallback,
    RunHooks,
    StatusCallback,
    StepCallback,
    StreamCallback,
)
from app.services.session_manager import session_manager
from app.services.step_execution import (
    AgentStepResult,
    execute_agent_step as _execute_agent_step,
)

logger = logging.getLogger(__name__)

MAX_AGENT_CHAIN_DEPTH = 4
REVIEW_REVISE_STATUSES = {"revise", "changes_requested"}
REVIEW_BLOCKED_STATUSES = {"blocked"}


@dataclass(slots=True)
class CycleResult:
    responses: list[Message]
    paused: bool = False


@dataclass(slots=True)
class ParallelTargetResult:
    transient_message: Message
    agent_config: AgentConfig
    response_text: str | None = None
    failure: AgentExecutionFailed | None = None


_build_prompt_with_history = build_prompt_with_history


def _get_git_context() -> str:
    return get_git_context()


async def _build_review_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    primary_response: str,
    *,
    task_kind: str = "deliverable",
) -> str:
    git_context = await asyncio.to_thread(_get_git_context)
    return await build_review_prompt(
        original_request,
        primary_agent,
        primary_response,
        git_context=git_context,
        task_kind=task_kind,
    )


async def _build_decision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    plan_text: str,
    review_texts: list[str],
) -> str:
    return await build_decision_prompt(
        original_request,
        primary_agent,
        plan_text,
        review_texts,
    )


async def _build_revision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    previous_output: str,
    review_texts: list[str],
    *,
    task_kind: str = "deliverable",
    artifact_type: str = "plan",
) -> str:
    return await build_revision_prompt(
        original_request,
        primary_agent,
        previous_output,
        review_texts,
        task_kind=task_kind,
        artifact_type=artifact_type,
    )


async def _build_owner_confirmation_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    latest_output: str,
    review_texts: list[str],
) -> str:
    return await build_owner_confirmation_prompt(
        original_request,
        primary_agent,
        latest_output,
        review_texts,
    )


def _build_human_collaboration_hint(
    message_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
    review_targets: list[str],
) -> str:
    return build_human_collaboration_hint(
        message_content,
        enabled_agents,
        primary_targets,
        review_targets,
    )


def _build_hooks(
    *,
    on_response: ResponseCallback | None = None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
) -> RunHooks:
    return RunHooks(
        on_response=on_response,
        on_status=on_status,
        on_stream=on_stream,
        on_run_update=on_run_update,
        on_artifact=on_artifact,
        on_step=on_step,
        on_event=on_event,
        on_approval=on_approval,
    )


async def _get_collaboration_run(
    db: AsyncSession,
    run_id: str | None,
) -> CollaborationRun | None:
    if not run_id:
        return None
    result = await db.execute(
        select(CollaborationRun).where(CollaborationRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def _get_or_create_collaboration_run(
    db: AsyncSession,
    message: Message,
    intent: CollaborationIntent,
    run_id: str | None = None,
) -> CollaborationRun:
    existing = await _get_collaboration_run(db, run_id)
    if existing:
        return existing

    kwargs: dict = {}
    if intent.max_review_rounds is not None:
        kwargs["max_review_rounds"] = intent.max_review_rounds
    if intent.max_steps is not None:
        kwargs["max_steps"] = intent.max_steps
    run = CollaborationRun(
        room_id=message.room_id,
        root_message_id=message.id,
        initiator_type=message.sender_type,
        mode=intent.mode,
        status=RUN_STATUS_RUNNING,
        **kwargs,
    )
    db.add(run)
    await db.flush()
    return run


async def _emit_run_update(
    run: CollaborationRun | None,
    hooks: RunHooks,
) -> None:
    if run:
        await hooks.emit_run_update(run)


async def _emit_step_update(
    step: RunStep | None,
    hooks: RunHooks,
) -> None:
    if step:
        await hooks.emit_step(step)


async def _emit_event(
    event: AgentEvent | None,
    hooks: RunHooks,
) -> None:
    if event:
        await hooks.emit_event(event)


async def _emit_approval(
    approval: ApprovalRequest | None,
    hooks: RunHooks,
) -> None:
    if approval:
        await hooks.emit_approval(approval)


def _resolve_sender_agent_names(
    message: Message,
    enabled_agents: list[AgentConfig],
) -> set[str]:
    if message.sender_type == "human":
        return set()

    sender_type = message.sender_type.lower()
    sender_name = message.sender_name.lower()
    resolved = {sender_type}

    for agent in enabled_agents:
        if (
            agent.agent_type.lower() == sender_type
            or agent.display_name.lower() == sender_name
            or agent.name.lower() == sender_name
        ):
            resolved.add(agent.name.lower())

    return resolved


async def get_enabled_agents(db: AsyncSession) -> list[AgentConfig]:
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.enabled.is_(True))
    )
    return list(result.scalars().all())


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
            return await _call_agent(
                agent_config,
                prompt,
                on_stream=handle_stream,
                db=db,
                room_id=room_id,
                manage_room_memory=manage_room_memory,
                override_permission_mode=override_permission_mode,
            )
        return await _call_agent(
            agent_config,
            prompt,
            db=db,
            room_id=room_id,
            manage_room_memory=manage_room_memory,
            override_permission_mode=override_permission_mode,
        )
    finally:
        await hooks.emit_status(agent_config.name, "idle")


async def _run_parallel_targets(
    message: Message,
    db: AsyncSession,
    *,
    run: CollaborationRun,
    targets: list[AgentConfig],
    prompt_by_agent: dict[str, str],
    hooks: RunHooks,
    chain_depth: int,
    agent_chain: tuple[str, ...],
) -> list[Message]:
    responses: list[Message] = []

    async def run_target(
        cfg: AgentConfig,
        transient_message: Message,
    ) -> ParallelTargetResult:
        try:
            agent_config, response_text = await _run_agent_call(
                db,
                message.room_id,
                cfg,
                prompt_by_agent[cfg.name.lower()],
                hooks,
                stream_message=transient_message,
                manage_room_memory=False,
            )
            return ParallelTargetResult(
                transient_message=transient_message,
                agent_config=agent_config,
                response_text=response_text,
            )
        except AgentExecutionFailed as exc:
            return ParallelTargetResult(
                transient_message=transient_message,
                agent_config=cfg,
                failure=exc,
            )
        except Exception as e:
            logger.error("Agent call failed for %s: %s", cfg.name, e)
            return ParallelTargetResult(
                transient_message=transient_message,
                agent_config=cfg,
                failure=AgentExecutionFailed(
                    agent_name=cfg.name,
                    agent_display_name=cfg.display_name,
                    error_type="runtime_error",
                    error_text=str(e),
                ),
            )

    tasks = [
        asyncio.create_task(
            run_target(cfg, _build_transient_agent_message(message.room_id, cfg))
        )
        for cfg in targets
    ]

    for task in asyncio.as_completed(tasks):
        result = await task
        if result.failure:
            failure_message = _format_agent_failure_message(
                result.agent_config,
                "agent_response",
                result.failure,
            )
            system_message = await _persist_system_message(
                db,
                message.room_id,
                content=failure_message,
            )
            step = await create_run_step(
                db,
                run,
                step_type="agent_response",
                status="failed",
                agent_name=result.agent_config.name,
                source_message=system_message,
                title=f"{result.agent_config.display_name} failed",
                content=failure_message,
                metadata={
                    "error_type": result.failure.error_type,
                    "error_text": result.failure.error_text,
                },
            )
            event = await create_agent_event(
                db,
                run,
                event_type="step_failed",
                agent_name=result.agent_config.name,
                step=step,
                source_message=system_message,
                content=failure_message,
                payload={"step_type": "agent_response"},
            )
            await _emit_step_update(step, hooks)
            await _emit_event(event, hooks)
            responses.append(system_message)
            await hooks.emit_response(system_message)
            continue

        transient_message = result.transient_message
        agent_config = result.agent_config
        response_text = result.response_text or ""
        extracted = extract_artifact(response_text)
        agent_message = await _persist_agent_response(
            db,
            message.room_id,
            transient_message,
            agent_config,
            response_text,
            extracted,
        )
        register_step(run)
        await _sync_runtime_to_memory(db, message.room_id, agent_config.name)
        artifact = await _create_agent_artifact(
            db,
            run,
            agent_message,
            agent_config.name,
            extracted,
            hooks=hooks,
        )
        step = await create_run_step(
            db,
            run,
            step_type="agent_response",
            status="completed",
            agent_name=agent_config.name,
            source_message=agent_message,
            title=extracted.title or f"{agent_config.display_name} responded",
            content=extracted.clean_content,
            metadata={
                "artifact_type": extracted.artifact_type,
                "artifact_status": extracted.status,
                "artifact_id": artifact.id if artifact else None,
            },
        )
        event = await create_agent_event(
            db,
            run,
            event_type="step_completed",
            agent_name=agent_config.name,
            step=step,
            source_message=agent_message,
            content=step.title,
            payload={"step_type": "agent_response"},
        )
        await _emit_run_update(run, hooks)
        await _emit_step_update(step, hooks)
        await _emit_event(event, hooks)
        responses.append(agent_message)
        await hooks.emit_response(agent_message)

        if run.status == RUN_STATUS_RUNNING:
            chained_responses = await route_message(
                agent_message,
                db,
                hooks=hooks,
                chain_depth=chain_depth + 1,
                agent_chain=(*agent_chain, agent_config.name.lower()),
                run_id=run.id,
                raw_content_override=response_text,
            )
            responses.extend(chained_responses)

    return responses


async def _run_target_cycle(
    message: Message,
    db: AsyncSession,
    *,
    run: CollaborationRun,
    agent_config: AgentConfig,
    reviewer_configs: list[AgentConfig],
    intent: CollaborationIntent,
    clean_content: str,
    primary_prompt: str,
    hooks: RunHooks,
    chain_depth: int = 0,
    agent_chain: tuple[str, ...] = (),
    primary_phase: str = "plan",
) -> CycleResult:
    responses: list[Message] = []
    if intent.task_kind == "content_iteration":
        primary_step_type = "content_revision" if primary_phase == "revision" else "content_draft"
    else:
        primary_step_type = "revision" if primary_phase == "revision" else "plan"
    primary_title = (
        f"{agent_config.display_name} revising after review"
        if primary_phase == "revision"
        else f"{agent_config.display_name} drafting the current solution"
    )
    primary_result = await _execute_agent_step(
        db,
        run,
        source_message=message,
        agent_config=agent_config,
        prompt=primary_prompt,
        step_type=primary_step_type,
        step_title=primary_title,
        hooks=hooks,
        default_artifact_type=intent.primary_artifact_type if reviewer_configs else None,
        required_permission_mode=intent.required_permission_mode,
        allow_approval=True,
        resume_kind="target_cycle",
        resume_payload={
            "source_message_id": message.id,
            "clean_content": clean_content,
            "agent_name": agent_config.name,
            "reviewer_names": [reviewer.name for reviewer in reviewer_configs],
            "mode": intent.mode,
            "wants_revision_loop": intent.wants_revision_loop,
            "require_decision": intent.require_decision,
            "required_permission_mode": intent.required_permission_mode,
            "prompt": primary_prompt,
            "chain_depth": chain_depth,
            "agent_chain": list(agent_chain),
            "primary_phase": primary_phase,
        },
        run_agent_call_impl=_run_agent_call,
    )
    if primary_result.failed:
        if primary_result.message:
            responses.append(primary_result.message)
        return CycleResult(responses=responses, paused=False)
    if primary_result.paused or not primary_result.message or not primary_result.extracted:
        return CycleResult(responses=responses, paused=True)
    responses.append(primary_result.message)
    current_primary = primary_result

    follow_up_message = current_primary.message
    follow_up_raw_content = current_primary.raw_content or current_primary.message.content

    if reviewer_configs:
        while run.status == RUN_STATUS_RUNNING:
            limit_reason = should_stop_for_limits(run)
            if limit_reason:
                stop_run(run, RUN_STATUS_STOPPED, limit_reason)
                await _emit_run_update(run, hooks)
                break

            review_texts: list[str] = []
            review_statuses: set[str] = set()
            for reviewer_config in reviewer_configs:
                review_prompt = await _build_review_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                    task_kind=intent.task_kind,
                )
                review_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=current_primary.message,
                    agent_config=reviewer_config,
                    prompt=review_prompt,
                    step_type="content_review" if intent.task_kind == "content_iteration" else "review",
                    step_title=f"{reviewer_config.display_name} reviewing the latest output",
                    hooks=hooks,
                    default_artifact_type="review",
                    count_as_review=True,
                    allow_approval=False,
                    run_agent_call_impl=_run_agent_call,
                )
                if review_result.failed:
                    if review_result.message:
                        responses.append(review_result.message)
                    return CycleResult(responses=responses, paused=False)
                if review_result.paused or not review_result.message or not review_result.extracted:
                    return CycleResult(responses=responses, paused=True)
                responses.append(review_result.message)
                review_texts.append(review_result.extracted.clean_content)
                if review_result.extracted.status:
                    review_statuses.add(review_result.extracted.status)

            if review_statuses & REVIEW_BLOCKED_STATUSES:
                stop_run(run, RUN_STATUS_BLOCKED, "review_blocked")
                await _emit_run_update(run, hooks)
                break

            if intent.wants_revision_loop and review_statuses & REVIEW_REVISE_STATUSES:
                limit_reason = should_stop_for_limits(run)
                if limit_reason:
                    stop_run(run, RUN_STATUS_STOPPED, limit_reason)
                    await _emit_run_update(run, hooks)
                    break

                revision_prompt = await _build_revision_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                    review_texts,
                    task_kind=intent.task_kind,
                    artifact_type=intent.primary_artifact_type or "plan",
                )
                revision_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=follow_up_message,
                    agent_config=agent_config,
                    prompt=revision_prompt,
                    step_type="content_revision" if intent.task_kind == "content_iteration" else "revision",
                    step_title=f"{agent_config.display_name} revising after review",
                    hooks=hooks,
                    default_artifact_type=intent.primary_artifact_type,
                    required_permission_mode=intent.required_permission_mode,
                    allow_approval=True,
                    resume_kind="target_cycle",
                    resume_payload={
                        "source_message_id": follow_up_message.id,
                        "clean_content": clean_content,
                        "agent_name": agent_config.name,
                        "reviewer_names": [reviewer.name for reviewer in reviewer_configs],
                        "mode": intent.mode,
                        "wants_revision_loop": intent.wants_revision_loop,
                        "require_decision": intent.require_decision,
                        "required_permission_mode": intent.required_permission_mode,
                        "prompt": revision_prompt,
                        "chain_depth": chain_depth,
                        "agent_chain": list(agent_chain),
                        "primary_phase": "revision",
                    },
                    run_agent_call_impl=_run_agent_call,
                )
                if (
                    revision_result.failed
                    or (
                    revision_result.paused
                    or not revision_result.message
                    or not revision_result.extracted
                    )
                ):
                    if revision_result.failed and revision_result.message:
                        responses.append(revision_result.message)
                        return CycleResult(responses=responses, paused=False)
                    return CycleResult(responses=responses, paused=True)
                responses.append(revision_result.message)
                current_primary = revision_result
                follow_up_message = revision_result.message
                follow_up_raw_content = (
                    revision_result.raw_content or revision_result.message.content
                )
                continue

            if (
                intent.decision_style == "owner_confirmation"
                and run.status == RUN_STATUS_RUNNING
                and review_statuses
                and review_statuses <= {"approved"}
            ):
                confirmation_prompt = await _build_owner_confirmation_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                    review_texts,
                )
                confirmation_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=current_primary.message,
                    agent_config=agent_config,
                    prompt=confirmation_prompt,
                    step_type="owner_confirmation",
                    step_title=f"{agent_config.display_name} confirming the latest content",
                    hooks=hooks,
                    default_artifact_type=intent.primary_artifact_type,
                    allow_approval=False,
                    emit_run_update=False,
                    run_agent_call_impl=_run_agent_call,
                )
                if (
                    confirmation_result.failed
                    or (
                        confirmation_result.paused
                        or not confirmation_result.message
                        or not confirmation_result.extracted
                    )
                ):
                    if confirmation_result.failed and confirmation_result.message:
                        responses.append(confirmation_result.message)
                        return CycleResult(responses=responses, paused=False)
                    return CycleResult(responses=responses, paused=True)
                responses.append(confirmation_result.message)
                confirmation_status = confirmation_result.extracted.status
                if confirmation_status in {"approved", "completed"}:
                    stop_run(run, RUN_STATUS_COMPLETED, "owner_confirmed")
                    await _emit_run_update(run, hooks)
                    follow_up_message = confirmation_result.message
                    follow_up_raw_content = (
                        confirmation_result.raw_content
                        or confirmation_result.message.content
                    )
                    break
                if confirmation_status in REVIEW_BLOCKED_STATUSES:
                    stop_run(run, RUN_STATUS_BLOCKED, "owner_confirmation_blocked")
                    await _emit_run_update(run, hooks)
                    break
                current_primary = confirmation_result
                follow_up_message = confirmation_result.message
                follow_up_raw_content = (
                    confirmation_result.raw_content or confirmation_result.message.content
                )
                continue

            if (
                intent.require_decision
                and intent.decision_style == "readiness"
                and run.status == RUN_STATUS_RUNNING
            ):
                decision_prompt = await _build_decision_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                    review_texts,
                )
                decision_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=current_primary.message,
                    agent_config=agent_config,
                    prompt=decision_prompt,
                    step_type="decision",
                    step_title=f"{agent_config.display_name} making the final decision",
                    hooks=hooks,
                    default_artifact_type="decision",
                    allow_approval=False,
                    emit_run_update=False,
                    run_agent_call_impl=_run_agent_call,
                )
                if (
                    decision_result.failed
                    or (
                    decision_result.paused
                    or not decision_result.message
                    or not decision_result.extracted
                    )
                ):
                    if decision_result.failed and decision_result.message:
                        responses.append(decision_result.message)
                        return CycleResult(responses=responses, paused=False)
                    return CycleResult(responses=responses, paused=True)
                responses.append(decision_result.message)
                finalize_run_from_artifact(
                    run,
                    decision_result.extracted.artifact_type,
                    decision_result.extracted.status,
                )
                await _emit_run_update(run, hooks)
                follow_up_message = decision_result.message
                follow_up_raw_content = (
                    decision_result.raw_content or decision_result.message.content
                )
            break

    if run.status == RUN_STATUS_RUNNING:
        chained_agents = (
            *agent_chain,
            agent_config.name.lower(),
            *(reviewer.name.lower() for reviewer in reviewer_configs),
        )
        chained_responses = await route_message(
            follow_up_message,
            db,
            hooks=hooks,
            chain_depth=chain_depth + 1,
            agent_chain=chained_agents,
            run_id=run.id,
            raw_content_override=follow_up_raw_content,
        )
        responses.extend(chained_responses)

    return CycleResult(responses=responses, paused=False)


async def route_message(
    message: Message,
    db: AsyncSession,
    on_response: ResponseCallback | None = None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    chain_depth: int = 0,
    agent_chain: tuple[str, ...] = (),
    run_id: str | None = None,
    raw_content_override: str | None = None,
    hooks: RunHooks | None = None,
) -> list[Message]:
    hooks = hooks or _build_hooks(
        on_response=on_response,
        on_status=on_status,
        on_stream=on_stream,
        on_run_update=on_run_update,
        on_artifact=on_artifact,
        on_step=on_step,
        on_event=on_event,
        on_approval=on_approval,
    )
    raw_content = raw_content_override or message.content

    run = await _get_collaboration_run(db, run_id)
    if chain_depth > MAX_AGENT_CHAIN_DEPTH:
        logger.warning("Agent chain depth exceeded for room %s", message.room_id)
        if run and run.status == RUN_STATUS_RUNNING:
            stop_run(run, RUN_STATUS_STOPPED, "max_agent_chain_depth_exceeded")
            await db.flush()
            await _emit_run_update(run, hooks)
        return []

    if message.sender_type == "human":
        mentions = extract_mentions(raw_content)
        clean_content = strip_control_syntax(raw_content)
    else:
        mentions = extract_agent_handoff_targets(raw_content)
        clean_content = extract_agent_handoff_request(raw_content)

    if not mentions:
        return []

    enabled_agents = await get_enabled_agents(db)
    agent_map = {a.name.lower(): a for a in enabled_agents}
    current_sender_agents = _resolve_sender_agent_names(message, enabled_agents)

    targets: list[AgentConfig] = []
    if "all" in mentions:
        targets = [
            agent
            for agent in enabled_agents
            if agent.name.lower() not in current_sender_agents
            and agent.name.lower() not in agent_chain
        ]
    else:
        seen_agents: set[str] = set()
        for mention in mentions:
            if (
                mention in agent_map
                and mention not in seen_agents
                and mention not in current_sender_agents
                and mention not in agent_chain
            ):
                targets.append(agent_map[mention])
                seen_agents.add(mention)

    if not targets:
        return []

    explicit_review_targets = extract_review_targets(raw_content)
    if message.sender_type == "human":
        intent = build_collaboration_intent(
            raw_content,
            enabled_agents,
            targets,
            explicit_review_targets,
        )
    else:
        intent = CollaborationIntent(
            mode="plan_review" if explicit_review_targets else "custom",
            review_targets=explicit_review_targets,
            wants_revision_loop=False,
            require_decision=bool(explicit_review_targets),
            required_permission_mode=None,
            task_kind="deliverable",
            primary_artifact_type="plan",
            decision_style="readiness" if explicit_review_targets else "none",
            max_review_rounds=None,
            max_steps=None,
        )
    reviewer_configs: list[AgentConfig] = []
    seen_reviewers: set[str] = set()
    primary_names = {target.name.lower() for target in targets}
    # If a reviewer is also listed as a primary target, move it to reviewers only
    review_set = set(intent.review_targets)
    if review_set & primary_names and len(targets) > 1:
        remaining = [t for t in targets if t.name.lower() not in review_set]
        if remaining:
            targets = remaining
        else:
            # Keep the first target as primary, rest become reviewers
            targets = targets[:1]
        primary_names = {t.name.lower() for t in targets}
    for reviewer_name in intent.review_targets:
        if (
            reviewer_name in agent_map
            and reviewer_name not in primary_names
            and reviewer_name not in seen_reviewers
        ):
            reviewer_configs.append(agent_map[reviewer_name])
            seen_reviewers.add(reviewer_name)

    existing_run = run
    run = await _get_or_create_collaboration_run(
        db,
        message,
        intent,
        run_id=run_id,
    )
    if not existing_run:
        started_event = await create_agent_event(
            db,
            run,
            event_type="run_started",
            source_message=message,
            content=f"Run started in {run.mode}",
            payload={"root_message_id": message.id},
        )
        await _emit_run_update(run, hooks)
        await _emit_event(started_event, hooks)

    if run.status != RUN_STATUS_RUNNING:
        return []

    limit_reason = should_stop_for_limits(run)
    if limit_reason:
        stop_run(run, RUN_STATUS_STOPPED, limit_reason)
        await db.flush()
        await _emit_run_update(run, hooks)
        return []

    prompt_request = clean_content
    if message.sender_type == "human":
        base_request = (
            clean_content
            + _build_human_collaboration_hint(
                raw_content,
                enabled_agents,
                targets,
                intent.review_targets,
            )
        )
        if reviewer_configs and len(targets) == 1:
            prompt_request = build_primary_step_prompt(
                base_request,
                reviewer_names=[reviewer.display_name for reviewer in reviewer_configs],
                task_kind=intent.task_kind,
                artifact_type=intent.primary_artifact_type,
            )
        else:
            prompt_request = base_request

    prompt_by_agent: dict[str, str] = {}
    for target in targets:
        await _hydrate_runtime_from_memory(db, message.room_id, target.name)
        prompt_by_agent[target.name.lower()] = await _build_prompt_with_history(
            db,
            message.room_id,
            target.name,
            prompt_request,
            message.id,
            include_current_message_in_history=message.sender_type != "human",
        )

    if len(targets) > 1 and not reviewer_configs:
        responses = await _run_parallel_targets(
            message,
            db,
            run=run,
            targets=targets,
            prompt_by_agent=prompt_by_agent,
            hooks=hooks,
            chain_depth=chain_depth,
            agent_chain=agent_chain,
        )
    else:
        cycle_result = await _run_target_cycle(
            message,
            db,
            run=run,
            agent_config=targets[0],
            reviewer_configs=reviewer_configs,
            intent=intent,
            clean_content=clean_content,
            primary_prompt=prompt_by_agent[targets[0].name.lower()],
            hooks=hooks,
            chain_depth=chain_depth,
            agent_chain=agent_chain,
        )
        responses = cycle_result.responses
        if cycle_result.paused:
            await db.flush()
            return responses

    if run.status == RUN_STATUS_RUNNING:
        stop_run(run, RUN_STATUS_COMPLETED, "no_further_actions")
        completed_event = await create_agent_event(
            db,
            run,
            event_type="run_completed",
            source_message=message,
            content="Run completed with no further actions",
            payload={"stop_reason": run.stop_reason},
        )
        await _emit_run_update(run, hooks)
        await _emit_event(completed_event, hooks)

    await db.flush()
    return responses


async def resume_approval_request(
    approval_id: str,
    db: AsyncSession,
    *,
    on_response: ResponseCallback | None = None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    hooks: RunHooks | None = None,
) -> CollaborationRun:
    hooks = hooks or _build_hooks(
        on_response=on_response,
        on_status=on_status,
        on_stream=on_stream,
        on_run_update=on_run_update,
        on_artifact=on_artifact,
        on_step=on_step,
        on_event=on_event,
        on_approval=on_approval,
    )
    approval_result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = approval_result.scalar_one_or_none()
    if not approval:
        raise ValueError("Approval request not found")
    if approval.status != APPROVAL_STATUS_APPROVED:
        raise ValueError("Approval request is not approved")
    if approval.resume_kind != "target_cycle":
        raise ValueError("Unsupported approval continuation")

    payload = loads_payload(approval.resume_payload)
    source_message_id = payload.get("source_message_id")
    if not source_message_id:
        raise ValueError("Approval continuation missing source message")

    run = await _get_collaboration_run(db, approval.run_id)
    if not run:
        raise ValueError("Collaboration run not found")
    run.status = RUN_STATUS_RUNNING
    run.stop_reason = None

    source_message_result = await db.execute(
        select(Message).where(Message.id == source_message_id)
    )
    source_message = source_message_result.scalar_one_or_none()
    if not source_message:
        raise ValueError("Approval continuation source message not found")

    agent_result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == payload.get("agent_name"))
    )
    agent_config = agent_result.scalar_one_or_none()
    if not agent_config:
        raise ValueError("Primary agent not found")

    reviewer_configs: list[AgentConfig] = []
    for reviewer_name in payload.get("reviewer_names", []):
        reviewer_result = await db.execute(
            select(AgentConfig).where(AgentConfig.name == reviewer_name)
        )
        reviewer = reviewer_result.scalar_one_or_none()
        if reviewer:
            reviewer_configs.append(reviewer)

    approval_event = await create_agent_event(
        db,
        run,
        event_type="approval_resolved",
        agent_name=approval.agent_name,
        source_message=source_message,
        content=f"Approval granted for {approval.agent_name}",
        payload={
            "approval_id": approval.id,
            "requested_permission_mode": approval.requested_permission_mode,
        },
    )
    await _emit_event(approval_event, hooks)
    await _emit_run_update(run, hooks)
    await _emit_approval(approval, hooks)

    intent = CollaborationIntent(
        mode=str(payload.get("mode") or run.mode),
        review_targets=[str(item) for item in payload.get("reviewer_names", [])],
        wants_revision_loop=bool(payload.get("wants_revision_loop")),
        require_decision=bool(payload.get("require_decision", True)),
        required_permission_mode=payload.get("required_permission_mode"),
        task_kind=str(payload.get("task_kind", "deliverable")),
        primary_artifact_type=payload.get("primary_artifact_type"),
        decision_style=str(payload.get("decision_style", "readiness")),
        max_review_rounds=None,
        max_steps=None,
    )
    cycle_result = await _run_target_cycle(
        source_message,
        db,
        run=run,
        agent_config=agent_config,
        reviewer_configs=reviewer_configs,
        intent=intent,
        clean_content=str(payload.get("clean_content") or source_message.content),
        primary_prompt=str(payload.get("prompt") or source_message.content),
        hooks=hooks,
        chain_depth=int(payload.get("chain_depth") or 0),
        agent_chain=tuple(payload.get("agent_chain") or []),
        primary_phase=str(payload.get("primary_phase") or "plan"),
    )
    if not cycle_result.paused and run.status == RUN_STATUS_RUNNING:
        stop_run(run, RUN_STATUS_COMPLETED, "no_further_actions")
        completed_event = await create_agent_event(
            db,
            run,
            event_type="run_completed",
            source_message=source_message,
            content="Run completed with no further actions",
            payload={"stop_reason": run.stop_reason},
        )
        await _emit_run_update(run, hooks)
        await _emit_event(completed_event, hooks)

    await db.flush()
    return run


async def deny_approval_request(
    approval_id: str,
    db: AsyncSession,
    *,
    on_response: ResponseCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    hooks: RunHooks | None = None,
) -> ApprovalRequest:
    hooks = hooks or _build_hooks(
        on_response=on_response,
        on_run_update=on_run_update,
        on_event=on_event,
        on_approval=on_approval,
    )
    approval_result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = approval_result.scalar_one_or_none()
    if not approval:
        raise ValueError("Approval request not found")

    resolve_approval(approval, APPROVAL_STATUS_DENIED)
    run = await _get_collaboration_run(db, approval.run_id)
    if run:
        stop_run(run, RUN_STATUS_BLOCKED, "approval_denied")
        system_msg = await _persist_system_message(
            db,
            run.room_id,
            content=f"Approval denied for {approval.agent_name}. Run stopped.",
        )
        denied_event = await create_agent_event(
            db,
            run,
            event_type="approval_resolved",
            agent_name=approval.agent_name,
            content=f"Approval denied for {approval.agent_name}",
            payload={
                "approval_id": approval.id,
                "status": APPROVAL_STATUS_DENIED,
            },
        )
        await _emit_event(denied_event, hooks)
        await _emit_run_update(run, hooks)
        await hooks.emit_response(system_msg)
    await _emit_approval(approval, hooks)
    await db.flush()
    return approval
