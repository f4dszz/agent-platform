"""Session manager — tracks agent sessions and handles rotation.

Each agent maintains a session with a unique ID for context continuity.
When the session approaches the context limit (by message count or estimated
tokens), the manager triggers rotation: the agent is asked to summarize,
a new session is created with the summary as context.
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class AgentSession:
    """In-memory session state for a single agent."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    provider_session_id: str | None = None
    message_count: int = 0
    estimated_tokens: int = 0
    active_runs: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summaries: list[str] = field(default_factory=list)


class SessionManager:
    """Manages agent sessions in memory.

    This is a simple in-memory implementation. For production, sessions
    should be persisted to the database.
    """

    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}

    def get_session(self, agent_name: str) -> dict | None:
        """Get session info as a dict, or None if no session exists."""
        session = self._sessions.get(agent_name)
        if not session:
            return None
        return {
            "session_id": session.session_id,
            "provider_session_id": session.provider_session_id,
            "message_count": session.message_count,
            "estimated_tokens": session.estimated_tokens,
            "busy": session.active_runs > 0,
            "created_at": session.created_at.isoformat(),
        }

    def get_or_create_session(self, agent_name: str) -> dict:
        """Get existing session or create a new one."""
        if agent_name not in self._sessions:
            session = AgentSession(agent_name=agent_name)
            self._sessions[agent_name] = session
            logger.info(
                f"Created new session for {agent_name}: {session.session_id}"
            )
        return self.get_session(agent_name)  # type: ignore[return-value]

    def start_run(self, agent_name: str) -> None:
        """Increment the number of in-flight runs for an agent."""
        self.get_or_create_session(agent_name)
        self._sessions[agent_name].active_runs += 1

    def finish_run(self, agent_name: str) -> None:
        """Decrement the number of in-flight runs for an agent."""
        if agent_name in self._sessions:
            session = self._sessions[agent_name]
            session.active_runs = max(0, session.active_runs - 1)

    def set_busy(self, agent_name: str, busy: bool) -> None:
        """Backwards-compatible wrapper for callers that set a boolean status."""
        self.get_or_create_session(agent_name)
        self._sessions[agent_name].active_runs = 1 if busy else 0

    def get_provider_session_id(self, agent_name: str) -> str | None:
        session = self._sessions.get(agent_name)
        return session.provider_session_id if session else None

    def set_provider_session_id(self, agent_name: str, provider_session_id: str) -> None:
        self.get_or_create_session(agent_name)
        self._sessions[agent_name].provider_session_id = provider_session_id

    def increment_messages(self, agent_name: str, estimated_tokens: int = 0) -> None:
        """Increment the message count and token estimate for a session."""
        if agent_name in self._sessions:
            session = self._sessions[agent_name]
            session.message_count += 1
            session.estimated_tokens += estimated_tokens or 1500  # rough estimate

    def should_rotate(self, agent_name: str) -> bool:
        """Check if a session should be rotated based on limits."""
        session = self._sessions.get(agent_name)
        if not session:
            return False

        if session.message_count >= settings.max_session_messages:
            logger.info(
                f"Session {session.session_id} for {agent_name} hit message limit "
                f"({session.message_count}/{settings.max_session_messages})"
            )
            return True

        if session.estimated_tokens >= settings.max_session_tokens:
            logger.info(
                f"Session {session.session_id} for {agent_name} hit token limit "
                f"({session.estimated_tokens}/{settings.max_session_tokens})"
            )
            return True

        return False

    def rotate_session(self, agent_name: str, summary: str | None = None) -> dict:
        """Rotate to a new session, optionally preserving a summary.

        Args:
            agent_name: The agent whose session to rotate.
            summary: Optional summary of the previous session.

        Returns:
            The new session info dict.
        """
        old_session = self._sessions.get(agent_name)
        old_id = old_session.session_id if old_session else "none"

        # Create new session
        new_session = AgentSession(agent_name=agent_name)

        # Carry over summaries
        if old_session and old_session.summaries:
            new_session.summaries = old_session.summaries.copy()
        if summary:
            new_session.summaries.append(summary)

        self._sessions[agent_name] = new_session
        logger.info(
            f"Rotated session for {agent_name}: {old_id} → {new_session.session_id}"
        )

        return self.get_session(agent_name)  # type: ignore[return-value]

    def clear_session(self, agent_name: str) -> None:
        """Remove an agent's session entirely."""
        if agent_name in self._sessions:
            del self._sessions[agent_name]
            logger.info(f"Cleared session for {agent_name}")

    def all_sessions(self) -> dict[str, dict]:
        """Get all sessions as a dict of agent_name → session info."""
        return {
            name: self.get_session(name)  # type: ignore[misc]
            for name in self._sessions
        }


# Singleton instance
session_manager = SessionManager()
