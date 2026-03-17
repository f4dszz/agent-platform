from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.agent import AgentConfig
from app.schemas.schemas import AgentRegister, AgentResponse, AgentStatusResponse

router = APIRouter()


@router.post("/", response_model=AgentResponse, status_code=201)
async def register_agent(body: AgentRegister, db: AsyncSession = Depends(get_db)):
    """Register a new CLI agent."""
    # Check for duplicate name
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == body.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already registered")

    agent = AgentConfig(
        name=body.name,
        display_name=body.display_name,
        agent_type=body.agent_type,
        command=body.command,
        default_args=body.default_args,
        max_timeout=body.max_timeout,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/", response_model=list[AgentResponse])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """List all registered agents."""
    result = await db.execute(select(AgentConfig).order_by(AgentConfig.name))
    return list(result.scalars().all())


@router.get("/{agent_name}", response_model=AgentResponse)
async def get_agent(agent_name: str, db: AsyncSession = Depends(get_db)):
    """Get a specific agent by name."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == agent_name)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/{agent_name}/status", response_model=AgentStatusResponse)
async def get_agent_status(agent_name: str, db: AsyncSession = Depends(get_db)):
    """Get the current status of an agent.

    Status is determined by the session manager at runtime.
    """
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == agent_name)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Import here to avoid circular imports
    from app.services.session_manager import session_manager

    session = session_manager.get_session(agent_name)
    status = "idle"
    session_id = None
    message_count = 0

    if session:
        status = "working" if session.get("busy") else "idle"
        session_id = session.get("session_id")
        message_count = session.get("message_count", 0)

    if not agent.enabled:
        status = "offline"

    return AgentStatusResponse(
        name=agent.name,
        display_name=agent.display_name,
        status=status,
        current_session_id=session_id,
        message_count=message_count,
    )


@router.patch("/{agent_name}/toggle", response_model=AgentResponse)
async def toggle_agent(agent_name: str, db: AsyncSession = Depends(get_db)):
    """Enable or disable an agent."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == agent_name)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.enabled = not agent.enabled
    await db.flush()
    await db.refresh(agent)
    return agent
