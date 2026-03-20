"""Message orchestrator for native agent collaboration runs."""

import asyncio
from dataclasses import dataclass
import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.agent_artifact import AgentArtifact
from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.run_step import RunStep
from app.services.agent_memory_store import (
    build_agent_memory_context,
    get_or_create_agent_memory,
    sync_agent_memory_from_runtime,
)
from app.services.artifact_extractor import ExtractedArtifact, extract_artifact
from app.services.claude_agent import ClaudeAgent
from app.services.collaboration_policy import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_COMPLETED,
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
    PermissionEscalationRequired,
    create_agent_event,
    create_approval_request,
    create_run_step,
    get_run_permission_override,
    is_permission_error,
    loads_payload,
    next_permission_mode,
    permission_rank,
    pick_higher_permission,
    resolve_approval,
    update_run_step,
)
from app.services.codex_agent import CodexAgent
from app.services.run_intent import CollaborationIntent, build_collaboration_intent
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"@(\w+)")
LINE_HANDOFF_PATTERN = re.compile(r"(?m)^\s*@(\w+)\b")
LINE_HANDOFF_WITH_REQUEST_PATTERN = re.compile(r"^\s*@(\w+)\b(.*)$")
REVIEW_DIRECTIVE_PATTERN = re.compile(r"#review-by=([a-zA-Z0-9_, -]+)")
HANDOFF_DIRECTIVE_PATTERN = re.compile(r"#handoff=([a-zA-Z0-9_, -]+)")
REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_AGENT_CHAIN_DEPTH = 4
REVIEW_REVISE_STATUSES = {"revise", "changes_requested"}
REVIEW_BLOCKED_STATUSES = {"blocked"}
PLATFORM_AGENT_SYSTEM_PROMPT = """
You are one AI agent participating in a shared multi-agent room.

Rules for collaboration:
- Do not try to invoke other local CLIs, subprocesses, terminals, or tools to contact another agent.
- Do not ask the human for permission to run another agent on your behalf.
- If another agent should continue, emit a handoff instruction instead of trying to call it yourself.
- Preferred handoff format:
  #handoff=<agent-name>
  <the exact request for that agent>
- When your output is intended to be reused by another agent, prefer adding:
  #artifact=plan|review|decision|todo|summary
- Review outputs should also include:
  #status=approved|revise|blocked
- Final decision outputs should also include:
  #status=completed|blocked|revise
- You may also use a single new line like:
  @codex review the plan above
- Normal inline mentions inside prose should be avoided unless you intend a handoff.
- Keep your own answer for the human separate from the handoff request for the next agent.
""".strip()

StatusCallback = Callable[[str, str], Awaitable[None]]
StreamCallback = Callable[[Message, str], Awaitable[None]]
RunCallback = Callable[[CollaborationRun], Awaitable[None]]
ArtifactCallback = Callable[[AgentArtifact], Awaitable[None]]
StepCallback = Callable[[RunStep], Awaitable[None]]
EventCallback = Callable[[AgentEvent], Awaitable[None]]
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[None]]

AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
}


@dataclass(slots=True)
class AgentStepResult:
    message: Message | None
    raw_content: str | None
    extracted: ExtractedArtifact | None
    step: RunStep
    paused: bool = False
    approval: ApprovalRequest | None = None


@dataclass(slots=True)
class CycleResult:
    responses: list[Message]
    paused: bool = False


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

    run = CollaborationRun(
        room_id=message.room_id,
        root_message_id=message.id,
        initiator_type=message.sender_type,
        mode=intent.mode,
        status=RUN_STATUS_RUNNING,
    )
    db.add(run)
    await db.flush()
    return run


async def _hydrate_runtime_from_memory(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
) -> None:
    memory = await get_or_create_agent_memory(db, room_id, agent_name)
    session_manager.hydrate_session(
        agent_name,
        room_id,
        memory.provider_session_id,
        memory.message_count,
        memory.estimated_tokens,
    )


async def _sync_runtime_to_memory(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
) -> None:
    runtime_session = session_manager.get_session(agent_name, room_id)
    if not runtime_session:
        return
    await sync_agent_memory_from_runtime(
        db,
        room_id,
        agent_name,
        runtime_session.get("provider_session_id"),
        runtime_session.get("message_count", 0),
        runtime_session.get("estimated_tokens", 0),
    )


async def _create_agent_artifact(
    db: AsyncSession,
    run: CollaborationRun,
    message: Message,
    agent_name: str,
    extracted: ExtractedArtifact,
    on_artifact: ArtifactCallback | None = None,
) -> AgentArtifact | None:
    if not extracted.artifact_type or not extracted.clean_content:
        return None

    artifact = AgentArtifact(
        run_id=run.id,
        room_id=message.room_id,
        source_message_id=message.id,
        agent_name=agent_name,
        artifact_type=extracted.artifact_type,
        title=extracted.title,
        content=extracted.clean_content,
        status=extracted.status,
    )
    db.add(artifact)
    await db.flush()
    if on_artifact:
        await on_artifact(artifact)
    return artifact


async def _emit_run_update(
    run: CollaborationRun | None,
    on_run_update: RunCallback | None,
) -> None:
    if run and on_run_update:
        await on_run_update(run)


async def _emit_step_update(
    step: RunStep | None,
    on_step: StepCallback | None,
) -> None:
    if step and on_step:
        await on_step(step)


async def _emit_event(
    event: AgentEvent | None,
    on_event: EventCallback | None,
) -> None:
    if event and on_event:
        await on_event(event)


async def _emit_approval(
    approval: ApprovalRequest | None,
    on_approval: ApprovalCallback | None,
) -> None:
    if approval and on_approval:
        await on_approval(approval)


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


def extract_mentions(content: str) -> list[str]:
    return [m.lower() for m in MENTION_PATTERN.findall(content)]


def _extract_directive_targets(content: str, pattern: re.Pattern[str]) -> list[str]:
    match = pattern.search(content)
    if not match:
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for raw_target in match.group(1).split(","):
        target = raw_target.strip().lower()
        if target and target not in seen:
            targets.append(target)
            seen.add(target)
    return targets


def extract_agent_handoff_targets(content: str) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    for target in LINE_HANDOFF_PATTERN.findall(content):
        lowered = target.lower()
        if lowered not in seen:
            targets.append(lowered)
            seen.add(lowered)

    for target in _extract_directive_targets(content, HANDOFF_DIRECTIVE_PATTERN):
        if target not in seen:
            targets.append(target)
            seen.add(target)

    return targets


def extract_agent_handoff_request(content: str) -> str:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        handoff_match = LINE_HANDOFF_WITH_REQUEST_PATTERN.match(line)
        if handoff_match:
            inline_request = handoff_match.group(2).strip()
            if inline_request:
                return inline_request

            trailing_request = "\n".join(lines[index + 1 :]).strip()
            if trailing_request:
                return trailing_request
            break

        directive_match = HANDOFF_DIRECTIVE_PATTERN.fullmatch(line.strip())
        if directive_match:
            trailing_request = "\n".join(lines[index + 1 :]).strip()
            if trailing_request:
                return trailing_request
            break

    return re.sub(r"[ \t]{2,}", " ", strip_control_syntax(content)).strip()


def extract_referenced_agent_names(
    content: str,
    enabled_agents: list[AgentConfig],
) -> list[str]:
    lowered = content.lower()
    referenced: list[str] = []
    seen: set[str] = set()

    for agent in enabled_agents:
        name = agent.name.lower()
        display_name = agent.display_name.lower()
        if (
            name in lowered
            or display_name in lowered
            or f"@{name}" in lowered
        ) and name not in seen:
            referenced.append(name)
            seen.add(name)

    return referenced


def _build_human_collaboration_hint(
    message_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
    review_targets: list[str],
) -> str:
    if len(primary_targets) != 1:
        return ""

    referenced_agents = extract_referenced_agent_names(message_content, enabled_agents)
    primary_names = {target.name.lower() for target in primary_targets}
    collaborator_names = [
        name
        for name in referenced_agents
        if name not in primary_names and name not in review_targets
    ]
    if not collaborator_names:
        return ""

    collaborator_list = ", ".join(collaborator_names)
    preferred_target = collaborator_names[0]
    return "\n".join(
        [
            "",
            "Platform instruction:",
            (
                "The user also referenced these agents for possible follow-up: "
                f"{collaborator_list}."
            ),
            (
                "If you want one of them to continue, do not claim you need permission "
                "and do not try to run their CLI yourself."
            ),
            (
                f"Instead, end your reply with an explicit handoff such as "
                f"`#handoff={preferred_target}` followed by the exact request for that agent."
            ),
        ]
    )


def strip_mentions(content: str) -> str:
    return MENTION_PATTERN.sub("", content).strip()


def extract_review_targets(content: str) -> list[str]:
    return _extract_directive_targets(content, REVIEW_DIRECTIVE_PATTERN)


def strip_review_directives(content: str) -> str:
    return REVIEW_DIRECTIVE_PATTERN.sub("", content).strip()


def strip_handoff_directives(content: str) -> str:
    return HANDOFF_DIRECTIVE_PATTERN.sub("", content).strip()


def strip_control_syntax(content: str) -> str:
    return strip_mentions(
        strip_handoff_directives(strip_review_directives(content))
    ).strip()


async def get_enabled_agents(db: AsyncSession) -> list[AgentConfig]:
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.enabled.is_(True))
    )
    return list(result.scalars().all())


async def _build_prompt_with_history(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
    current_content: str,
    current_message_id: str,
    include_current_message_in_history: bool = False,
    max_messages: int = 20,
) -> str:
    stmt = (
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    if not include_current_message_in_history:
        stmt = stmt.where(Message.id != current_message_id)
    result = await db.execute(stmt)
    history = list(result.scalars().all())
    history.reverse()

    if not history:
        memory_context = await build_agent_memory_context(
            db,
            room_id,
            agent_name,
            max_messages,
        )
        if not memory_context:
            return current_content
        return "\n".join(
            [
                "Below is the persistent long-term memory for this room.",
                "",
                memory_context,
                "",
                f"Now respond to this request: {current_content}",
            ]
        )

    memory_context = await build_agent_memory_context(
        db,
        room_id,
        agent_name,
        max_messages,
    )

    lines = [
        "Below is the conversation history from a shared chat room. Multiple users and AI agents participate. Read the history for context, then respond ONLY to the current request at the end.",
        "",
    ]
    if memory_context:
        lines.extend(
            [
                "--- LONG-TERM MEMORY ---",
                memory_context,
                "--- END LONG-TERM MEMORY ---",
                "",
            ]
        )
    lines.append("--- CONVERSATION HISTORY ---")
    for msg in history:
        lines.append(f"[{msg.sender_name}]: {msg.content}")
    lines.append("--- END HISTORY ---")
    lines.append("")
    lines.append(f"Now respond to this request: {current_content}")

    return "\n".join(lines)


async def _call_agent(
    agent_config: AgentConfig,
    prompt: str,
    on_stream: Callable[[str], Awaitable[None]] | None = None,
    *,
    db: AsyncSession | None = None,
    room_id: str | None = None,
    manage_room_memory: bool = True,
    override_permission_mode: str | None = None,
) -> tuple[AgentConfig, str]:
    agent_class = AGENT_CLASSES.get(agent_config.agent_type)
    if not agent_class:
        return agent_config, f"No wrapper for agent type: {agent_config.agent_type}"

    effective_system_prompt = PLATFORM_AGENT_SYSTEM_PROMPT
    if agent_config.system_prompt:
        effective_system_prompt = (
            f"{agent_config.system_prompt.strip()}\n\n{PLATFORM_AGENT_SYSTEM_PROMPT}"
        )

    agent = agent_class(
        command=agent_config.command,
        timeout=agent_config.max_timeout,
        model=agent_config.model,
        permission_mode=override_permission_mode or agent_config.permission_mode,
        allowed_tools=agent_config.allowed_tools,
        system_prompt=effective_system_prompt,
        default_args=agent_config.default_args,
    )

    if room_id and db and manage_room_memory:
        await _hydrate_runtime_from_memory(db, room_id, agent_config.name)

    if room_id:
        provider_session_id = session_manager.get_provider_session_id(
            agent_config.name,
            room_id,
        )
        session_manager.start_run(agent_config.name, room_id)
    else:
        session_manager.get_or_create_session(agent_config.name)
        provider_session_id = session_manager.get_provider_session_id(agent_config.name)
        session_manager.start_run(agent_config.name)

    try:
        if on_stream:
            response_text = await agent.send_with_stream(
                prompt,
                on_stream,
                session_id=provider_session_id,
            )
        else:
            response_text = await agent.send(prompt, session_id=provider_session_id)
        if agent.last_session_id:
            if room_id:
                session_manager.set_provider_session_id(
                    agent_config.name,
                    agent.last_session_id,
                    room_id,
                )
            else:
                session_manager.set_provider_session_id(
                    agent_config.name,
                    agent.last_session_id,
                )
        if room_id:
            session_manager.increment_messages(agent_config.name, room_id=room_id)
        else:
            session_manager.increment_messages(agent_config.name)

        if room_id:
            if session_manager.should_rotate(agent_config.name, room_id):
                session_manager.rotate_session(agent_config.name, room_id)
        elif session_manager.should_rotate(agent_config.name):
            session_manager.rotate_session(agent_config.name)

        if room_id and db and manage_room_memory:
            await _sync_runtime_to_memory(db, room_id, agent_config.name)

    except (TimeoutError, RuntimeError) as e:
        error_text = str(e)
        if is_permission_error(error_text):
            raise PermissionEscalationRequired(
                agent_name=agent_config.name,
                requested_permission_mode=next_permission_mode(
                    override_permission_mode or agent_config.permission_mode,
                    error_text,
                ),
                reason=(
                    f"{agent_config.display_name} needs more permission to continue "
                    f"this step."
                ),
                error_text=error_text,
            )
        logger.error("Agent %s failed: %s", agent_config.name, e)
        response_text = f"Agent error: {e}"
    finally:
        if room_id:
            session_manager.finish_run(agent_config.name, room_id)
        else:
            session_manager.finish_run(agent_config.name)

    return agent_config, response_text


async def _run_agent_call(
    db: AsyncSession,
    room_id: str,
    agent_config: AgentConfig,
    prompt: str,
    on_status: StatusCallback | None = None,
    stream_message: Message | None = None,
    on_stream: StreamCallback | None = None,
    *,
    manage_room_memory: bool = True,
    override_permission_mode: str | None = None,
) -> tuple[AgentConfig, str]:
    if on_status:
        await on_status(agent_config.name, "working")

    async def handle_stream(content: str) -> None:
        if on_stream and stream_message:
            await on_stream(stream_message, content)

    try:
        if on_stream and stream_message:
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
        if on_status:
            await on_status(agent_config.name, "idle")


def _build_transient_agent_message(
    room_id: str,
    agent_config: AgentConfig,
) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        room_id=room_id,
        sender_type=agent_config.agent_type,
        sender_name=agent_config.display_name,
        content="",
        created_at=datetime.now(timezone.utc),
    )


def _get_git_context() -> str:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() or "(detached HEAD)"
    except Exception:
        return "Git branch information unavailable."

    try:
        status_output = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        status_output = ""

    lines = [f"Current git branch: {branch}."]
    if status_output:
        changed = status_output.splitlines()[:10]
        lines.append("Working tree status:")
        lines.extend(changed)
        if len(status_output.splitlines()) > len(changed):
            lines.append("...")
    else:
        lines.append("Working tree status: clean.")

    return "\n".join(lines)


async def _build_review_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    primary_response: str,
) -> str:
    git_context = await asyncio.to_thread(_get_git_context)
    return "\n".join(
        [
            "You are reviewing another AI agent's proposed plan or output.",
            "Focus on risks, missing steps, branch-related concerns, and concrete corrections.",
            "Do not rewrite everything from scratch unless the original plan is fundamentally broken.",
            "Return your review using this protocol:",
            "#artifact=review",
            "#status=approved|revise|blocked",
            "",
            git_context,
            "",
            f"Original user request:\n{original_request}",
            "",
            f"{primary_agent.display_name} plan or output to review:\n{primary_response}",
            "",
            "Return a concise review with:",
            "1. Major risks",
            "2. Missing considerations",
            "3. Branch / workspace cautions",
            "4. Final recommendation",
        ]
    )


async def _build_decision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    plan_text: str,
    review_texts: list[str],
) -> str:
    review_block = "\n\n".join(
        f"Review {index + 1}:\n{text}" for index, text in enumerate(review_texts)
    )
    return "\n".join(
        [
            "You are making the final decision for a multi-agent collaboration run.",
            "Read your original plan and the review feedback, then decide whether the work is ready.",
            "Return your result using this protocol:",
            "#artifact=decision",
            "#status=completed|blocked|revise",
            "",
            f"Original user request:\n{original_request}",
            "",
            f"Your original plan:\n{plan_text}",
            "",
            f"Review feedback:\n{review_block}",
            "",
            "Return a concise final decision with:",
            "1. Decision",
            "2. Reasoning",
            "3. Next action",
        ]
    )


async def _build_revision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    previous_output: str,
    review_texts: list[str],
) -> str:
    review_block = "\n\n".join(
        f"Review {index + 1}:\n{text}" for index, text in enumerate(review_texts)
    )
    return "\n".join(
        [
            f"You are {primary_agent.display_name}. Revise your previous output using the review feedback.",
            "Keep the strongest parts of the current solution and change only what the review requires.",
            "Return the revised output using this protocol:",
            "#artifact=plan",
            "",
            f"Original user request:\n{original_request}",
            "",
            f"Previous output:\n{previous_output}",
            "",
            f"Review feedback:\n{review_block}",
            "",
            "Return a revised, reusable result that directly addresses the review comments.",
        ]
    )


async def _persist_agent_response(
    db: AsyncSession,
    room_id: str,
    transient_message: Message,
    agent_config: AgentConfig,
    raw_content: str,
    extracted: ExtractedArtifact,
) -> Message:
    agent_message = Message(
        id=transient_message.id,
        room_id=room_id,
        sender_type=agent_config.agent_type,
        sender_name=agent_config.display_name,
        content=extracted.clean_content,
        created_at=transient_message.created_at,
    )
    db.add(agent_message)
    await db.flush()
    return agent_message


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
    on_run_update: RunCallback | None,
    on_step: StepCallback | None,
    on_event: EventCallback | None,
    on_approval: ApprovalCallback | None,
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
    await _emit_step_update(step, on_step)
    await _emit_approval(approval, on_approval)
    await _emit_event(event, on_event)
    await _emit_run_update(run, on_run_update)
    return approval


async def _execute_agent_step(
    db: AsyncSession,
    run: CollaborationRun,
    *,
    source_message: Message,
    agent_config: AgentConfig,
    prompt: str,
    step_type: str,
    step_title: str,
    on_response=None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    default_artifact_type: str | None = None,
    default_status: str | None = None,
    count_as_review: bool = False,
    required_permission_mode: str | None = None,
    allow_approval: bool = False,
    emit_run_update: bool = True,
    resume_kind: str | None = None,
    resume_payload: dict[str, Any] | None = None,
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
    await _emit_step_update(step, on_step)
    await _emit_event(started_event, on_event)

    effective_permission_mode = await _resolve_effective_permission_mode(
        db,
        run,
        agent_config,
    )
    if (
        allow_approval
        and required_permission_mode
        and permission_rank(required_permission_mode) > permission_rank(effective_permission_mode)
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
            on_run_update=on_run_update,
            on_step=on_step,
            on_event=on_event,
            on_approval=on_approval,
        )
        return AgentStepResult(
            message=None,
            raw_content=None,
            extracted=None,
            step=step,
            paused=True,
            approval=approval,
        )

    transient_message = _build_transient_agent_message(run.room_id, agent_config)
    try:
        _, response_text = await _run_agent_call(
            db,
            run.room_id,
            agent_config,
            prompt,
            on_status,
            stream_message=transient_message,
            on_stream=on_stream,
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
                on_run_update=on_run_update,
                on_step=on_step,
                on_event=on_event,
                on_approval=on_approval,
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
        response_text = f"Agent error: {exc.error_text}"

    extracted = extract_artifact(
        response_text,
        default_artifact_type=default_artifact_type,
        default_status=default_status,
    )
    agent_message = await _persist_agent_response(
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
    await _sync_runtime_to_memory(db, run.room_id, agent_config.name)
    artifact = await _create_agent_artifact(
        db,
        run,
        agent_message,
        agent_config.name,
        extracted,
        on_artifact=on_artifact,
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
        await _emit_run_update(run, on_run_update)
    await _emit_step_update(step, on_step)
    await _emit_event(completed_event, on_event)
    if on_response:
        await on_response(agent_message)
    return AgentStepResult(
        message=agent_message,
        raw_content=response_text,
        extracted=extracted,
        step=step,
    )


async def _run_parallel_targets(
    message: Message,
    db: AsyncSession,
    *,
    run: CollaborationRun,
    targets: list[AgentConfig],
    prompt_by_agent: dict[str, str],
    on_response=None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    chain_depth: int,
    agent_chain: tuple[str, ...],
) -> list[Message]:
    responses: list[Message] = []

    async def run_target(
        cfg: AgentConfig,
        transient_message: Message,
    ) -> tuple[Message, AgentConfig, str]:
        try:
            agent_config, response_text = await _run_agent_call(
                db,
                message.room_id,
                cfg,
                prompt_by_agent[cfg.name.lower()],
                on_status,
                stream_message=transient_message,
                on_stream=on_stream,
                manage_room_memory=False,
            )
        except Exception as e:
            logger.error("Agent call failed for %s: %s", cfg.name, e)
            agent_config = cfg
            response_text = f"Agent error: {e}"
        return transient_message, agent_config, response_text

    tasks = [
        asyncio.create_task(
            run_target(cfg, _build_transient_agent_message(message.room_id, cfg))
        )
        for cfg in targets
    ]

    for task in asyncio.as_completed(tasks):
        transient_message, agent_config, response_text = await task
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
            on_artifact=on_artifact,
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
        await _emit_run_update(run, on_run_update)
        await _emit_step_update(step, on_step)
        await _emit_event(event, on_event)
        responses.append(agent_message)
        if on_response:
            await on_response(agent_message)

        if run.status == RUN_STATUS_RUNNING:
            chained_responses = await route_message(
                agent_message,
                db,
                on_response=on_response,
                on_status=on_status,
                on_stream=on_stream,
                on_run_update=on_run_update,
                on_artifact=on_artifact,
                on_step=on_step,
                on_event=on_event,
                on_approval=on_approval,
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
    on_response=None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
    chain_depth: int = 0,
    agent_chain: tuple[str, ...] = (),
    primary_phase: str = "plan",
) -> CycleResult:
    responses: list[Message] = []
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
        on_response=on_response,
        on_status=on_status,
        on_stream=on_stream,
        on_run_update=on_run_update,
        on_artifact=on_artifact,
        on_step=on_step,
        on_event=on_event,
        on_approval=on_approval,
        default_artifact_type="plan" if reviewer_configs else None,
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
    )
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
                await _emit_run_update(run, on_run_update)
                break

            review_texts: list[str] = []
            review_statuses: set[str] = set()
            for reviewer_config in reviewer_configs:
                review_prompt = await _build_review_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                )
                review_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=current_primary.message,
                    agent_config=reviewer_config,
                    prompt=review_prompt,
                    step_type="review",
                    step_title=f"{reviewer_config.display_name} reviewing the latest output",
                    on_response=on_response,
                    on_status=on_status,
                    on_stream=on_stream,
                    on_run_update=on_run_update,
                    on_artifact=on_artifact,
                    on_step=on_step,
                    on_event=on_event,
                    on_approval=on_approval,
                    default_artifact_type="review",
                    count_as_review=True,
                    allow_approval=False,
                )
                if review_result.paused or not review_result.message or not review_result.extracted:
                    return CycleResult(responses=responses, paused=True)
                responses.append(review_result.message)
                review_texts.append(review_result.extracted.clean_content)
                if review_result.extracted.status:
                    review_statuses.add(review_result.extracted.status)

            if review_statuses & REVIEW_BLOCKED_STATUSES:
                stop_run(run, RUN_STATUS_BLOCKED, "review_blocked")
                await _emit_run_update(run, on_run_update)
                break

            if intent.wants_revision_loop and review_statuses & REVIEW_REVISE_STATUSES:
                limit_reason = should_stop_for_limits(run)
                if limit_reason:
                    stop_run(run, RUN_STATUS_STOPPED, limit_reason)
                    await _emit_run_update(run, on_run_update)
                    break

                revision_prompt = await _build_revision_prompt(
                    clean_content,
                    agent_config,
                    current_primary.extracted.clean_content,
                    review_texts,
                )
                revision_result = await _execute_agent_step(
                    db,
                    run,
                    source_message=follow_up_message,
                    agent_config=agent_config,
                    prompt=revision_prompt,
                    step_type="revision",
                    step_title=f"{agent_config.display_name} revising after review",
                    on_response=on_response,
                    on_status=on_status,
                    on_stream=on_stream,
                    on_run_update=on_run_update,
                    on_artifact=on_artifact,
                    on_step=on_step,
                    on_event=on_event,
                    on_approval=on_approval,
                    default_artifact_type="plan",
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
                )
                if (
                    revision_result.paused
                    or not revision_result.message
                    or not revision_result.extracted
                ):
                    return CycleResult(responses=responses, paused=True)
                responses.append(revision_result.message)
                current_primary = revision_result
                follow_up_message = revision_result.message
                follow_up_raw_content = (
                    revision_result.raw_content or revision_result.message.content
                )
                continue

            if intent.require_decision and run.status == RUN_STATUS_RUNNING:
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
                    on_response=on_response,
                    on_status=on_status,
                    on_stream=on_stream,
                    on_run_update=on_run_update,
                    on_artifact=on_artifact,
                    on_step=on_step,
                    on_event=on_event,
                    on_approval=on_approval,
                    default_artifact_type="decision",
                    allow_approval=False,
                    emit_run_update=False,
                )
                if (
                    decision_result.paused
                    or not decision_result.message
                    or not decision_result.extracted
                ):
                    return CycleResult(responses=responses, paused=True)
                responses.append(decision_result.message)
                finalize_run_from_artifact(
                    run,
                    decision_result.extracted.artifact_type,
                    decision_result.extracted.status,
                )
                await _emit_run_update(run, on_run_update)
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
            on_response=on_response,
            on_status=on_status,
            on_stream=on_stream,
            on_run_update=on_run_update,
            on_artifact=on_artifact,
            on_step=on_step,
            on_event=on_event,
            on_approval=on_approval,
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
    on_response=None,
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
) -> list[Message]:
    raw_content = raw_content_override or message.content

    run = await _get_collaboration_run(db, run_id)
    if chain_depth > MAX_AGENT_CHAIN_DEPTH:
        logger.warning("Agent chain depth exceeded for room %s", message.room_id)
        if run and run.status == RUN_STATUS_RUNNING:
            stop_run(run, RUN_STATUS_STOPPED, "max_agent_chain_depth_exceeded")
            await db.flush()
            await _emit_run_update(run, on_run_update)
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
        )
    reviewer_configs: list[AgentConfig] = []
    seen_reviewers: set[str] = set()
    primary_names = {target.name.lower() for target in targets}
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
        await _emit_run_update(run, on_run_update)
        await _emit_event(started_event, on_event)

    if run.status != RUN_STATUS_RUNNING:
        return []

    limit_reason = should_stop_for_limits(run)
    if limit_reason:
        stop_run(run, RUN_STATUS_STOPPED, limit_reason)
        await db.flush()
        await _emit_run_update(run, on_run_update)
        return []

    prompt_request = clean_content
    if message.sender_type == "human":
        prompt_request = (
            clean_content
            + _build_human_collaboration_hint(
                raw_content,
                enabled_agents,
                targets,
                intent.review_targets,
            )
        )
        if reviewer_configs and len(targets) == 1:
            prompt_request = "\n".join(
                [
                    prompt_request,
                    "",
                    "Collaboration protocol:",
                    "Return a reusable plan and begin with `#artifact=plan`.",
                ]
            )

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
            on_response=on_response,
            on_status=on_status,
            on_stream=on_stream,
            on_run_update=on_run_update,
            on_artifact=on_artifact,
            on_step=on_step,
            on_event=on_event,
            on_approval=on_approval,
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
            on_response=on_response,
            on_status=on_status,
            on_stream=on_stream,
            on_run_update=on_run_update,
            on_artifact=on_artifact,
            on_step=on_step,
            on_event=on_event,
            on_approval=on_approval,
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
        await _emit_run_update(run, on_run_update)
        await _emit_event(completed_event, on_event)

    await db.flush()
    return responses


async def resume_approval_request(
    approval_id: str,
    db: AsyncSession,
    *,
    on_response=None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    on_run_update: RunCallback | None = None,
    on_artifact: ArtifactCallback | None = None,
    on_step: StepCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
) -> CollaborationRun:
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
    await _emit_event(approval_event, on_event)
    await _emit_run_update(run, on_run_update)
    await _emit_approval(approval, on_approval)

    intent = CollaborationIntent(
        mode=str(payload.get("mode") or run.mode),
        review_targets=[str(item) for item in payload.get("reviewer_names", [])],
        wants_revision_loop=bool(payload.get("wants_revision_loop")),
        require_decision=bool(payload.get("require_decision", True)),
        required_permission_mode=payload.get("required_permission_mode"),
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
        on_response=on_response,
        on_status=on_status,
        on_stream=on_stream,
        on_run_update=on_run_update,
        on_artifact=on_artifact,
        on_step=on_step,
        on_event=on_event,
        on_approval=on_approval,
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
        await _emit_run_update(run, on_run_update)
        await _emit_event(completed_event, on_event)

    await db.flush()
    return run


async def deny_approval_request(
    approval_id: str,
    db: AsyncSession,
    *,
    on_run_update: RunCallback | None = None,
    on_event: EventCallback | None = None,
    on_approval: ApprovalCallback | None = None,
) -> ApprovalRequest:
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
        await _emit_event(denied_event, on_event)
        await _emit_run_update(run, on_run_update)
    await _emit_approval(approval, on_approval)
    await db.flush()
    return approval
