from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.db.database import engine, async_session, Base
from app.models import AgentConfig
from app.routers import rooms, messages, agents
from app.ws.handler import router as ws_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default agents to seed on first startup
DEFAULT_AGENTS = [
    {
        "name": "claude",
        "display_name": "Claude Code",
        "agent_type": "claude",
        "command": "claude",
        "max_timeout": 300,
        "permission_mode": "acceptEdits",
        "allowed_tools": None,
        "system_prompt": None,
    },
    {
        "name": "codex",
        "display_name": "Codex CLI",
        "agent_type": "codex",
        "command": "codex",
        "max_timeout": 300,
        "permission_mode": "acceptEdits",
        "allowed_tools": None,
        "system_prompt": None,
    },
]


async def seed_agents():
    """Register default agents if they don't exist yet."""
    async with async_session() as db:
        for agent_data in DEFAULT_AGENTS:
            result = await db.execute(
                select(AgentConfig).where(AgentConfig.name == agent_data["name"])
            )
            if not result.scalar_one_or_none():
                agent = AgentConfig(**agent_data)
                db.add(agent)
                logger.info(f"Seeded agent: {agent_data['name']}")
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: create tables (dev convenience — use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed default agents
    await seed_agents()
    logger.info("Agent Platform started")
    yield
    # Shutdown: dispose engine
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title="Agent Platform",
    description="Multi-agent chat platform for humans and CLI-based AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(rooms.router, prefix="/api/rooms", tags=["rooms"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])

# WebSocket router
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
