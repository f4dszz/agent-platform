# Agent Platform

A multi-agent chat platform where humans and CLI-based AI agents (Claude Code, Codex CLI, etc.) communicate in a shared chat room via web/mobile.

## Tech Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** Python + FastAPI
- **Database:** SQLite (dev) / PostgreSQL (prod)
- **Real-time:** WebSocket
- **CLI Agents:** Claude Code (`claude -p`), Codex CLI (`codex`)

## Quick Start

### 1. Start the backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

> Note: Use `python -m uvicorn` (not bare `uvicorn`) to ensure the correct Python version. Do NOT use `--reload` on Windows — it causes zombie worker processes.

### 2. Start the frontend

```bash
cd frontend
bun install   # or npm install
npx vite --port 5173
```

### 3. Use the app

1. Open http://localhost:5173
2. Create a room
3. Type a message — it appears in real time
4. Type `@claude hello` — Claude Code CLI responds
5. Type `@codex hello` — Codex CLI responds
6. Type `@all summarize this file` — both agents respond sequentially

## Message Routing

| Syntax | Behavior |
|--------|----------|
| `@claude <msg>` | Send to Claude Code only |
| `@codex <msg>` | Send to Codex CLI only |
| `@all <msg>` | Send to all enabled agents (sequentially) |
| No mention | Human chat — no agent auto-reply |

## Agent Configuration

Each agent has configurable settings editable from the sidebar:

- **Permission Mode**: Controls what the agent is allowed to do
  - `acceptEdits` — Allow file edits (recommended)
  - `plan` — Plan only, no file operations
  - `default` — Require confirmation (non-interactive = reject)
  - `bypassPermissions` — Skip all checks (dangerous)
- **Allowed Tools** (Claude only): Restrict which tools the agent can use (Read, Write, Edit, Bash, Glob, Grep)
- **System Prompt**: Inject a persona/role (e.g., "你是代码审核员，专注于代码质量...")

Settings are persisted to the database via `PATCH /api/agents/{name}`.

## Project Structure

```
agent-platform/
├── frontend/                     # React + Vite + TypeScript
│   └── src/
│       ├── components/           # ChatRoom, MessageList, MessageInput, AgentSettings, etc.
│       ├── hooks/                # useWebSocket
│       ├── services/             # REST API client
│       └── types/                # Shared TypeScript types
├── backend/                      # Python + FastAPI
│   └── app/
│       ├── main.py               # App entry, CORS, lifespan, seed agents
│       ├── config.py             # Pydantic Settings
│       ├── models/               # SQLAlchemy ORM (Room, Message, AgentConfig)
│       ├── schemas/              # Pydantic request/response schemas
│       ├── services/             # Orchestrator, CLI wrappers, session manager
│       ├── routers/              # REST endpoints (rooms, messages, agents)
│       ├── ws/                   # WebSocket handler
│       └── db/                   # Async SQLAlchemy engine
├── docker-compose.yml            # PostgreSQL service (prod)
└── .env.example                  # Environment template
```
