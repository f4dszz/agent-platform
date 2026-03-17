# Agent Platform

A multi-agent chat platform where humans and CLI-based AI agents (Claude Code, Codex CLI, etc.) communicate in a shared chat room via web/mobile.

多 Agent 聊天平台：人类与 CLI AI 代理（Claude Code、Codex CLI 等）在共享聊天室中实时对话。

## Tech Stack / 技术栈

- **Frontend 前端:** React + Vite + TypeScript + Tailwind CSS
- **Backend 后端:** Python + FastAPI
- **Database 数据库:** SQLite (dev) / PostgreSQL (prod)
- **Real-time 实时通信:** WebSocket
- **CLI Agents 代理:** Claude Code (`claude -p`), Codex CLI (`codex`)

## Quick Start / 快速启动

### 1. Start the backend / 启动后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

> Note / 注意: Use `python -m uvicorn` (not bare `uvicorn`) to ensure the correct Python version. Do NOT use `--reload` on Windows — it causes zombie worker processes.
>
> 使用 `python -m uvicorn`（而非直接 `uvicorn`）确保正确的 Python 版本。Windows 上不要用 `--reload`，会导致僵尸子进程堆叠。

### 2. Start the frontend / 启动前端

```bash
cd frontend
bun install   # or npm install / 或 npm install
npx vite --port 5173
```

### 3. Use the app / 使用应用

1. Open / 打开 http://localhost:5173
2. Create a room / 创建聊天室
3. Type a message — it appears in real time / 输入消息——实时显示
4. Type `@claude hello` — Claude Code CLI responds / 输入 `@claude hello`——Claude Code 回复
5. Type `@codex hello` — Codex CLI responds / 输入 `@codex hello`——Codex CLI 回复
6. Type `@all summarize this file` — both agents respond / 输入 `@all`——所有代理回复

## Message Routing / 消息路由

| Syntax 语法 | Behavior 行为 |
|--------|----------|
| `@claude <msg>` | Send to Claude Code only / 仅发送给 Claude Code |
| `@codex <msg>` | Send to Codex CLI only / 仅发送给 Codex CLI |
| `@all <msg>` | Send to all enabled agents / 发送给所有启用的代理 |
| No mention 无 @ | Human chat — no agent auto-reply / 人类聊天，代理不自动回复 |

## Agent Configuration / Agent 配置

Each agent has configurable settings editable from the sidebar:

每个 Agent 可在侧边栏中配置以下设置：

- **Permission Mode / 权限模式**: Controls what the agent is allowed to do / 控制代理的操作权限
  - `acceptEdits` — Allow file edits (recommended) / 允许编辑文件（推荐）
  - `plan` — Plan only, no file operations / 仅规划，不操作文件
  - `default` — Require confirmation (non-interactive = reject) / 需要确认（非交互=拒绝）
  - `bypassPermissions` — Skip all checks (dangerous) / 跳过所有权限检查（危险）
- **Allowed Tools / 允许的工具** (Claude only): Restrict which tools the agent can use (Read, Write, Edit, Bash, Glob, Grep) / 限制可用工具
- **System Prompt / 人格提示词**: Inject a persona/role / 注入人格角色（如 "你是代码审核员..."）

Settings are persisted to the database via `PATCH /api/agents/{name}`.

设置通过 `PATCH /api/agents/{name}` 持久化到数据库。

## Project Structure / 项目结构

```
agent-platform/
├── frontend/                     # React + Vite + TypeScript
│   └── src/
│       ├── components/           # ChatRoom, MessageList, MessageInput, AgentSettings...
│       ├── hooks/                # useWebSocket
│       ├── services/             # REST API client / REST API 客户端
│       └── types/                # Shared TypeScript types / 共享 TS 类型
├── backend/                      # Python + FastAPI
│   └── app/
│       ├── main.py               # App entry, CORS, lifespan, seed agents / 应用入口
│       ├── config.py             # Pydantic Settings / 配置
│       ├── models/               # SQLAlchemy ORM (Room, Message, AgentConfig)
│       ├── schemas/              # Pydantic request/response schemas / 请求响应模型
│       ├── services/             # Orchestrator, CLI wrappers, session manager / 编排器
│       ├── routers/              # REST endpoints (rooms, messages, agents)
│       ├── ws/                   # WebSocket handler / WebSocket 处理器
│       └── db/                   # Async SQLAlchemy engine / 异步数据库引擎
├── docker-compose.yml            # PostgreSQL service (prod) / 生产数据库
└── .env.example                  # Environment template / 环境变量模板
```
