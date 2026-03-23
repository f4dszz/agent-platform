import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.models.agent_artifact import AgentArtifact
from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.collaboration_run import CollaborationRun
from app.models.message import Message
from app.models.run_step import RunStep

logger = logging.getLogger(__name__)

ResponseCallback = Callable[[Message], Awaitable[None]]
StatusCallback = Callable[[str, str], Awaitable[None]]
StreamCallback = Callable[[Message, str], Awaitable[None]]
RunCallback = Callable[[CollaborationRun], Awaitable[None]]
ArtifactCallback = Callable[[AgentArtifact], Awaitable[None]]
StepCallback = Callable[[RunStep], Awaitable[None]]
EventCallback = Callable[[AgentEvent], Awaitable[None]]
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[None]]


@dataclass(slots=True)
class RunHooks:
    on_response: ResponseCallback | None = None
    on_status: StatusCallback | None = None
    on_stream: StreamCallback | None = None
    on_run_update: RunCallback | None = None
    on_artifact: ArtifactCallback | None = None
    on_step: StepCallback | None = None
    on_event: EventCallback | None = None
    on_approval: ApprovalCallback | None = None

    async def _safe_call(self, name: str, coro):
        try:
            await coro
        except Exception:
            logger.error("Hook callback %s failed", name, exc_info=True)

    async def emit_response(self, message: Message) -> None:
        if self.on_response:
            await self._safe_call("on_response", self.on_response(message))

    async def emit_status(self, agent_name: str, status: str) -> None:
        if self.on_status:
            await self._safe_call("on_status", self.on_status(agent_name, status))

    async def emit_stream(self, message: Message, content: str) -> None:
        if self.on_stream:
            await self._safe_call("on_stream", self.on_stream(message, content))

    async def emit_run_update(self, run: CollaborationRun) -> None:
        if self.on_run_update:
            await self._safe_call("on_run_update", self.on_run_update(run))

    async def emit_artifact(self, artifact: AgentArtifact) -> None:
        if self.on_artifact:
            await self._safe_call("on_artifact", self.on_artifact(artifact))

    async def emit_step(self, step: RunStep) -> None:
        if self.on_step:
            await self._safe_call("on_step", self.on_step(step))

    async def emit_event(self, event: AgentEvent) -> None:
        if self.on_event:
            await self._safe_call("on_event", self.on_event(event))

    async def emit_approval(self, approval: ApprovalRequest) -> None:
        if self.on_approval:
            await self._safe_call("on_approval", self.on_approval(approval))
