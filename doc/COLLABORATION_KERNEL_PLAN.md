# Collaboration Kernel Plan

目标：把当前聊天室从“能让多个 agent 说话”推进到“能让多个原生 agent 稳定协作”。

当前定位：
- 不做通用 workflow builder
- 不做大而全任务编排平台
- 先做原生 agent 协作台的核心差异化层

## 1. 当前基础

已有：
- room 级 session 隔离
- room + agent 级长记忆
- agent-to-agent handoff
- 双 agent review 链路
- 流式输出、Markdown、长输出折叠

当前缺口：
- handoff 主要还是文本，缺少结构
- agent 输出只有 message，没有工件层
- 没有“这一轮协作”的运行对象
- 没有显式终止条件和停止原因
- UI 只能看消息，不能看协作过程

结论：
下一步不该先加更多 agent，也不该先做大而全工具市场。先把协作内核做出来。

## 2. 核心差异化层的目标

核心差异化层只解决一个问题：

“不同平台的原生 agent，如何在同一个共享工作空间里，稳定地计划、交接、审核、收敛。”

围绕这个目标，内核需要四个能力：

1. 结构化交接
2. 结构化工件
3. 共享工作上下文
4. 协作终止和回放

## 3. 设计原则

1. 聊天室保留，但聊天室只做展示层
2. 先在现有消息流上叠加结构，不推翻现有 UI
3. 先支持最有价值的协作模式：
   - plan -> review
   - implement -> review
   - plan -> review -> decision
4. 先把 Claude/Codex 双 agent 路径做强，再谈更多 agent
5. 每一步都要能独立验证并单独提交

## 4. 内核分层

### 4.1 Collaboration Run

新增一个轻量运行对象，代表“一次协作链路”。

建议模型：
- `CollaborationRun`
  - `id`
  - `room_id`
  - `root_message_id`
  - `initiator_type` (`human` / `agent`)
  - `mode` (`plan_review`, `implement_review`, `custom`)
  - `status` (`running`, `blocked`, `completed`, `stopped`, `failed`)
  - `step_count`
  - `review_round_count`
  - `max_steps`
  - `max_review_rounds`
  - `stop_reason`
  - `created_at`, `updated_at`

作用：
- 给一串消息一个共同上下文
- 控制循环
- 记录停止原因
- 后面做 UI 回放和日志都有抓手

不做的事：
- 暂时不做通用任务系统
- 暂时不引入 DAG/节点编排

### 4.2 Artifact

当前最大问题是 agent 输出只有文本，另一个 agent 很难稳定接。

建议新增：
- `AgentArtifact`
  - `id`
  - `run_id`
  - `room_id`
  - `source_message_id`
  - `agent_name`
  - `artifact_type`
    - `plan`
    - `review`
    - `decision`
    - `todo`
    - `summary`
    - `handoff`
  - `title`
  - `content`
  - `status`
  - `created_at`

第一阶段不要求 agent 输出严格 JSON。
先走“半结构化协议 + 服务器提取”：
- `#artifact=plan`
- `#artifact=review`
- `#handoff=codex`
- `#expects=review`
- `#status=blocked|approved|revise`

如果 agent 没按协议输出，先保底退回普通 message，不让系统崩。

### 4.3 Shared Workspace Context

协作不是共享聊天，而是共享工作上下文。

建议把 prompt 上下文统一分成四段：

1. 长记忆
   - room brief
   - pinned memory
   - room summary

2. 工作区快照
   - 当前分支
   - 工作树状态
   - changed files 摘要

3. 当前 run 的最近工件
   - 最新 plan
   - 最新 review
   - 最新 decision

4. 最近聊天历史

这样 reviewer 不再只靠“看上一条自然语言消息”判断，而是能拿到明确的 plan/review 对象。

### 4.4 Collaboration Policy

这是避免多 agent 失控的关键。

先实现固定策略，不做可视化配置器。

第一阶段策略：
- 每个 run 最多 `max_steps=6`
- review 最多 `max_review_rounds=2`
- 同一个 agent 不连续 self-handoff
- reviewer 默认不再自动 handoff 给第三个 agent
- 一旦出现 `approved` / `blocked` / `completed`，优先结束 run
- 超时、报错、达到最大轮次时写入 `stop_reason`

## 5. 第一阶段要做什么

第一阶段只做一个目标：

“把 `plan -> review -> decision` 做成有结构、可停止、可回看的协作链。”

包含：

1. 后端
- 新增 `CollaborationRun`
- 新增 `AgentArtifact`
- 路由时为用户请求创建 run
- review 链写入 artifact
- handoff 只在 run 内继续，不再只是递归文本消息
- 增加 stop policy

2. prompt / 协议
- 给 agent 明确输出协议
- reviewer 看 plan artifact，而不是只看原始自然语言
- 决策 agent 输出 `decision` artifact

3. 前端
- 聊天室保留
- 在消息气泡上方或下方插入简洁 artifact 卡片
- 增加 run 状态条：
  - 当前模式
  - 第几步
  - 谁在处理
  - 是否 blocked / completed

第一阶段明确不做：
- 通用 task board
- 可拖拽流程图
- 多 run 并行控制台
- MCP 市场
- 复杂权限系统

## 6. 第二阶段

在第一阶段稳定后，再做这些：

### 6.1 Role Presets

不是每个 agent 都平级对话。

增加角色模板：
- `planner`
- `implementer`
- `reviewer`
- `tester`

一个原生 agent 可以绑定不同 role profile。
这样 `@claude` 和 `@codex` 不是单纯名字，而是协作角色。

### 6.2 One-Click Collaboration Modes

在输入框附近增加快捷模式：
- `Plan + Review`
- `Implement + Review`
- `Plan + Review + Decide`

这样用户不需要每次手写控制语法。

### 6.3 Manual Pin / Promote to Memory

把重要 artifact 一键 pin 到 long-term memory。

## 7. 第三阶段

第三阶段再接工程化层和扩展层。

### 工程化层
- auth
- room membership
- logs / tracing
- token / step metrics
- PostgreSQL + migration
- single-instance deployment

### 扩展层
- 更多原生 agent
- MCP 接入
- 共享工具面板
- 外部系统连接

原则：
扩展层必须服务协作内核，而不是转移产品重心。

## 8. 推荐实现顺序

### Slice 1
- `CollaborationRun` 模型
- `AgentArtifact` 模型
- route_message 接入 run
- review 结果结构化落库

### Slice 2
- handoff / artifact 提取器
- stop policy
- run 状态回写

### Slice 3
- run 状态 WebSocket 事件
- 前端 run 状态条
- artifact 卡片展示

### Slice 4
- role preset
- one-click `Plan + Review`

### Slice 5
- artifact pin 到 long memory

## 9. 代码落点

后端大概率新增：
- `backend/app/models/collaboration_run.py`
- `backend/app/models/agent_artifact.py`
- `backend/app/services/collaboration_policy.py`
- `backend/app/services/artifact_extractor.py`
- `backend/app/services/workspace_context.py`

后端修改：
- `backend/app/services/orchestrator.py`
- `backend/app/ws/handler.py`
- `backend/app/schemas/schemas.py`
- `backend/app/main.py`

前端大概率新增：
- `frontend/src/components/ArtifactCard.tsx`
- `frontend/src/components/RunStatusBar.tsx`

前端修改：
- `frontend/src/components/ChatRoom.tsx`
- `frontend/src/components/MessageList.tsx`
- `frontend/src/types/index.ts`
- `frontend/src/services/api.ts`

## 10. 风险

1. 如果协议太重，原生 agent 不稳定遵守
   - 处理：先半结构化，解析失败就退回普通消息

2. 如果一开始就做太多模式，复杂度会爆
   - 处理：第一阶段只做 `plan -> review -> decision`

3. 如果直接做成 task 平台，会偏离当前优势
   - 处理：坚持 room + native agent collaboration，不做通用 builder

## 11. 我建议的下一步

下一步不要继续讨论抽象定位，直接做 `Slice 1`：

1. 建 `CollaborationRun`
2. 建 `AgentArtifact`
3. 把现有双 agent review 链升级为 run + artifact
4. 保持现有聊天室 UI 不破

如果这一步做出来，产品会第一次从“多 agent 聊天”变成“原生 agent 协作系统”。
