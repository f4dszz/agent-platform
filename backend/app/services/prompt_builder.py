import asyncio
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.message import Message
from app.services.agent_memory_store import build_agent_memory_context
from app.services.message_parser import extract_referenced_agent_names

REPO_ROOT = Path(__file__).resolve().parents[3]

PLATFORM_AGENT_SYSTEM_PROMPT = """
You are one AI agent participating in a shared multi-agent room.

Rules for collaboration:
- Do not try to invoke other local CLIs, subprocesses, terminals, or tools to contact another agent.
- Do not ask the human for permission to run another agent on your behalf.
- If another agent should continue, emit a handoff instruction instead of trying to call it yourself.
- Preferred handoff format:
  #handoff=<agent-name>
  <the exact request for that agent>
- When your output is intended to be reused by another agent, prefer adding:
  #artifact=plan|review|decision|todo|summary
- Review outputs should also include:
  #status=approved|revise|blocked
- Final decision outputs should also include:
  #status=completed|blocked|revise
- You may also use a single new line like:
  @codex review the plan above
- Normal inline mentions inside prose should be avoided unless you intend a handoff.
- Keep your own answer for the human separate from the handoff request for the next agent.
""".strip()


def build_primary_step_prompt(
    original_request: str,
    *,
    reviewer_names: list[str],
    task_kind: str,
    artifact_type: str | None,
) -> str:
    reviewer_label = ", ".join(reviewer_names) if reviewer_names else "the reviewer"
    lines = ["Platform step contract:"]

    if task_kind == "content_iteration":
        lines.extend(
            [
                "You are the lead agent for the current content step only.",
                "Produce the actual first version of the requested content now.",
                "Do not describe a workflow, protocol, or collaboration plan.",
                "Do not simulate the reviewer, future rounds, or final agreement.",
                f"The platform will send your output to {reviewer_label} after this step.",
                "Return the content itself, not meta commentary about the process.",
            ]
        )
    else:
        lines.extend(
            [
                "You are the lead agent for the current step only.",
                "Produce the best first-pass draft or solution for the user's request now.",
                "Do not describe the collaboration workflow.",
                "Do not simulate reviewer feedback, later revision rounds, or final approval.",
                "If the full request mentions later export, file generation, or follow-up actions, ignore those later stages for now unless they are strictly required to produce the current draft.",
                f"The platform will send your output to {reviewer_label} after this step.",
                "Return the deliverable itself, not a plan about the process.",
            ]
        )

    if artifact_type:
        lines.append(f"Begin your reply with `#artifact={artifact_type}`.")

    lines.extend(
        [
            "",
            "Original user request:",
            original_request,
        ]
    )
    return "\n".join(lines)


async def build_prompt_with_history(
    db: AsyncSession,
    room_id: str,
    agent_name: str,
    current_content: str,
    current_message_id: str,
    include_current_message_in_history: bool = False,
    max_messages: int = 20,
) -> str:
    stmt = (
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    if not include_current_message_in_history:
        stmt = stmt.where(Message.id != current_message_id)
    result = await db.execute(stmt)
    history = list(result.scalars().all())
    history.reverse()

    memory_context = await build_agent_memory_context(
        db,
        room_id,
        agent_name,
        max_messages,
    )

    if not history:
        if not memory_context:
            return current_content
        return "\n".join(
            [
                "Below is the persistent long-term memory for this room.",
                "",
                memory_context,
                "",
                f"Now respond to this request: {current_content}",
            ]
        )

    lines = [
        "Below is the conversation history from a shared chat room. Multiple users and AI agents participate. Read the history for context, then respond ONLY to the current request at the end.",
        "",
    ]
    if memory_context:
        lines.extend(
            [
                "--- LONG-TERM MEMORY ---",
                memory_context,
                "--- END LONG-TERM MEMORY ---",
                "",
            ]
        )
    lines.append("--- CONVERSATION HISTORY ---")
    for msg in history:
        lines.append(f"[{msg.sender_name}]: {msg.content}")
    lines.append("--- END HISTORY ---")
    lines.append("")
    lines.append(f"Now respond to this request: {current_content}")

    return "\n".join(lines)


def get_git_context() -> str:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() or "(detached HEAD)"
    except Exception:
        return "Git branch information unavailable."

    try:
        status_output = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        status_output = ""

    lines = [f"Current git branch: {branch}."]
    if status_output:
        changed = status_output.splitlines()[:10]
        lines.append("Working tree status:")
        lines.extend(changed)
        if len(status_output.splitlines()) > len(changed):
            lines.append("...")
    else:
        lines.append("Working tree status: clean.")

    return "\n".join(lines)


async def build_review_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    primary_response: str,
    git_context: str | None = None,
    *,
    task_kind: str = "deliverable",
) -> str:
    if task_kind == "content_iteration":
        return "\n".join(
            [
                "You are reviewing another AI agent's latest content draft.",
                "Judge the content itself against the user's request.",
                "Do not discuss git, files, branches, tooling, or the collaboration protocol.",
                "Return your result using this protocol:",
                "#artifact=review",
                "#status=approved|revise|blocked",
                "",
                f"Original user request:\n{original_request}",
                "",
                f"{primary_agent.display_name}'s latest content:\n{primary_response}",
                "",
                "Return a concise review with:",
                "1. Verdict",
                "2. Brief critique",
                "3. Improved version if revision is needed",
            ]
        )

    if git_context is None:
        git_context = await asyncio.to_thread(get_git_context)
    return "\n".join(
        [
            "You are reviewing another AI agent's proposed plan or output.",
            "Focus on risks, missing steps, branch-related concerns, and concrete corrections.",
            "Do not rewrite everything from scratch unless the original plan is fundamentally broken.",
            "Return your review using this protocol:",
            "#artifact=review",
            "#status=approved|revise|blocked",
            "",
            git_context,
            "",
            f"Original user request:\n{original_request}",
            "",
            f"{primary_agent.display_name} plan or output to review:\n{primary_response}",
            "",
            "Return a concise review with:",
            "1. Major risks",
            "2. Missing considerations",
            "3. Branch / workspace cautions",
            "4. Final recommendation",
        ]
    )


async def build_decision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    plan_text: str,
    review_texts: list[str],
) -> str:
    review_block = "\n\n".join(
        f"Review {index + 1}:\n{text}" for index, text in enumerate(review_texts)
    )
    return "\n".join(
        [
            "You are making the final decision for a multi-agent collaboration run.",
            "Read your original plan and the review feedback, then decide whether the work is ready.",
            "Return your result using this protocol:",
            "#artifact=decision",
            "#status=completed|blocked|revise",
            "",
            f"Original user request:\n{original_request}",
            "",
            f"Your original plan:\n{plan_text}",
            "",
            f"Review feedback:\n{review_block}",
            "",
            "Return a concise final decision with:",
            "1. Decision",
            "2. Reasoning",
            "3. Next action",
        ]
    )


async def build_revision_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    previous_output: str,
    review_texts: list[str],
    *,
    task_kind: str = "deliverable",
    artifact_type: str = "plan",
) -> str:
    review_block = "\n\n".join(
        f"Review {index + 1}:\n{text}" for index, text in enumerate(review_texts)
    )
    if task_kind == "content_iteration":
        return "\n".join(
            [
                f"You are {primary_agent.display_name}. Revise the latest content using the review feedback.",
                "Return the next content version itself, not a workflow description.",
                "Return the revised output using this protocol:",
                f"#artifact={artifact_type}",
                "",
                f"Original user request:\n{original_request}",
                "",
                f"Current content:\n{previous_output}",
                "",
                f"Review feedback:\n{review_block}",
                "",
                "Return a stronger revised version that directly addresses the review comments.",
            ]
        )

    return "\n".join(
        [
            f"You are {primary_agent.display_name}. Revise your previous output using the review feedback.",
            "Keep the strongest parts of the current solution and change only what the review requires.",
            "Return the revised output using this protocol:",
            f"#artifact={artifact_type}",
            "",
            f"Original user request:\n{original_request}",
            "",
            f"Previous output:\n{previous_output}",
            "",
            f"Review feedback:\n{review_block}",
            "",
            "Return a revised, reusable result that directly addresses the review comments.",
        ]
    )


async def build_owner_confirmation_prompt(
    original_request: str,
    primary_agent: AgentConfig,
    latest_output: str,
    review_texts: list[str],
) -> str:
    review_block = "\n\n".join(
        f"Review {index + 1}:\n{text}" for index, text in enumerate(review_texts)
    )
    return "\n".join(
        [
            f"You are {primary_agent.display_name}. The reviewer approved or commented on the latest content.",
            "Evaluate the current content itself, not the workflow.",
            "If you also agree the current version satisfies the user request, keep it and mark it approved.",
            "If you still disagree, revise the content and mark it revise.",
            "Return your result using this protocol:",
            "#artifact=content",
            "#status=approved|revise|blocked",
            "",
            f"Original user request:\n{original_request}",
            "",
            f"Latest content:\n{latest_output}",
            "",
            f"Reviewer feedback:\n{review_block}",
            "",
            "Return:",
            "1. Verdict",
            "2. Final content",
        ]
    )


def build_human_collaboration_hint(
    message_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
    review_targets: list[str],
) -> str:
    if len(primary_targets) != 1:
        return ""

    referenced_agents = extract_referenced_agent_names(message_content, enabled_agents)
    primary_names = {target.name.lower() for target in primary_targets}
    collaborator_names = [
        name
        for name in referenced_agents
        if name not in primary_names and name not in review_targets
    ]
    if not collaborator_names:
        return ""

    collaborator_list = ", ".join(collaborator_names)
    preferred_target = collaborator_names[0]
    return "\n".join(
        [
            "",
            "Platform instruction:",
            (
                "The user also referenced these agents for possible follow-up: "
                f"{collaborator_list}."
            ),
            (
                "If you want one of them to continue, do not claim you need permission "
                "and do not try to run their CLI yourself."
            ),
            (
                f"Instead, end your reply with an explicit handoff such as "
                f"`#handoff={preferred_target}` followed by the exact request for that agent."
            ),
        ]
    )
