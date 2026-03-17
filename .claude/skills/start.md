---
name: start
description: Quick start the Agent Platform locally (backend + frontend). Handles port conflicts, Python version issues, and npm fallbacks automatically.
user_invocable: true
---

# Agent Platform — Local Quick Start

You are starting the Agent Platform development environment. Follow these steps precisely.

## Pre-flight Checks

1. Check if port 8001 is free (8000 is often occupied on this machine):
```bash
netstat -ano | grep ":8001" | grep LISTEN
```
If occupied, kill the process or pick another port.

2. Verify CLIs are available:
```bash
which claude && which codex && python --version
```

## Start Backend

IMPORTANT: Always use `python -m uvicorn`, NOT bare `uvicorn` (Python version mismatch issue).

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Run this in the background, then verify:
```bash
curl -s http://127.0.0.1:8001/health
```
Expected: `{"status":"ok"}`

On first startup, the backend automatically:
- Creates SQLite database (`agent_platform.db`)
- Creates all tables (rooms, messages, agent_configs)
- Seeds default agents (claude, codex)

## Start Frontend

```bash
cd frontend
```

If `node_modules/` doesn't exist, install dependencies. Prefer **bun** (npm often has network issues on this machine):
```bash
bun install
```
Fallback: `npm install`

Then start the dev server:
```bash
bun run dev
```
Or: `npm run dev`

Verify frontend proxy works:
```bash
curl -s http://localhost:5173/api/agents/
```
Should return the list of registered agents.

## Verify End-to-End

Open http://localhost:5173 in the browser. The user should see:
- Left sidebar with rooms list and agent status indicators
- Main area with chat
- Input bar at the bottom

Quick smoke test via WebSocket (optional CLI test):
```python
import asyncio, json, websockets
async def test():
    # First create a room via REST
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:8001/api/rooms/",
        data=json.dumps({"name":"test"}).encode(), headers={"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    room_id = resp["id"]

    async with websockets.connect(f"ws://127.0.0.1:8001/ws/{room_id}") as ws:
        await ws.send(json.dumps({"type":"chat","sender_name":"User","content":"@claude hello"}))
        for _ in range(5):
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if data["type"] == "chat" and data.get("sender_type") == "claude":
                print("Claude responded:", data["content"][:100])
                break
asyncio.run(test())
```

## Known Pitfalls (Windows)

- **Port 8000 occupied** → use 8001, update `vite.config.ts` proxy if changed
- **`uvicorn` uses wrong Python** → always `python -m uvicorn`
- **npm ECONNRESET** → use `bun install` instead
- **CLI [WinError 2]** → already fixed: uses `create_subprocess_shell` on Windows
- **`--allowedTools` breaks prompt** → already removed from default claude command
- **Codex CLI** → uses `codex exec` subcommand, not `codex --quiet`

## Ports Summary

| Service  | Port |
|----------|------|
| Backend  | 8001 |
| Frontend | 5173 |
| DB       | SQLite (file, no port) |
