"""Low-level agent execution helpers.

This module owns provider invocation, provider session sync, transient message
construction, and persistence helpers that should not live in the run
orchestrator.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.agent_artifact import AgentArtifact
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.services.agent_memory_store import (
    get_or_create_agent_memory,
    sync_agent_memory_from_runtime,
)
from app.services.artifact_extractor import ExtractedArtifact
from app.services.claude_agent import ClaudeAgent
from app.services.codex_agent import CodexAgent
from app.services.collaboration_runtime import (
    PermissionEscalationRequired,
    is_permission_error,
    next_permission_mode,
)
from app.services.prompt_builder import PLATFORM_AGENT_SYSTEM_PROMPT
from app.services.run_hooks import RunHooks
from app.services.session_manager import session_manager

logger = logging.getLogger(__name__)

AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
}


class AgentExecutionFailed(RuntimeError):
    def __init__(
        self,
        *,
        agent_name: str,
        agent_display_name: str,
        error_type: str,
        error_text: str,
    ) -> None:
        super().__init__(error_text)
        self.agent_name = agent_name
        self.agent_display_name = agent_display_name
        self.error_type = error_type
        self.error_text = error_text


async def hydrate_runtime_from_memory(
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


async def sync_runtime_to_memory(
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


async def create_agent_artifact(
    db: AsyncSession,
    run: CollaborationRun,
    message: Message,
    agent_name: str,
    extracted: ExtractedArtifact,
    hooks: RunHooks,
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
    await hooks.emit_artifact(artifact)
    return artifact


async def call_agent(
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
        reasoning_effort=agent_config.reasoning_effort,
        permission_mode=override_permission_mode or agent_config.permission_mode,
        allowed_tools=agent_config.allowed_tools,
        system_prompt=effective_system_prompt,
        default_args=agent_config.default_args,
    )

    if room_id and db and manage_room_memory:
        await hydrate_runtime_from_memory(db, room_id, agent_config.name)

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
            await sync_runtime_to_memory(db, room_id, agent_config.name)

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
        raise AgentExecutionFailed(
            agent_name=agent_config.name,
            agent_display_name=agent_config.display_name,
            error_type="timeout" if isinstance(e, TimeoutError) else "runtime_error",
            error_text=error_text,
        ) from e
    finally:
        if room_id:
            session_manager.finish_run(agent_config.name, room_id)
        else:
            session_manager.finish_run(agent_config.name)

    return agent_config, response_text


def build_transient_agent_message(
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


async def persist_agent_response(
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


async def persist_system_message(
    db: AsyncSession,
    room_id: str,
    *,
    content: str,
) -> Message:
    message = Message(
        room_id=room_id,
        sender_type="system",
        sender_name="System",
        content=content,
    )
    db.add(message)
    await db.flush()
    return message


def format_agent_failure_message(
    agent_config: AgentConfig,
    step_type: str,
    error: AgentExecutionFailed,
) -> str:
    if error.error_type == "timeout":
        return (
            f"{agent_config.display_name} timed out after {agent_config.max_timeout} seconds "
            f"during the {step_type} step."
        )
    return f"{agent_config.display_name} failed during the {step_type} step: {error.error_text}"
