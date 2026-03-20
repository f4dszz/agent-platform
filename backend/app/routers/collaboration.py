import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session, get_db
from app.models.agent_event import AgentEvent
from app.models.approval_request import ApprovalRequest
from app.models.agent_artifact import AgentArtifact
from app.models.collaboration_run import CollaborationRun
from app.models.room import Room
from app.models.run_step import RunStep
from app.schemas.schemas import (
    AgentArtifactList,
    AgentEventList,
    ApprovalRequestList,
    ApprovalRequestResponse,
    CollaborationRunList,
    CollaborationRunResponse,
    RunStepList,
)
from app.services.collaboration_runtime import APPROVAL_STATUS_APPROVED, resolve_approval
from app.services.orchestrator import deny_approval_request, resume_approval_request

router = APIRouter()


async def _ensure_room_exists(db: AsyncSession, room_id: str) -> None:
    room_result = await db.execute(select(Room.id).where(Room.id == room_id))
    if not room_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")


async def _build_broadcast_callbacks(room_id: str):
    from app.ws.handler import (
        agent_event_to_dict,
        approval_to_dict,
        artifact_to_dict,
        manager,
        message_to_dict,
        run_step_to_dict,
        run_to_dict,
        stream_chunk_to_dict,
    )

    async def on_response(resp_msg):
        await manager.broadcast(room_id, message_to_dict(resp_msg))

    async def on_status(agent_name: str, status: str):
        await manager.broadcast(
            room_id,
            {
                "type": "status",
                "agent_name": agent_name,
                "status": status,
            },
        )

    async def on_stream(stream_msg, content: str):
        await manager.broadcast(room_id, stream_chunk_to_dict(stream_msg, content))

    async def on_run_update(run: CollaborationRun):
        await manager.broadcast(room_id, run_to_dict(run))

    async def on_artifact(artifact: AgentArtifact):
        await manager.broadcast(room_id, artifact_to_dict(artifact))

    async def on_step(step: RunStep):
        await manager.broadcast(room_id, run_step_to_dict(step))

    async def on_event(event: AgentEvent):
        await manager.broadcast(room_id, agent_event_to_dict(event))

    async def on_approval(approval: ApprovalRequest):
        await manager.broadcast(room_id, approval_to_dict(approval))

    return {
        "on_response": on_response,
        "on_status": on_status,
        "on_stream": on_stream,
        "on_run_update": on_run_update,
        "on_artifact": on_artifact,
        "on_step": on_step,
        "on_event": on_event,
        "on_approval": on_approval,
    }


@router.get("/rooms/{room_id}/runs", response_model=CollaborationRunList)
async def list_room_runs(
    room_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    room_result = await db.execute(select(Room.id).where(Room.id == room_id))
    if not room_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")

    stmt = (
        select(CollaborationRun)
        .where(CollaborationRun.room_id == room_id)
        .order_by(CollaborationRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    runs = list(result.scalars().all())

    count_result = await db.execute(
        select(func.count(CollaborationRun.id)).where(CollaborationRun.room_id == room_id)
    )
    total = count_result.scalar() or 0
    return CollaborationRunList(runs=runs, total=total)


@router.get("/rooms/{room_id}/artifacts", response_model=AgentArtifactList)
async def list_room_artifacts(
    room_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    room_result = await db.execute(select(Room.id).where(Room.id == room_id))
    if not room_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")

    stmt = (
        select(AgentArtifact)
        .where(AgentArtifact.room_id == room_id)
        .order_by(AgentArtifact.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    artifacts = list(result.scalars().all())

    count_result = await db.execute(
        select(func.count(AgentArtifact.id)).where(AgentArtifact.room_id == room_id)
    )
    total = count_result.scalar() or 0
    return AgentArtifactList(artifacts=artifacts, total=total)


@router.get("/rooms/{room_id}/steps", response_model=RunStepList)
async def list_room_steps(
    room_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_room_exists(db, room_id)
    stmt = (
        select(RunStep)
        .where(RunStep.room_id == room_id)
        .order_by(RunStep.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    steps = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(RunStep.id)).where(RunStep.room_id == room_id)
    )
    total = count_result.scalar() or 0
    return RunStepList(steps=steps, total=total)


@router.get("/rooms/{room_id}/events", response_model=AgentEventList)
async def list_room_events(
    room_id: str,
    limit: int = Query(default=300, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_room_exists(db, room_id)
    stmt = (
        select(AgentEvent)
        .where(AgentEvent.room_id == room_id)
        .order_by(AgentEvent.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(AgentEvent.id)).where(AgentEvent.room_id == room_id)
    )
    total = count_result.scalar() or 0
    return AgentEventList(events=events, total=total)


@router.get("/rooms/{room_id}/approvals", response_model=ApprovalRequestList)
async def list_room_approvals(
    room_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_room_exists(db, room_id)
    stmt = (
        select(ApprovalRequest)
        .where(ApprovalRequest.room_id == room_id)
        .order_by(ApprovalRequest.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    approvals = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(ApprovalRequest.id)).where(ApprovalRequest.room_id == room_id)
    )
    total = count_result.scalar() or 0
    return ApprovalRequestList(approvals=approvals, total=total)


@router.get("/runs/{run_id}", response_model=CollaborationRunResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CollaborationRun).where(CollaborationRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/artifacts", response_model=AgentArtifactList)
async def list_run_artifacts(run_id: str, db: AsyncSession = Depends(get_db)):
    run_result = await db.execute(
        select(CollaborationRun.id).where(CollaborationRun.id == run_id)
    )
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    stmt = (
        select(AgentArtifact)
        .where(AgentArtifact.run_id == run_id)
        .order_by(AgentArtifact.created_at.asc())
    )
    result = await db.execute(stmt)
    artifacts = list(result.scalars().all())

    count_result = await db.execute(
        select(func.count(AgentArtifact.id)).where(AgentArtifact.run_id == run_id)
    )
    total = count_result.scalar() or 0
    return AgentArtifactList(artifacts=artifacts, total=total)


@router.get("/runs/{run_id}/steps", response_model=RunStepList)
async def list_run_steps(run_id: str, db: AsyncSession = Depends(get_db)):
    run_result = await db.execute(
        select(CollaborationRun.id).where(CollaborationRun.id == run_id)
    )
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    stmt = (
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .order_by(RunStep.created_at.asc())
    )
    result = await db.execute(stmt)
    steps = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(RunStep.id)).where(RunStep.run_id == run_id)
    )
    total = count_result.scalar() or 0
    return RunStepList(steps=steps, total=total)


@router.get("/runs/{run_id}/events", response_model=AgentEventList)
async def list_run_events(run_id: str, db: AsyncSession = Depends(get_db)):
    run_result = await db.execute(
        select(CollaborationRun.id).where(CollaborationRun.id == run_id)
    )
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    stmt = (
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id)
        .order_by(AgentEvent.created_at.asc())
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(AgentEvent.id)).where(AgentEvent.run_id == run_id)
    )
    total = count_result.scalar() or 0
    return AgentEventList(events=events, total=total)


@router.get("/runs/{run_id}/approvals", response_model=ApprovalRequestList)
async def list_run_approvals(run_id: str, db: AsyncSession = Depends(get_db)):
    run_result = await db.execute(
        select(CollaborationRun.id).where(CollaborationRun.id == run_id)
    )
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    stmt = (
        select(ApprovalRequest)
        .where(ApprovalRequest.run_id == run_id)
        .order_by(ApprovalRequest.created_at.asc())
    )
    result = await db.execute(stmt)
    approvals = list(result.scalars().all())
    count_result = await db.execute(
        select(func.count(ApprovalRequest.id)).where(ApprovalRequest.run_id == run_id)
    )
    total = count_result.scalar() or 0
    return ApprovalRequestList(approvals=approvals, total=total)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRequestResponse)
async def approve_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    resolve_approval(approval, APPROVAL_STATUS_APPROVED)
    await db.flush()
    callbacks = await _build_broadcast_callbacks(approval.room_id)
    await callbacks["on_approval"](approval)
    await db.commit()

    async def _resume_background() -> None:
        async with async_session() as session:
            bg_callbacks = await _build_broadcast_callbacks(approval.room_id)
            await resume_approval_request(
                approval_id,
                session,
                **bg_callbacks,
            )
            await session.commit()

    asyncio.create_task(_resume_background())
    return approval


@router.post("/approvals/{approval_id}/deny", response_model=ApprovalRequestResponse)
async def deny_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    callbacks = await _build_broadcast_callbacks(approval.room_id)
    denied = await deny_approval_request(
        approval_id,
        db,
        on_run_update=callbacks["on_run_update"],
        on_event=callbacks["on_event"],
        on_approval=callbacks["on_approval"],
    )
    return denied
