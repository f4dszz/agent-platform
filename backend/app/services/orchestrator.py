"""Message orchestrator — routes messages to the appropriate agents.

Rules:
  - @claude → send to Claude only
  - @codex  → send to Codex only
  - @all    → send to all enabled agents sequentially
  - No mention → broadcast to room, no agent auto-reply (human chat)
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.message import Message
from app.services.claude_agent import ClaudeAgent
from app.services.codex_agent import CodexAgent
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

# Pattern matches @word at word boundaries
MENTION_PATTERN = re.compile(r"@(\w+)")

# Map of agent_type → agent wrapper class
AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
}


def extract_mentions(content: str) -> list[str]:
    """Extract @mentions from message content.

    Returns:
        List of lowercase mention names (e.g., ["claude", "codex", "all"]).
    """
    return [m.lower() for m in MENTION_PATTERN.findall(content)]


def strip_mentions(content: str) -> str:
    """Remove @mentions from the message for cleaner agent input."""
    return MENTION_PATTERN.sub("", content).strip()


async def get_enabled_agents(db: AsyncSession) -> list[AgentConfig]:
    """Fetch all enabled agent configs from the database."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.enabled.is_(True))
    )
    return list(result.scalars().all())


async def route_message(
    message: Message,
    db: AsyncSession,
) -> list[Message]:
    """Route an incoming message to the appropriate agents.

    Args:
        message: The incoming message (already saved to DB).
        db: Database session.

    Returns:
        List of agent response Messages (already saved to DB).
    """
    mentions = extract_mentions(message.content)
    clean_content = strip_mentions(message.content)

    if not mentions:
        # No mentions — human chat, no agent response
        logger.info("No agent mentions in message, skipping agent routing")
        return []

    # Get all enabled agents
    enabled_agents = await get_enabled_agents(db)
    agent_map = {a.name.lower(): a for a in enabled_agents}

    # Determine which agents to invoke
    targets: list[AgentConfig] = []

    if "all" in mentions:
        targets = enabled_agents
    else:
        for mention in mentions:
            if mention in agent_map:
                targets.append(agent_map[mention])
            else:
                logger.warning(f"Mentioned agent @{mention} not found or disabled")

    if not targets:
        logger.info("No valid agent targets found for mentions: %s", mentions)
        return []

    # Invoke agents sequentially so each can see the previous response
    responses: list[Message] = []

    for agent_config in targets:
        agent_class = AGENT_CLASSES.get(agent_config.agent_type)
        if not agent_class:
            logger.error(f"No wrapper class for agent type: {agent_config.agent_type}")
            continue

        agent = agent_class(
            command=agent_config.command,
            timeout=agent_config.max_timeout,
        )

        # Get or create session (session_id is tracked but not passed to CLI
        # by default — each `claude -p` call is independent. Session continuity
        # can be enabled later for multi-turn conversations.)
        session = session_manager.get_or_create_session(agent_config.name)

        # Mark agent as busy
        session_manager.set_busy(agent_config.name, True)

        try:
            # Build context: include previous response if multi-agent chain
            prompt = clean_content
            if responses:
                prev = responses[-1]
                prompt = (
                    f"Previous agent ({prev.sender_name}) responded:\n"
                    f"{prev.content}\n\n"
                    f"Original request: {clean_content}"
                )

            # Send to agent
            response_text = await agent.send(prompt)

            # Track message in session
            session_manager.increment_messages(agent_config.name)

            # Check if session needs rotation
            if session_manager.should_rotate(agent_config.name):
                logger.info(f"Session rotation needed for {agent_config.name}")
                # TODO: Ask agent to summarize, then rotate
                session_manager.rotate_session(agent_config.name)

        except (TimeoutError, RuntimeError) as e:
            logger.error(f"Agent {agent_config.name} failed: {e}")
            response_text = f"⚠️ Agent error: {e}"

        finally:
            session_manager.set_busy(agent_config.name, False)

        # Save agent response to DB
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

    return responses
