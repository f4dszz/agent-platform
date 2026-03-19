from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.agent_artifact import AgentArtifact
from app.models.collaboration_run import CollaborationRun
from app.models.room import Room
from app.schemas.schemas import (
    AgentArtifactList,
    CollaborationRunList,
    CollaborationRunResponse,
)

router = APIRouter()


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
