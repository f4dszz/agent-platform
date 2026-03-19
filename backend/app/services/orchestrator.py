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
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.message import Message
from app.services.claude_agent import ClaudeAgent
from app.services.codex_agent import CodexAgent
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"@(\w+)")
REVIEW_DIRECTIVE_PATTERN = re.compile(r"#review-by=([a-zA-Z0-9_, -]+)")
REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_AGENT_CHAIN_DEPTH = 4

StatusCallback = Callable[[str, str], Awaitable[None]]

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


def strip_mentions(content: str) -> str:
    return MENTION_PATTERN.sub("", content).strip()


def extract_review_targets(content: str) -> list[str]:
    match = REVIEW_DIRECTIVE_PATTERN.search(content)
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


def strip_review_directives(content: str) -> str:
    return REVIEW_DIRECTIVE_PATTERN.sub("", content).strip()


def strip_control_syntax(content: str) -> str:
    return strip_mentions(strip_review_directives(content)).strip()


async def get_enabled_agents(db: AsyncSession) -> list[AgentConfig]:
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.enabled.is_(True))
    )
    return list(result.scalars().all())


async def _build_prompt_with_history(
    db: AsyncSession,
    room_id: str,
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
        return current_content

    lines = [
        "Below is the conversation history from a shared chat room. "
        "Multiple users and AI agents participate. "
        "Read the history for context, then respond ONLY to the current request at the end.",
        "",
        "--- CONVERSATION HISTORY ---",
    ]
    for msg in history:
        lines.append(f"[{msg.sender_name}]: {msg.content}")
    lines.append("--- END HISTORY ---")
    lines.append("")
    lines.append(f"Now respond to this request: {current_content}")

    return "\n".join(lines)


async def _call_agent(
    agent_config: AgentConfig, prompt: str
) -> tuple[AgentConfig, str]:
    """Call a single agent and return (config, response_text)."""
    agent_class = AGENT_CLASSES.get(agent_config.agent_type)
    if not agent_class:
        return agent_config, f"No wrapper for agent type: {agent_config.agent_type}"

    agent = agent_class(
        command=agent_config.command,
        timeout=agent_config.max_timeout,
        permission_mode=agent_config.permission_mode,
        allowed_tools=agent_config.allowed_tools,
        system_prompt=agent_config.system_prompt,
    )

    session_manager.get_or_create_session(agent_config.name)
    provider_session_id = session_manager.get_provider_session_id(agent_config.name)
    session_manager.start_run(agent_config.name)

    try:
        response_text = await agent.send(prompt, session_id=provider_session_id)
        if agent.last_session_id:
            session_manager.set_provider_session_id(
                agent_config.name, agent.last_session_id
            )
        session_manager.increment_messages(agent_config.name)

        if session_manager.should_rotate(agent_config.name):
            session_manager.rotate_session(agent_config.name)

    except (TimeoutError, RuntimeError) as e:
        logger.error(f"Agent {agent_config.name} failed: {e}")
        response_text = f"Agent error: {e}"
    finally:
        session_manager.finish_run(agent_config.name)

    return agent_config, response_text


async def _run_agent_call(
    agent_config: AgentConfig,
    prompt: str,
    on_status: StatusCallback | None = None,
) -> tuple[AgentConfig, str]:
    if on_status:
        await on_status(agent_config.name, "working")
    try:
        return await _call_agent(agent_config, prompt)
    finally:
        if on_status:
            await on_status(agent_config.name, "idle")


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
        chain_depth: Current recursive depth for agent-to-agent chaining.
        agent_chain: Ordered names of agents already invoked in this route chain.
    """
    if chain_depth > MAX_AGENT_CHAIN_DEPTH:
        logger.warning("Agent chain depth exceeded for room %s", message.room_id)
        return []

    mentions = extract_mentions(message.content)
    review_targets = extract_review_targets(message.content)
    clean_content = strip_control_syntax(message.content)

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

    # Build prompt with chat history so agent can see prior conversation
    prompt_with_history = await _build_prompt_with_history(
        db,
        message.room_id,
        clean_content,
        message.id,
        include_current_message_in_history=message.sender_type != "human",
    )

    responses: list[Message] = []
    tasks = [
        asyncio.create_task(_run_agent_call(cfg, prompt_with_history, on_status))
        for cfg in targets
    ]
    for task in asyncio.as_completed(tasks):
        try:
            agent_config, response_text = await task
        except Exception as e:
            logger.error(f"Agent call failed: {e}")
            continue

        agent_message = Message(
            room_id=message.room_id,
            sender_type=agent_config.agent_type,
            sender_name=agent_config.display_name,
            content=response_text,
        )
        db.add(agent_message)
        await db.flush()
        await db.refresh(agent_message)
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
            try:
                _, review_text = await _run_agent_call(
                    reviewer_config,
                    review_prompt,
                    on_status,
                )
            except Exception as e:
                logger.error(
                    "Review agent %s failed after %s response: %s",
                    reviewer_config.name,
                    agent_config.name,
                    e,
                )
                continue

            review_message = Message(
                room_id=message.room_id,
                sender_type=reviewer_config.agent_type,
                sender_name=reviewer_config.display_name,
                content=review_text,
            )
            db.add(review_message)
            await db.flush()
            await db.refresh(review_message)
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
            chain_depth=chain_depth + 1,
            agent_chain=chained_agents,
        )
        responses.extend(chained_responses)

    return responses
