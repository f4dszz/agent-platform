# 方向调整：AI Task Runner with Human Oversight

> 日期：2026-03-23
> 状态：初步方案，待验证

## 1. 为什么要调整方向

### 1.1 原方向的根本问题

原方向是"让原生 CLI agent（Claude Code, Codex）在聊天室里协作"。

技术上已实现了 collaboration kernel（run 状态机、artifact 提取、approval 流、handoff 语义），但遇到了两个无法回避的根本问题：

**问题一：CLI agent 是客户端工具，不是可编程的 headless agent。**

调用 `claude -p` 和 `codex exec` 本质上是套壳。无法控制 agent 的内部状态、上下文窗口、工具调用策略。能传入的只有一段 prompt，拿回来的只有一段文本。这不是真正的 agent 协作，是 orchestrated prompting with extra steps。

**问题二："多 agent 协作优于单 agent"这个前提未被验证。**

- Claude Code 自己就能 plan → code → review → fix
- 让另一个 agent 去 review，并不比让同一个 agent 自己 review 更好——因为 review 质量取决于模型能力，不取决于"另一个人在看"这种人类直觉
- 人类团队需要协作是因为单人知识和时间有限。LLM 没有这个限制

### 1.2 如果转 API-based multi-agent platform

直觉上的替代方案是放弃 CLI，改用 Claude API / Agent SDK 直接调 agent。但这会进入一个极其拥挤的赛道：

- CrewAI — 已融资，社区大，Python 原生
- AutoGen — 微软背书
- LangGraph — LangChain 生态
- Dify / Coze — 可视化编排
- Anthropic Agent SDK — 官方出品

一个人的项目去和这些竞争，没有胜算。而且整个 multi-agent 赛道本身都有一个未被验证的前提——大多数产品 demo 很炫，实际 token 消耗翻 3-5 倍，输出质量并不稳定优于 single agent + good prompt。

### 1.3 现有代码中真正有价值的部分

不应该全盘否定已有工作。以下模块具有独立价值：

1. **CollaborationRun 状态机** — 结构化的任务执行生命周期
2. **Approval / Permission Gating** — 人在关键节点审批
3. **AgentArtifact 提取和追踪** — 结构化的执行产物
4. **Agent-agnostic execution layer** — CLI wrapper 抽象
5. **WebSocket 实时基础设施** — 完整的实时通信层

这些代码在新方向下可以 80%+ 复用。

## 2. 新方向：AI Task Runner with Human Oversight

### 2.1 一句话定义

**让开发者把复杂任务交给 AI 执行，但保留结构化的审批和控制权。**

### 2.2 核心洞察

现在很多团队想用 AI agent 做事，但不敢放手——因为 agent 会乱改代码、乱删文件、执行危险操作。

"我想用 AI 但我需要控制权" 这个需求是真实存在的，而且目前没有好的产品解决它。

现有产品的定位对比：

| | Cursor / Windsurf | CrewAI / AutoGen | 本项目新方向 |
|---|---|---|---|
| 核心模型 | 内嵌编辑器 | 全自动 pipeline | 结构化审批流 |
| 人的角色 | 实时对话 | 旁观者 | 每步审批者 |
| 适合场景 | 写代码 | demo / 实验 | 生产环境中的谨慎使用 |
| 信任假设 | 高信任 | 完全信任 | 低信任 / 可控 |

### 2.3 核心场景

用户提交一个复杂任务，例如："重构这个模块的认证逻辑"

系统执行流程：
1. AI 分解任务为 plan → implement → review → test 步骤
2. 每个关键节点暂停，等人确认
3. 展示结构化的 artifact（plan 文档、代码 diff、test 结果）
4. 人可以在任何节点 reject / revise / approve
5. 执行完成后有完整的审计记录

### 2.4 关键差异化

**不强调"多 agent"，强调"人对 AI 执行的结构化控制"。**

Agent 数量是 1 个还是 3 个不重要。重要的是 oversight layer 做得比别人好。

## 3. 已有代码的复用映射

| 已有模块 | 新方向中的用途 | 改动量 |
|---|---|---|
| CollaborationRun | → TaskRun（任务执行生命周期） | 重命名 + 简化 mode |
| RunStep | → TaskStep（不变） | 基本不变 |
| AgentArtifact | → StepArtifact（每步的产出物） | 基本不变 |
| ApprovalRequest | → 核心差异化功能，不变 | 不变 |
| collaboration_policy.py | → execution_policy.py | 微调停止条件 |
| artifact_extractor.py | → 不变 | 不变 |
| prompt_builder.py | → 调整为单 agent 优先 | 简化 |
| orchestrator.py | → task_executor.py | 去掉 multi-agent routing，聚焦单 agent 步骤控制 |
| step_execution.py | → 不变 | 不变 |
| approval gating | → 核心卖点 | 增强 UI |
| WebSocket 实时通信 | → 不变 | 不变 |
| 前端 RunTimeline | → TaskTimeline | 增强可视化 |
| 前端 ApprovalUI | → 核心交互 | 增强 |

## 4. 初步技术方案

### 4.1 执行层调整

**Phase 1：保留 CLI wrapper，同时支持 API 调用。**

不需要一次性切换。先保留 `claude -p` 作为执行后端，同时新增 Claude API / Agent SDK 作为第二个 provider。用户按需选择。

```
ExecutionProvider (interface)
├── CLIProvider (现有 claude -p / codex exec)
└── APIProvider (新增 Claude API / Agent SDK)
```

这样老用户不受影响，新方向的核心价值在 oversight 层而不在 provider 层。

### 4.2 任务模型

简化现有的 collaboration run 模型，去掉"多 agent 协作"语义，聚焦"任务执行 + 审批"：

```
TaskRun
├── goal: 用户的任务描述
├── workspace: 工作目录
├── steps: TaskStep[]
│   ├── type: plan | implement | review | test | custom
│   ├── status: pending | running | needs_approval | approved | rejected | completed
│   ├── artifacts: StepArtifact[]
│   └── approval: ApprovalRequest?
├── policy: ExecutionPolicy
│   ├── auto_approve: string[]  (哪些步骤类型可以自动通过)
│   ├── require_approval: string[]  (哪些步骤必须人工审批)
│   ├── max_steps: int
│   └── max_revisions: int
└── status: running | paused | completed | failed
```

### 4.3 审批层增强

这是核心差异化，需要比现在做得更好：

1. **分级审批策略**
   - 只读操作（搜索、分析）→ 自动通过
   - 文件修改 → 展示 diff，等待审批
   - 危险操作（删除、执行脚本）→ 强制审批 + 警告

2. **审批 UI**
   - 不只是 approve/reject 按钮
   - 展示每步的 artifact（plan 文档、代码 diff、测试结果）
   - 支持 inline 批注（"这里改一下再跑"）
   - 支持 partial approve（"前三个文件通过，第四个拒绝"）

3. **审计追踪**
   - 完整的执行日志
   - 每步 token 消耗
   - 审批决策记录
   - 可回放的执行时间线

### 4.4 前端重构方向

从"聊天室"转为"任务面板 + 执行时间线"：

```
┌─────────────┬──────────────────────────────────┐
│ Task List   │  Task: 重构认证模块               │
│             │                                    │
│ ● 重构认证  │  Step 1: Plan          ✅ Approved │
│ ○ 优化查询  │  ┗ artifact: plan.md               │
│ ○ 添加测试  │                                    │
│             │  Step 2: Implement  ⏸ Needs Review │
│             │  ┗ artifact: diff (3 files)         │
│             │  ┗ [Approve] [Reject] [Revise]      │
│             │                                    │
│             │  Step 3: Test           ⏳ Pending  │
│             │                                    │
│             │──────────────────────────────────  │
│             │  💬 Chat with AI about this task   │
│             │  > _                                │
└─────────────┴──────────────────────────────────┘
```

聊天不消失，但从"主界面"变成"任务内的辅助对话"。

## 5. 实施路线

### Phase 0：验证（1-2 周）

不写新代码。用现有系统跑几个真实任务：
- 一次代码重构
- 一次 bug 修复
- 一次新功能开发

记录：
- 人在哪些节点想要暂停审核？
- 审核时需要看到什么信息？
- 现有 approval 系统够用吗？差在哪？

**如果验证结论是"人其实不需要中间审批，直接看最终结果就够了"，那这个方向也不成立，需要再调整。**

### Phase 1：核心改造（2-3 周）

- 把 CollaborationRun 重构为 TaskRun
- 简化 orchestrator，去掉 multi-agent routing
- 新增 API-based execution provider
- 审批 UI 增强（diff 展示、inline 批注）

### Phase 2：前端重构（2-3 周）

- 从聊天室 UI 转为任务面板 UI
- 执行时间线可视化
- 审批交互增强

### Phase 3：生产化（2-4 周）

- Auth（至少 API key 级别）
- PostgreSQL
- 部署方案
- 文档和 onboarding

## 6. 风险

1. **"人不需要中间审批"的风险**
   - 如果开发者习惯了直接信任 AI 输出，那 oversight 层没有价值
   - 对策：Phase 0 验证，不要跳过

2. **"做出来了但没人用"的风险**
   - 单人项目最大的风险不是技术，是没有用户
   - 对策：Phase 1 完成后就发布，尽早收集真实反馈

3. **"和 IDE 集成竞争"的风险**
   - Cursor、Windsurf 等 IDE 内置了 AI agent + 审批
   - 对策：不做 IDE 插件，做独立的 task runner，面向 CI/CD 场景或团队协作场景

4. **过度重构的风险**
   - 已有代码大部分可复用，不要为了"方向调整"而重写
   - 对策：渐进式改造，保持系统随时可运行

## 7. 开放问题

以下问题需要在 Phase 0 验证中回答：

1. 目标用户到底是个人开发者还是团队？
2. 审批的粒度应该多细？每个文件？每个步骤？每个任务？
3. 是否需要支持多种 AI provider（Claude, GPT, Gemini）还是只聚焦 Claude？
4. 长期来看，是否回到 multi-agent？还是坚持 single-agent + human oversight？
