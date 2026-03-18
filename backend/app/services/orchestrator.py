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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.message import Message
from app.services.claude_agent import ClaudeAgent
from app.services.codex_agent import CodexAgent
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"@(\w+)")

AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
}


def extract_mentions(content: str) -> list[str]:
    return [m.lower() for m in MENTION_PATTERN.findall(content)]


def strip_mentions(content: str) -> str:
    return MENTION_PATTERN.sub("", content).strip()


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
    max_messages: int = 20,
) -> str:
    """Prepend recent chat history so the agent can see prior conversation."""
    result = await db.execute(
        select(Message)
        .where(Message.room_id == room_id)
        .where(Message.id != current_message_id)  # exclude current msg to avoid duplication
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    history = list(result.scalars().all())
    history.reverse()  # chronological order

    if not history:
        return current_content

    lines = ["[Chat History]"]
    for msg in history:
        lines.append(f"{msg.sender_name}: {msg.content}")
    lines.append("")
    lines.append("[Current Request]")
    lines.append(current_content)

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
    session_manager.set_busy(agent_config.name, True)

    try:
        response_text = await agent.send(prompt)
        session_manager.increment_messages(agent_config.name)

        if session_manager.should_rotate(agent_config.name):
            session_manager.rotate_session(agent_config.name)

    except (TimeoutError, RuntimeError) as e:
        logger.error(f"Agent {agent_config.name} failed: {e}")
        response_text = f"Agent error: {e}"
    finally:
        session_manager.set_busy(agent_config.name, False)

    return agent_config, response_text


async def route_message(
    message: Message,
    db: AsyncSession,
    on_response=None,
) -> list[Message]:
    """Route an incoming message to the appropriate agents.

    Args:
        message: The incoming message (already saved to DB).
        db: Database session.
        on_response: Optional async callback(Message) called as each agent responds
                     (for real-time broadcast before all agents finish).
    """
    mentions = extract_mentions(message.content)
    clean_content = strip_mentions(message.content)

    if not mentions:
        return []

    enabled_agents = await get_enabled_agents(db)
    agent_map = {a.name.lower(): a for a in enabled_agents}

    targets: list[AgentConfig] = []
    if "all" in mentions:
        targets = enabled_agents
    else:
        for mention in mentions:
            if mention in agent_map:
                targets.append(agent_map[mention])

    if not targets:
        return []

    # Build prompt with chat history so agent can see prior conversation
    prompt_with_history = await _build_prompt_with_history(
        db, message.room_id, clean_content, message.id
    )

    # Call all agents in parallel
    tasks = [_call_agent(cfg, prompt_with_history) for cfg in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    responses: list[Message] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Agent call failed: {result}")
            continue

        agent_config, response_text = result

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

    return responses
