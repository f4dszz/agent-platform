from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (SQLite for local dev, PostgreSQL for production)
    database_url: str = "sqlite+aiosqlite:///./agent_platform.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Agent CLI paths
    claude_cli_path: str = "claude"
    codex_cli_path: str = "codex"

    # Agent defaults
    agent_timeout_seconds: int = 300  # 5 minutes max per agent call
    max_session_messages: int = 50  # Rotate session after N messages
    max_session_tokens: int = 80000  # Estimated token limit before rotation

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
