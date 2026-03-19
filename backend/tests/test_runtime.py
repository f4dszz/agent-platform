import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, engine as app_engine
from app.models.agent import AgentConfig
from app.models.message import Message
from app.models.room import Room
from app.services.orchestrator import (
    _build_prompt_with_history,
    _build_review_prompt,
    _call_agent,
    extract_review_targets,
    route_message,
    strip_control_syntax,
)
from app.services.session_manager import SessionManager, session_manager
from app.ws.handler import _room_exists


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


class PromptHistoryTests(AsyncDbTestCase):
    async def test_build_prompt_excludes_current_message_from_history(self):
        async with self.session_factory() as db:
            room = Room(name="runtime-tests")
            db.add(room)
            await db.flush()

            db.add(
                Message(
                    room_id=room.id,
                    sender_type="human",
                    sender_name="Alice",
                    content="first request",
                )
            )
            current = Message(
                room_id=room.id,
                sender_type="human",
                sender_name="Bob",
                content="@codex UNIQUE_CURRENT_REQUEST",
            )
            db.add(current)
            await db.commit()

            prompt = await _build_prompt_with_history(
                db,
                room.id,
                "UNIQUE_CURRENT_REQUEST",
                current.id,
            )

            self.assertIn("[Alice]: first request", prompt)
            self.assertIn("Now respond to this request: UNIQUE_CURRENT_REQUEST", prompt)
            self.assertEqual(prompt.count("UNIQUE_CURRENT_REQUEST"), 1)

    def test_review_directive_helpers(self):
        content = "@claude refactor auth #review-by=codex, claude, codex"
        self.assertEqual(extract_review_targets(content), ["codex", "claude"])
        self.assertEqual(strip_control_syntax(content), "refactor auth")


class RouteMessageTests(AsyncDbTestCase):
    async def test_route_message_deduplicates_duplicate_mentions(self):
        async with self.session_factory() as db:
            room = Room(name="route-room")
            agent = AgentConfig(
                name="claude",
                display_name="Claude Code",
                agent_type="claude",
                command="claude",
            )
            db.add_all([room, agent])
            await db.flush()

            message = Message(
                room_id=room.id,
                sender_type="human",
                sender_name="User",
                content="@claude @claude fix this",
            )
            db.add(message)
            await db.flush()

            with patch(
                "app.services.orchestrator._build_prompt_with_history",
                new=AsyncMock(return_value="prompt"),
            ), patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(return_value=(agent, "done")),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 1)
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].content, "done")

    async def test_route_message_emits_responses_in_completion_order(self):
        async with self.session_factory() as db:
            room = Room(name="stream-room")
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
                content="@all review this refactor",
            )
            db.add(message)
            await db.flush()

            async def fake_call_agent(agent_config, prompt):
                delay = 0.05 if agent_config.name == "claude" else 0.01
                await asyncio.sleep(delay)
                return agent_config, f"{agent_config.name}-response"

            seen: list[str] = []

            async def on_response(resp_msg):
                seen.append(resp_msg.sender_name)

            with patch(
                "app.services.orchestrator._build_prompt_with_history",
                new=AsyncMock(return_value="prompt"),
            ), patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ):
                responses = await route_message(message, db, on_response=on_response)

            self.assertEqual(seen, ["Codex CLI", "Claude Code"])
            self.assertEqual(
                [response.sender_name for response in responses],
                ["Codex CLI", "Claude Code"],
            )

    async def test_route_message_auto_triggers_review_chain(self):
        async with self.session_factory() as db:
            room = Room(name="review-room")
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
                content="@claude refactor auth flow #review-by=codex",
            )
            db.add(message)
            await db.flush()

            seen_prompts: list[tuple[str, str]] = []
            seen_statuses: list[tuple[str, str]] = []
            seen_responses: list[str] = []

            async def fake_call_agent(agent_config, prompt):
                seen_prompts.append((agent_config.name, prompt))
                if agent_config.name == "claude":
                    return agent_config, "Primary plan"
                return agent_config, "Review notes"

            async def on_status(agent_name: str, status: str):
                seen_statuses.append((agent_name, status))

            async def on_response(resp_msg: Message):
                seen_responses.append(resp_msg.sender_name)

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
                responses = await route_message(
                    message,
                    db,
                    on_response=on_response,
                    on_status=on_status,
                )

            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code", "Codex CLI"],
            )
            self.assertEqual(seen_responses, ["Claude Code", "Codex CLI"])
            self.assertEqual(
                seen_statuses,
                [
                    ("claude", "working"),
                    ("claude", "idle"),
                    ("codex", "working"),
                    ("codex", "idle"),
                ],
            )
            self.assertEqual(seen_prompts[0], ("claude", "primary prompt"))
            self.assertEqual(seen_prompts[1][0], "codex")
            self.assertIn("Current git branch: feature/test.", seen_prompts[1][1])
            self.assertIn("Original user request:\nrefactor auth flow", seen_prompts[1][1])
            self.assertIn("Claude Code response to review:\nPrimary plan", seen_prompts[1][1])


class SessionManagerTests(unittest.TestCase):
    def test_session_manager_tracks_concurrent_runs(self):
        manager = SessionManager()

        manager.start_run("claude")
        manager.start_run("claude")
        self.assertTrue(manager.get_session("claude")["busy"])

        manager.finish_run("claude")
        self.assertTrue(manager.get_session("claude")["busy"])

        manager.finish_run("claude")
        self.assertFalse(manager.get_session("claude")["busy"])


class AgentSessionReuseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        session_manager.clear_session("claude-reuse")

    async def asyncTearDown(self):
        session_manager.clear_session("claude-reuse")

    async def test_call_agent_reuses_provider_session_id(self):
        captured_session_ids: list[str | None] = []

        class FakeClaudeAgent:
            def __init__(self, **_kwargs):
                self._last_session_id = None

            @property
            def last_session_id(self):
                return self._last_session_id

            async def send(self, _prompt, session_id=None):
                captured_session_ids.append(session_id)
                if session_id is None:
                    self._last_session_id = "provider-session-1"
                else:
                    self._last_session_id = session_id
                return "ok"

        agent = AgentConfig(
            name="claude-reuse",
            display_name="Claude Code",
            agent_type="claude",
            command="claude",
        )

        with patch.dict(
            "app.services.orchestrator.AGENT_CLASSES",
            {"claude": FakeClaudeAgent},
            clear=False,
        ):
            await _call_agent(agent, "first prompt")
            await _call_agent(agent, "second prompt")

        self.assertEqual(captured_session_ids, [None, "provider-session-1"])


class DatabaseAndRoomValidationTests(AsyncDbTestCase):
    async def test_sqlite_foreign_keys_are_enabled_on_app_engine(self):
        async with app_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA foreign_keys"))
            self.assertEqual(result.scalar(), 1)

    async def test_room_exists_helper_matches_database_state(self):
        async with self.session_factory() as db:
            room = Room(name="existing-room")
            db.add(room)
            await db.commit()

            self.assertTrue(await _room_exists(db, room.id))
            self.assertFalse(await _room_exists(db, "missing-room"))


class ReviewPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_review_prompt_includes_git_context(self):
        agent = AgentConfig(
            name="claude",
            display_name="Claude Code",
            agent_type="claude",
            command="claude",
        )
        with patch(
            "app.services.orchestrator._get_git_context",
            return_value="Current git branch: review-branch.\nWorking tree status: clean.",
        ):
            prompt = await _build_review_prompt(
                "refactor service layer",
                agent,
                "Plan text",
            )

        self.assertIn("Current git branch: review-branch.", prompt)
        self.assertIn("Original user request:\nrefactor service layer", prompt)
        self.assertIn("Claude Code response to review:\nPlan text", prompt)
