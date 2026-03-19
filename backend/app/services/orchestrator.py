"""Message orchestrator — routes messages to the appropriate agents.

Rules:
  - @claude → send to Claude only
  - @codex  → send to Codex only
  - @all    → send to all enabled agents in parallel
  - No mention → broadcast to room, no agent auto-reply (human chat)
"""

import asyncio
import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.message import Message
from app.services.agent_memory_store import (
    build_agent_memory_context,
    get_or_create_agent_memory,
    sync_agent_memory_from_runtime,
)
from app.services.claude_agent import ClaudeAgent
from app.services.codex_agent import CodexAgent
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"@(\w+)")
LINE_HANDOFF_PATTERN = re.compile(r"(?m)^\s*@(\w+)\b")
LINE_HANDOFF_WITH_REQUEST_PATTERN = re.compile(r"^\s*@(\w+)\b(.*)$")
REVIEW_DIRECTIVE_PATTERN = re.compile(r"#review-by=([a-zA-Z0-9_, -]+)")
HANDOFF_DIRECTIVE_PATTERN = re.compile(r"#handoff=([a-zA-Z0-9_, -]+)")
REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_AGENT_CHAIN_DEPTH = 4
PLATFORM_AGENT_SYSTEM_PROMPT = """
You are one AI agent participating in a shared multi-agent room.

Rules for collaboration:
- Do not try to invoke other local CLIs, subprocesses, terminals, or tools to contact another agent.
- Do not ask the human for permission to run another agent on your behalf.
- If another agent should continue, emit a handoff instruction instead of trying to call it yourself.
- Preferred handoff format:
  #handoff=<agent-name>
  <the exact request for that agent>
- You may also use a single new line like:
  @codex review the plan above
- Normal inline mentions inside prose should be avoided unless you intend a handoff.
- Keep your own answer for the human separate from the handoff request for the next agent.
""".strip()

StatusCallback = Callable[[str, str], Awaitable[None]]
StreamCallback = Callable[[Message, str], Awaitable[None]]

AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
}


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
    """Prepend recent chat history so the agent can see prior conversation."""
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
    history.reverse()  # chronological order

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
        "Below is the conversation history from a shared chat room. "
        "Multiple users and AI agents participate. "
        "Read the history for context, then respond ONLY to the current request at the end.",
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
    lines.extend(
        [
        "--- CONVERSATION HISTORY ---",
        ]
    )
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
) -> tuple[AgentConfig, str]:
    """Call a single agent and return (config, response_text)."""
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
        permission_mode=agent_config.permission_mode,
        allowed_tools=agent_config.allowed_tools,
        system_prompt=effective_system_prompt,
    )

    if db and room_id:
        memory = await get_or_create_agent_memory(db, room_id, agent_config.name)
        session_manager.hydrate_session(
            agent_config.name,
            room_id,
            memory.provider_session_id,
            memory.message_count,
            memory.estimated_tokens,
        )
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

        if db and room_id:
            runtime_session = session_manager.get_session(agent_config.name, room_id)
            if runtime_session:
                await sync_agent_memory_from_runtime(
                    db,
                    room_id,
                    agent_config.name,
                    runtime_session.get("provider_session_id"),
                    runtime_session.get("message_count", 0),
                    runtime_session.get("estimated_tokens", 0),
                )

    except (TimeoutError, RuntimeError) as e:
        logger.error(f"Agent {agent_config.name} failed: {e}")
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
            )
        return await _call_agent(agent_config, prompt, db=db, room_id=room_id)
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
            "",
            git_context,
            "",
            f"Original user request:\n{original_request}",
            "",
            f"{primary_agent.display_name} response to review:\n{primary_response}",
            "",
            "Return a concise review with:",
            "1. Major risks",
            "2. Missing considerations",
            "3. Branch / workspace cautions",
            "4. Final recommendation",
        ]
    )


async def route_message(
    message: Message,
    db: AsyncSession,
    on_response=None,
    on_status: StatusCallback | None = None,
    on_stream: StreamCallback | None = None,
    chain_depth: int = 0,
    agent_chain: tuple[str, ...] = (),
) -> list[Message]:
    """Route an incoming message to the appropriate agents.

    Args:
        message: The incoming message (already saved to DB).
        db: Database session.
        on_response: Optional async callback(Message) called as each agent responds
                     (for real-time broadcast before all agents finish).
        on_status: Optional async callback(agent_name, status) for status updates.
        on_stream: Optional async callback(Message, content) for progressive chunks.
        chain_depth: Current recursive depth for agent-to-agent chaining.
        agent_chain: Ordered names of agents already invoked in this route chain.
    """
    if chain_depth > MAX_AGENT_CHAIN_DEPTH:
        logger.warning("Agent chain depth exceeded for room %s", message.room_id)
        return []

    if message.sender_type == "human":
        mentions = extract_mentions(message.content)
        clean_content = strip_control_syntax(message.content)
    else:
        mentions = extract_agent_handoff_targets(message.content)
        clean_content = extract_agent_handoff_request(message.content)
    review_targets = extract_review_targets(message.content)

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

    reviewer_configs: list[AgentConfig] = []
    seen_reviewers: set[str] = set()
    primary_names = {target.name.lower() for target in targets}
    for reviewer_name in review_targets:
        if reviewer_name in agent_map and reviewer_name not in primary_names and reviewer_name not in seen_reviewers:
            reviewer_configs.append(agent_map[reviewer_name])
            seen_reviewers.add(reviewer_name)

    prompt_request = clean_content
    if message.sender_type == "human":
        prompt_request = (
            clean_content
            + _build_human_collaboration_hint(
                message.content,
                enabled_agents,
                targets,
                review_targets,
            )
        )

    # Build prompt with chat history so agent can see prior conversation
    prompt_by_agent: dict[str, str] = {}
    for target in targets:
        prompt_by_agent[target.name.lower()] = await _build_prompt_with_history(
            db,
            message.room_id,
            target.name,
            prompt_request,
            message.id,
            include_current_message_in_history=message.sender_type != "human",
        )

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
            )
        except Exception as e:
            logger.error("Agent call failed for %s: %s", cfg.name, e)
            agent_config = cfg
            response_text = f"Agent error: {e}"
        return transient_message, agent_config, response_text

    tasks = [
        asyncio.create_task(run_target(cfg, _build_transient_agent_message(message.room_id, cfg)))
        for cfg in targets
    ]
    for task in asyncio.as_completed(tasks):
        transient_message, agent_config, response_text = await task

        agent_message = Message(
            id=transient_message.id,
            room_id=message.room_id,
            sender_type=agent_config.agent_type,
            sender_name=agent_config.display_name,
            content=response_text,
            created_at=transient_message.created_at,
        )
        db.add(agent_message)
        await db.flush()
        responses.append(agent_message)

        # Stream each response to clients as it arrives
        if on_response:
            await on_response(agent_message)

        for reviewer_config in reviewer_configs:
            review_prompt = await _build_review_prompt(
                clean_content,
                agent_config,
                response_text,
            )
            review_transient_message = _build_transient_agent_message(
                message.room_id,
                reviewer_config,
            )
            try:
                _, review_text = await _run_agent_call(
                    db,
                    message.room_id,
                    reviewer_config,
                    review_prompt,
                    on_status,
                    stream_message=review_transient_message,
                    on_stream=on_stream,
                )
            except Exception as e:
                logger.error(
                    "Review agent %s failed after %s response: %s",
                    reviewer_config.name,
                    agent_config.name,
                    e,
                )
                review_message = Message(
                    id=review_transient_message.id,
                    room_id=review_transient_message.room_id,
                    sender_type=review_transient_message.sender_type,
                    sender_name=review_transient_message.sender_name,
                    content=f"Agent error: {e}",
                    created_at=review_transient_message.created_at,
                )
                db.add(review_message)
                await db.flush()
                responses.append(review_message)
                if on_response:
                    await on_response(review_message)
                continue

            review_message = Message(
                id=review_transient_message.id,
                room_id=message.room_id,
                sender_type=reviewer_config.agent_type,
                sender_name=reviewer_config.display_name,
                content=review_text,
                created_at=review_transient_message.created_at,
            )
            db.add(review_message)
            await db.flush()
            responses.append(review_message)

            if on_response:
                await on_response(review_message)

        chained_agents = (
            *agent_chain,
            agent_config.name.lower(),
            *(reviewer.name.lower() for reviewer in reviewer_configs),
        )
        chained_responses = await route_message(
            agent_message,
            db,
            on_response=on_response,
            on_status=on_status,
            on_stream=on_stream,
            chain_depth=chain_depth + 1,
            agent_chain=chained_agents,
        )
        responses.extend(chained_responses)

    return responses
