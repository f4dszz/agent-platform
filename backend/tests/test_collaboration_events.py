import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.agent import AgentConfig
from app.models.agent_artifact import AgentArtifact
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.room import Room
from app.services.orchestrator import route_message
from app.ws.handler import ConnectionManager


class AsyncDbTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()


class CollaborationEventTests(AsyncDbTestCase):
    async def test_route_message_emits_run_and_artifact_callbacks(self):
        async with self.session_factory() as db:
            room = Room(name="review-events-room")
            claude = AgentConfig(
                name="claude",
                display_name="Claude Code",
                agent_type="claude",
                command="claude",
            )
            codex = AgentConfig(
                name="codex",
                display_name="Codex CLI",
                agent_type="codex",
                command="codex",
            )
            db.add_all([room, claude, codex])
            await db.flush()

            message = Message(
                room_id=room.id,
                sender_type="human",
                sender_name="User",
                content="@claude draft the plan #review-by=codex",
            )
            db.add(message)
            await db.flush()

            seen_run_updates: list[tuple[str, int, int, str | None]] = []
            seen_artifacts: list[tuple[str, str, str | None]] = []

            async def fake_call_agent(agent_config, prompt, **_kwargs):
                if agent_config.name == "codex":
                    return agent_config, "#artifact=review\n#status=approved\nLooks good"
                if "#artifact=decision" in prompt:
                    return agent_config, "#artifact=decision\n#status=completed\nShip it"
                return agent_config, "#artifact=plan\nDo the thing"

            async def on_run_update(run: CollaborationRun):
                seen_run_updates.append(
                    (run.status, run.step_count, run.review_round_count, run.stop_reason)
                )

            async def on_artifact(artifact: AgentArtifact):
                seen_artifacts.append(
                    (artifact.artifact_type, artifact.agent_name, artifact.status)
                )

            with patch(
                "app.services.orchestrator._build_prompt_with_history",
                new=AsyncMock(return_value="primary prompt"),
            ), patch(
                "app.services.orchestrator._get_git_context",
                return_value="Current git branch: feature/test.\nWorking tree status: clean.",
            ), patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ):
                await route_message(
                    message,
                    db,
                    on_run_update=on_run_update,
                    on_artifact=on_artifact,
                )

            self.assertEqual(
                seen_artifacts,
                [
                    ("plan", "claude", None),
                    ("review", "codex", "approved"),
                    ("decision", "claude", "completed"),
                ],
            )
            self.assertEqual(
                seen_run_updates,
                [
                    ("running", 0, 0, None),
                    ("running", 1, 0, None),
                    ("running", 2, 1, None),
                    ("completed", 3, 1, "decision_completed"),
                ],
            )


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_serializes_concurrent_sends_for_same_socket(self):
        manager = ConnectionManager()

        class FakeWebSocket:
            def __init__(self):
                self.accepted = False
                self.in_send = False
                self.payloads: list[str] = []

            async def accept(self):
                self.accepted = True

            async def send_text(self, payload: str):
                if self.in_send:
                    raise RuntimeError('concurrent send')
                self.in_send = True
                try:
                    await asyncio.sleep(0.01)
                    self.payloads.append(payload)
                finally:
                    self.in_send = False

        ws = FakeWebSocket()
        await manager.connect(ws, 'room-1')

        await asyncio.gather(
            manager.broadcast('room-1', {'type': 'first'}),
            manager.broadcast('room-1', {'type': 'second'}),
        )

        self.assertTrue(ws.accepted)
        self.assertEqual(len(ws.payloads), 2)
        self.assertIn('room-1', manager._rooms)
        self.assertIn(ws, manager._rooms['room-1'])

