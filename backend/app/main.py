from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.db.database import Base, async_session, engine
from app.models import AgentConfig
from app.routers import agents, collaboration, messages, rooms
from app.ws.handler import router as ws_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SQLITE_AGENT_CONFIG_COLUMNS = {
    "default_args": "TEXT",
    "max_timeout": "INTEGER NOT NULL DEFAULT 300",
    "permission_mode": "VARCHAR(30) NOT NULL DEFAULT 'acceptEdits'",
    "allowed_tools": "TEXT",
    "system_prompt": "TEXT",
    "model": "VARCHAR(120)",
    "avatar_label": "VARCHAR(8)",
    "avatar_color": "VARCHAR(40)",
}

# Default agents to seed on first startup
DEFAULT_AGENTS = [
    {
        "name": "claude",
        "display_name": "Claude Code",
        "agent_type": "claude",
        "command": "claude",
        "model": None,
        "max_timeout": 300,
        "permission_mode": "acceptEdits",
        "allowed_tools": None,
        "avatar_label": "C",
        "avatar_color": "#f59e0b",
        "system_prompt": None,
    },
    {
        "name": "codex",
        "display_name": "Codex CLI",
        "agent_type": "codex",
        "command": "codex",
        "model": None,
        "max_timeout": 300,
        "permission_mode": "acceptEdits",
        "allowed_tools": None,
        "avatar_label": "X",
        "avatar_color": "#10b981",
        "system_prompt": None,
    },
]


async def seed_agents() -> None:
    """Register default agents if they don't exist yet."""
    async with async_session() as db:
        for agent_data in DEFAULT_AGENTS:
            result = await db.execute(
                select(AgentConfig).where(AgentConfig.name == agent_data["name"])
            )
            agent = result.scalar_one_or_none()
            if not agent:
                db.add(AgentConfig(**agent_data))
                logger.info("Seeded agent: %s", agent_data["name"])
                continue

            updated = False
            for field, value in agent_data.items():
                if getattr(agent, field, None) is None and value is not None:
                    setattr(agent, field, value)
                    updated = True
            if updated:
                logger.info("Backfilled agent defaults for: %s", agent.name)
        await db.commit()


async def ensure_sqlite_schema() -> None:
    """Add newly introduced columns for local SQLite databases."""
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return

    async with engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(agent_configs)")
        existing = {row[1] for row in result.fetchall()}

        for column_name, column_ddl in SQLITE_AGENT_CONFIG_COLUMNS.items():
            if column_name in existing:
                continue
            await conn.exec_driver_sql(
                f"ALTER TABLE agent_configs ADD COLUMN {column_name} {column_ddl}"
            )
            logger.info("Added SQLite column agent_configs.%s", column_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_sqlite_schema()
    await seed_agents()
    logger.info("Agent Platform started")
    yield
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title="Agent Platform",
    description="Multi-agent chat platform for humans and CLI-based AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rooms.router, prefix="/api/rooms", tags=["rooms"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(
    collaboration.router, prefix="/api/collaboration", tags=["collaboration"]
)

app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
