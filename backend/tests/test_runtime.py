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
from app.services.agent_memory_store import refresh_agent_memory_summary
from app.services.orchestrator import (
    _build_prompt_with_history,
    _build_review_prompt,
    _call_agent,
    extract_agent_handoff_targets,
    extract_agent_handoff_request,
    extract_referenced_agent_names,
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
                "codex",
                "UNIQUE_CURRENT_REQUEST",
                current.id,
            )

            self.assertIn("[Alice]: first request", prompt)
            self.assertIn("Now respond to this request: UNIQUE_CURRENT_REQUEST", prompt)
            self.assertEqual(prompt.count("UNIQUE_CURRENT_REQUEST"), 1)

    async def test_build_prompt_can_include_current_agent_message_in_history(self):
        async with self.session_factory() as db:
            room = Room(name="agent-chain-history")
            db.add(room)
            await db.flush()

            current = Message(
                room_id=room.id,
                sender_type="claude",
                sender_name="Claude Code",
                content="Here is a joke.\n@codex your turn.",
            )
            db.add(current)
            await db.commit()

            prompt = await _build_prompt_with_history(
                db,
                room.id,
                "codex",
                "your turn.",
                current.id,
                include_current_message_in_history=True,
            )

            self.assertIn("[Claude Code]: Here is a joke.", prompt)
            self.assertIn("@codex your turn.", prompt)
            self.assertIn("Now respond to this request: your turn.", prompt)

    async def test_build_prompt_includes_persisted_long_term_memory(self):
        async with self.session_factory() as db:
            room = Room(name="long-memory-room", description="Refactor the auth area safely.")
            db.add(room)
            await db.flush()

            for index in range(6):
                db.add(
                    Message(
                        room_id=room.id,
                        sender_type="human",
                        sender_name="User",
                        content=f"historical note {index}",
                    )
                )
            await db.flush()

            memory = await refresh_agent_memory_summary(db, room.id, "codex", max_recent_messages=2)
            memory.pinned_memory = "Keep compatibility with the existing API."
            await db.commit()

            prompt = await _build_prompt_with_history(
                db,
                room.id,
                "codex",
                "propose the next change",
                "missing-current-message",
                max_messages=2,
            )

            self.assertIn("--- LONG-TERM MEMORY ---", prompt)
            self.assertIn("Room brief:", prompt)
            self.assertIn("Refactor the auth area safely.", prompt)
            self.assertIn("Pinned long-term memory:", prompt)
            self.assertIn("Keep compatibility with the existing API.", prompt)
            self.assertIn("Earlier room context summary:", prompt)
            self.assertIn("- [User] historical note 0", prompt)
            self.assertIn("- [User] historical note 3", prompt)
            self.assertNotIn("- [User] historical note 4", prompt)
            self.assertIn("[User]: historical note 4", prompt)
            self.assertIn("[User]: historical note 5", prompt)

    async def test_refresh_agent_memory_summary_persists_room_digest(self):
        async with self.session_factory() as db:
            room = Room(name="memory-digest-room")
            db.add(room)
            await db.flush()

            for index in range(5):
                db.add(
                    Message(
                        room_id=room.id,
                        sender_type="human",
                        sender_name="User",
                        content=f"step {index}",
                    )
                )
            await db.flush()

            memory = await refresh_agent_memory_summary(db, room.id, "claude", max_recent_messages=2)
            await db.commit()

            self.assertEqual(memory.summary_message_count, 3)
            self.assertEqual(
                memory.memory_summary,
                "\n".join(
                    [
                        "- [User] step 0",
                        "- [User] step 1",
                        "- [User] step 2",
                    ]
                ),
            )

    def test_review_directive_helpers(self):
        content = "@claude refactor auth #review-by=codex, claude, codex"
        self.assertEqual(extract_review_targets(content), ["codex", "claude"])
        self.assertEqual(strip_control_syntax(content), "refactor auth")

    def test_agent_handoff_requires_explicit_syntax(self):
        content = "You can also ask @codex for a second opinion."
        self.assertEqual(extract_agent_handoff_targets(content), [])
        self.assertEqual(
            extract_agent_handoff_request(content),
            "You can also ask for a second opinion.",
        )

        explicit_handoff = "Plan draft.\n@codex review this\n#handoff=claude"
        self.assertEqual(
            extract_agent_handoff_targets(explicit_handoff),
            ["codex", "claude"],
        )
        self.assertEqual(
            extract_agent_handoff_request(explicit_handoff),
            "review this",
        )

        directive_handoff = "Plan draft.\n#handoff=codex\nReview the plan above."
        self.assertEqual(
            extract_agent_handoff_request(directive_handoff),
            "Review the plan above.",
        )

    def test_extract_referenced_agent_names_from_human_text(self):
        agents = [
            AgentConfig(
                name="claude",
                display_name="Claude Code",
                agent_type="claude",
                command="claude",
            ),
            AgentConfig(
                name="codex",
                display_name="Codex CLI",
                agent_type="codex",
                command="codex",
            ),
        ]
        content = "@claude plan first, then let codex review, and compare Claude Code with Codex CLI"
        self.assertEqual(
            extract_referenced_agent_names(content, agents),
            ["claude", "codex"],
        )


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

            async def fake_call_agent(agent_config, prompt, **_kwargs):
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

            async def fake_call_agent(agent_config, prompt, **_kwargs):
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

    async def test_route_message_triggers_agent_mentions_from_agent_response(self):
        async with self.session_factory() as db:
            room = Room(name="agent-chain-room")
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
                content="@claude tell a joke",
            )
            db.add(message)
            await db.flush()

            seen_prompts: list[tuple[str, str]] = []
            seen_statuses: list[tuple[str, str]] = []

            async def fake_call_agent(agent_config, prompt, **_kwargs):
                seen_prompts.append((agent_config.name, prompt))
                if agent_config.name == "claude":
                    return agent_config, "Joke body.\n@codex continue in Chinese."
                return agent_config, "Chinese continuation"

            async def on_status(agent_name: str, status: str):
                seen_statuses.append((agent_name, status))

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ):
                responses = await route_message(
                    message,
                    db,
                    on_status=on_status,
                )

            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code", "Codex CLI"],
            )
            self.assertEqual(
                seen_statuses,
                [
                    ("claude", "working"),
                    ("claude", "idle"),
                    ("codex", "working"),
                    ("codex", "idle"),
                ],
            )
            self.assertEqual(seen_prompts[0][0], "claude")
            self.assertEqual(seen_prompts[1][0], "codex")
            self.assertIn("[Claude Code]: Joke body.", seen_prompts[1][1])
            self.assertIn("@codex continue in Chinese.", seen_prompts[1][1])
            self.assertIn("Now respond to this request: continue in Chinese.", seen_prompts[1][1])

    async def test_route_message_ignores_inline_agent_mentions_in_agent_text(self):
        async with self.session_factory() as db:
            room = Room(name="inline-mention-room")
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
                content="@claude explain review options",
            )
            db.add(message)
            await db.flush()

            async def fake_call_agent(agent_config, _prompt, **_kwargs):
                return agent_config, "You can also ask @codex for a second opinion."

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 1)
            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code"],
            )

    async def test_route_message_supports_explicit_handoff_directive(self):
        async with self.session_factory() as db:
            room = Room(name="handoff-directive-room")
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
                content="@claude draft a plan",
            )
            db.add(message)
            await db.flush()

            async def fake_call_agent(agent_config, _prompt, **_kwargs):
                if agent_config.name == "claude":
                    return agent_config, "Plan draft.\n#handoff=codex\nReview this."
                return agent_config, "Review result"

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 2)
            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code", "Codex CLI"],
            )

    async def test_route_message_adds_collaboration_hint_for_named_follow_up_agent(self):
        async with self.session_factory() as db:
            room = Room(name="collaboration-hint-room")
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
                content="@claude plan first, then let codex review",
            )
            db.add(message)
            await db.flush()

            seen_prompts: list[str] = []

            async def fake_call_agent(agent_config, prompt, **_kwargs):
                seen_prompts.append(prompt)
                return agent_config, "Plan draft"

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ):
                responses = await route_message(message, db)

            self.assertEqual([response.sender_name for response in responses], ["Claude Code"])
            self.assertEqual(len(seen_prompts), 1)
            self.assertIn("Platform instruction:", seen_prompts[0])
            self.assertIn("#handoff=codex", seen_prompts[0])
            self.assertIn("do not claim you need permission", seen_prompts[0])

    async def test_route_message_resolves_current_agent_name_from_display_name(self):
        async with self.session_factory() as db:
            room = Room(name="custom-agent-name-room")
            architect = AgentConfig(
                name="architect",
                display_name="Architecture Claude",
                agent_type="claude",
                command="claude",
            )
            codex = AgentConfig(
                name="codex",
                display_name="Codex CLI",
                agent_type="codex",
                command="codex",
            )
            db.add_all([room, architect, codex])
            await db.flush()

            message = Message(
                room_id=room.id,
                sender_type="claude",
                sender_name="Architecture Claude",
                content="@architect self-check\n@codex review this",
            )
            db.add(message)
            await db.flush()

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(return_value=(codex, "reviewed")),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 1)
            self.assertEqual([response.sender_name for response in responses], ["Codex CLI"])

    async def test_route_message_does_not_duplicate_reviewer_via_follow_up_mention(self):
        async with self.session_factory() as db:
            room = Room(name="review-mention-dedupe-room")
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
                content="@claude draft a plan #review-by=codex",
            )
            db.add(message)
            await db.flush()

            async def fake_call_agent(agent_config, _prompt, **_kwargs):
                if agent_config.name == "claude":
                    return agent_config, "Plan draft.\n@codex please review."
                return agent_config, "Review result"

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 2)
            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code", "Codex CLI"],
            )

    async def test_route_message_prevents_agent_ping_pong_loops(self):
        async with self.session_factory() as db:
            room = Room(name="loop-room")
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
                content="@claude start",
            )
            db.add(message)
            await db.flush()

            async def fake_call_agent(agent_config, prompt, **_kwargs):
                if agent_config.name == "claude":
                    return agent_config, "@codex continue"
                return agent_config, "@claude continue back"

            with patch(
                "app.services.orchestrator._call_agent",
                new=AsyncMock(side_effect=fake_call_agent),
            ) as mock_call_agent:
                responses = await route_message(message, db)

            self.assertEqual(mock_call_agent.await_count, 2)
            self.assertEqual(
                [response.sender_name for response in responses],
                ["Claude Code", "Codex CLI"],
            )


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

    async def test_call_agent_appends_platform_collaboration_prompt(self):
        captured_system_prompts: list[str | None] = []

        class FakeClaudeAgent:
            def __init__(self, **kwargs):
                captured_system_prompts.append(kwargs.get("system_prompt"))
                self._last_session_id = None

            @property
            def last_session_id(self):
                return self._last_session_id

            async def send(self, _prompt, session_id=None):
                return "ok"

        agent = AgentConfig(
            name="claude-reuse",
            display_name="Claude Code",
            agent_type="claude",
            command="claude",
            system_prompt="Custom instruction",
        )

        with patch.dict(
            "app.services.orchestrator.AGENT_CLASSES",
            {"claude": FakeClaudeAgent},
            clear=False,
        ):
            await _call_agent(agent, "prompt")

        self.assertEqual(len(captured_system_prompts), 1)
        self.assertIn("Custom instruction", captured_system_prompts[0])
        self.assertIn("#handoff=<agent-name>", captured_system_prompts[0])
        self.assertIn(
            "Do not try to invoke other local CLIs",
            captured_system_prompts[0],
        )

    async def test_call_agent_isolates_provider_sessions_per_room(self):
        captured_calls: list[tuple[str, str | None]] = []
        room_provider_ids = {
            "room-a": "provider-session-room-a",
            "room-b": "provider-session-room-b",
        }

        class FakeClaudeAgent:
            def __init__(self, **_kwargs):
                self._last_session_id = None

            @property
            def last_session_id(self):
                return self._last_session_id

            async def send(self, prompt, session_id=None):
                room_marker = "room-a" if "ROOM_A" in prompt else "room-b"
                captured_calls.append((room_marker, session_id))
                self._last_session_id = session_id or room_provider_ids[room_marker]
                return f"ok-{room_marker}"

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            room_a = Room(name="room-a")
            room_b = Room(name="room-b")
            db.add_all([room_a, room_b])
            await db.flush()

            agent = AgentConfig(
                name="claude-reuse",
                display_name="Claude Code",
                agent_type="claude",
                command="claude",
            )
            db.add(agent)
            await db.flush()

            session_manager.clear_session(agent.name, room_a.id)
            session_manager.clear_session(agent.name, room_b.id)

            with patch.dict(
                "app.services.orchestrator.AGENT_CLASSES",
                {"claude": FakeClaudeAgent},
                clear=False,
            ):
                await _call_agent(agent, "ROOM_A first prompt", db=db, room_id=room_a.id)
                await _call_agent(agent, "ROOM_B first prompt", db=db, room_id=room_b.id)
                await _call_agent(agent, "ROOM_A second prompt", db=db, room_id=room_a.id)

            result = await db.execute(
                text(
                    "SELECT room_id, provider_session_id, message_count "
                    "FROM agent_memories WHERE agent_name = 'claude-reuse' ORDER BY room_id"
                )
            )
            rows = result.all()

            self.assertEqual(
                captured_calls,
                [
                    ("room-a", None),
                    ("room-b", None),
                    ("room-a", "provider-session-room-a"),
                ],
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row.provider_session_id for row in rows},
                set(room_provider_ids.values()),
            )
            self.assertEqual({row.message_count for row in rows}, {1, 2})

        session_manager.clear_session("claude-reuse", room_a.id)
        session_manager.clear_session("claude-reuse", room_b.id)
        await engine.dispose()


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

    async def test_agent_memory_table_exists_in_database_metadata(self):
        async with self.session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'agent_memories'"
                )
            )
            self.assertEqual(result.scalar(), "agent_memories")


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
