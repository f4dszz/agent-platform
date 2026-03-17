# Agent Platform

A multi-agent chat platform where humans and CLI-based AI agents (Claude Code, Codex CLI, etc.) communicate in a shared chat room via web/mobile.

## Tech Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** Python + FastAPI
- **Database:** PostgreSQL
- **Real-time:** WebSocket
- **CLI Agents:** Claude Code (`claude -p`), Codex CLI (`codex`)

## Quick Start

### 1. Start PostgreSQL

```bash
docker-compose up -d
```

### 2. Start the backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env  # adjust settings as needed
uvicorn app.main:app --reload
```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Use the app

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

## Project Structure

```
agent-platform/
├── frontend/                     # React + Vite + TypeScript
│   └── src/
│       ├── components/           # ChatRoom, MessageList, MessageInput, etc.
│       ├── hooks/                # useWebSocket
│       ├── services/             # REST API client
│       └── types/                # Shared TypeScript types
├── backend/                      # Python + FastAPI
│   └── app/
│       ├── main.py               # App entry, CORS, lifespan
│       ├── config.py             # Pydantic Settings
│       ├── models/               # SQLAlchemy ORM (Room, Message, AgentConfig)
│       ├── schemas/              # Pydantic request/response schemas
│       ├── services/             # Orchestrator, CLI wrappers, session manager
│       ├── routers/              # REST endpoints (rooms, messages, agents)
│       ├── ws/                   # WebSocket handler
│       └── db/                   # Async SQLAlchemy engine
├── docker-compose.yml            # PostgreSQL service
└── .env.example                  # Environment template
```
