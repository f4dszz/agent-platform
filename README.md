# Agent Platform

A shared-room collaboration platform for humans and CLI agents such as Claude
Code and Codex CLI.

## Stack

- Frontend: React, Vite, TypeScript, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, SQLite for local development
- Realtime: WebSocket
- Agents: Claude Code CLI and Codex CLI

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Use `python -m uvicorn` rather than bare `uvicorn`. On Windows, avoid
`--reload` because it tends to leave zombie worker processes behind.

### Frontend

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

### App

1. Open `http://127.0.0.1:5173`
2. Create a room
3. Send a human message or mention an agent such as `@claude` or `@codex`

## Message Routing

| Syntax | Behavior |
| --- | --- |
| `@claude <msg>` | Send only to Claude Code |
| `@codex <msg>` | Send only to Codex CLI |
| `@all <msg>` | Send to all enabled agents |
| no mention | Human-only chat, no automatic agent reply |

## Agent Settings

Agent settings are provider-aware and loaded from
`GET /api/agents/{name}/capabilities`.

Shared settings:

- `Enabled`
- `Display Name`
- `Model`
- `Reasoning / Thinking` when supported
- `Execution`
- `Timeout`
- `System Prompt`, `Default Args`, and `Command` under Advanced

Claude Code support:

- Suggested models: `sonnet`, `opus`
- These aliases are described as the latest Sonnet 4.6 and Opus 4.6 family
- Thinking levels map to `claude --effort` with `low`, `medium`, `high`, `max`
- Tool rules are provider-native and are passed through as `--allowedTools`

Codex support:

- Suggested models come from local Codex config when available
- `gpt-5.4` is the default fallback recommendation
- Reasoning levels map to `-c model_reasoning_effort=...`
- Execution stays coarse because Codex CLI does not expose the same fine-grained
  provider approval surface as Claude Code

Settings are persisted through `PATCH /api/agents/{name}`.

## Collaboration Runs

The collaboration layer currently distinguishes between:

- `deliverable` tasks such as plans, implementation work, and documents
- `content_iteration` tasks such as jokes, naming, rewriting, and copywriting

This prevents every multi-agent request from being forced into the same
`plan -> review -> decision` flow.

Current run model highlights:

- lead-agent execution with reviewer follow-up
- approval pause and resume
- structured artifacts, steps, events, and approvals
- run timelines in the frontend

## Room Lifecycle

- Room create and delete events are broadcast through `/ws/lifecycle/rooms`
- Sidebar room lists stay in sync across clients
- Batch deletion is available at `POST /api/rooms/batch-delete`

## Project Structure

```text
agent-platform/
|-- frontend/
|   |-- src/
|   |   |-- components/
|   |   |-- hooks/
|   |   |-- services/
|   |   `-- types/
|-- backend/
|   |-- app/
|   |   |-- db/
|   |   |-- models/
|   |   |-- routers/
|   |   |-- schemas/
|   |   |-- services/
|   |   `-- ws/
|   `-- tests/
|-- docker-compose.yml
`-- README.md
```

## Notable Service Boundaries

- `agent_capabilities.py`: provider-aware configuration metadata for the UI
- `agent_execution.py`: provider invocation and session persistence
- `step_execution.py`: single-step lifecycle, approval gating, and artifact persistence
- `orchestrator.py`: run-level routing and collaboration loops
- `prompt_builder.py`: prompt construction
- `message_parser.py`: mention, handoff, and control syntax parsing
- `run_hooks.py`: callback bundling for responses, streams, steps, and approvals

## Current Limitations

- Claude and Codex are not yet wired to provider-native event streams in the UI
- Step/event logging is still coarse compared with a full debugging console
- `orchestrator.py` has been reduced substantially but still carries run-level
  workflow logic that can be split further
