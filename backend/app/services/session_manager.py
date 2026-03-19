"""Room-scoped runtime session manager for agent activity and counters."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class AgentSession:
    """In-memory session state for a single room-agent pair."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str | None = None
    agent_name: str = ""
    provider_session_id: str | None = None
    message_count: int = 0
    estimated_tokens: int = 0
    active_runs: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summaries: list[str] = field(default_factory=list)


class SessionManager:
    """Manages runtime session state keyed by room and agent."""

    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}

    @staticmethod
    def _key(agent_name: str, room_id: str | None = None) -> str:
        return f"{room_id}:{agent_name}" if room_id else agent_name

    def get_session(self, agent_name: str, room_id: str | None = None) -> dict | None:
        session = self._sessions.get(self._key(agent_name, room_id))
        if not session:
            return None
        return {
            "session_id": session.session_id,
            "room_id": session.room_id,
            "provider_session_id": session.provider_session_id,
            "message_count": session.message_count,
            "estimated_tokens": session.estimated_tokens,
            "busy": session.active_runs > 0,
            "created_at": session.created_at.isoformat(),
        }

    def get_or_create_session(
        self,
        agent_name: str,
        room_id: str | None = None,
        provider_session_id: str | None = None,
        message_count: int = 0,
        estimated_tokens: int = 0,
    ) -> dict:
        key = self._key(agent_name, room_id)
        if key not in self._sessions:
            session = AgentSession(
                room_id=room_id,
                agent_name=agent_name,
                provider_session_id=provider_session_id,
                message_count=message_count,
                estimated_tokens=estimated_tokens,
            )
            self._sessions[key] = session
            logger.info(
                "Created new session for %s in room %s: %s",
                agent_name,
                room_id or "(global)",
                session.session_id,
            )
        return self.get_session(agent_name, room_id)  # type: ignore[return-value]

    def hydrate_session(
        self,
        agent_name: str,
        room_id: str,
        provider_session_id: str | None,
        message_count: int,
        estimated_tokens: int,
    ) -> dict:
        key = self._key(agent_name, room_id)
        if key not in self._sessions:
            return self.get_or_create_session(
                agent_name,
                room_id=room_id,
                provider_session_id=provider_session_id,
                message_count=message_count,
                estimated_tokens=estimated_tokens,
            )

        session = self._sessions[key]
        session.provider_session_id = provider_session_id
        session.message_count = message_count
        session.estimated_tokens = estimated_tokens
        return self.get_session(agent_name, room_id)  # type: ignore[return-value]

    def start_run(self, agent_name: str, room_id: str | None = None) -> None:
        self.get_or_create_session(agent_name, room_id)
        self._sessions[self._key(agent_name, room_id)].active_runs += 1

    def finish_run(self, agent_name: str, room_id: str | None = None) -> None:
        key = self._key(agent_name, room_id)
        if key in self._sessions:
            session = self._sessions[key]
            session.active_runs = max(0, session.active_runs - 1)

    def set_busy(
        self,
        agent_name: str,
        busy: bool,
        room_id: str | None = None,
    ) -> None:
        self.get_or_create_session(agent_name, room_id)
        self._sessions[self._key(agent_name, room_id)].active_runs = 1 if busy else 0

    def get_provider_session_id(
        self,
        agent_name: str,
        room_id: str | None = None,
    ) -> str | None:
        session = self._sessions.get(self._key(agent_name, room_id))
        return session.provider_session_id if session else None

    def set_provider_session_id(
        self,
        agent_name: str,
        provider_session_id: str,
        room_id: str | None = None,
    ) -> None:
        self.get_or_create_session(agent_name, room_id)
        self._sessions[self._key(agent_name, room_id)].provider_session_id = provider_session_id

    def increment_messages(
        self,
        agent_name: str,
        estimated_tokens: int = 0,
        room_id: str | None = None,
    ) -> None:
        key = self._key(agent_name, room_id)
        if key in self._sessions:
            session = self._sessions[key]
            session.message_count += 1
            session.estimated_tokens += estimated_tokens or 1500

    def should_rotate(self, agent_name: str, room_id: str | None = None) -> bool:
        session = self._sessions.get(self._key(agent_name, room_id))
        if not session:
            return False

        if session.message_count >= settings.max_session_messages:
            logger.info(
                "Session %s for %s in room %s hit message limit (%s/%s)",
                session.session_id,
                agent_name,
                room_id or "(global)",
                session.message_count,
                settings.max_session_messages,
            )
            return True

        if session.estimated_tokens >= settings.max_session_tokens:
            logger.info(
                "Session %s for %s in room %s hit token limit (%s/%s)",
                session.session_id,
                agent_name,
                room_id or "(global)",
                session.estimated_tokens,
                settings.max_session_tokens,
            )
            return True

        return False

    def rotate_session(
        self,
        agent_name: str,
        room_id: str | None = None,
        summary: str | None = None,
    ) -> dict:
        key = self._key(agent_name, room_id)
        old_session = self._sessions.get(key)
        old_id = old_session.session_id if old_session else "none"

        new_session = AgentSession(room_id=room_id, agent_name=agent_name)
        if old_session and old_session.summaries:
            new_session.summaries = old_session.summaries.copy()
        if summary:
            new_session.summaries.append(summary)

        self._sessions[key] = new_session
        logger.info(
            "Rotated session for %s in room %s: %s -> %s",
            agent_name,
            room_id or "(global)",
            old_id,
            new_session.session_id,
        )
        return self.get_session(agent_name, room_id)  # type: ignore[return-value]

    def clear_session(self, agent_name: str, room_id: str | None = None) -> None:
        key = self._key(agent_name, room_id)
        if key in self._sessions:
            del self._sessions[key]
            logger.info(
                "Cleared session for %s in room %s",
                agent_name,
                room_id or "(global)",
            )

    def get_agent_status(self, agent_name: str) -> dict | None:
        matching = [
            session for session in self._sessions.values() if session.agent_name == agent_name
        ]
        if not matching:
            return None

        latest = max(matching, key=lambda session: session.created_at)
        return {
            "session_id": latest.session_id,
            "room_id": latest.room_id,
            "provider_session_id": latest.provider_session_id,
            "message_count": sum(session.message_count for session in matching),
            "estimated_tokens": sum(session.estimated_tokens for session in matching),
            "busy": any(session.active_runs > 0 for session in matching),
            "created_at": latest.created_at.isoformat(),
        }

    def all_sessions(self) -> dict[str, dict]:
        return {
            key: self.get_session(session.agent_name, session.room_id)  # type: ignore[misc]
            for key, session in self._sessions.items()
        }


session_manager = SessionManager()
