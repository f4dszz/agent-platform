from dataclasses import dataclass
import re

from app.models.agent import AgentConfig

REVIEW_HINT_PATTERN = re.compile(
    r"(review|critic|audit|inspect|check|评审|审核|评价|检查|复核|review一下|review this)",
    re.IGNORECASE,
)
LOOP_HINT_PATTERN = re.compile(
    r"(until|iterate|loop|re-review|再根据.*修改|根据.*评价.*修改|根据.*评审.*修改|直到|反复|来回|没有分歧|达成一致)",
    re.IGNORECASE,
)
WRITE_HINT_PATTERN = re.compile(
    r"(\b(?:implement|edit|write|fix|refactor|patch|code)\b|修改|实现|重构|修复|编写|落地|完成代码)",
    re.IGNORECASE,
)
DANGEROUS_HINT_PATTERN = re.compile(
    r"(\b(?:install|remove|deploy|apt|brew)\b|npm install|pnpm install|pip install|删除|rm\s|git push|发布)",
    re.IGNORECASE,
)
PLAN_HINT_PATTERN = re.compile(
    r"(plan|proposal|design|architecture|方案|计划|设计|架构|文档|报告)",
    re.IGNORECASE,
)
CONTENT_HINT_PATTERN = re.compile(
    r"(joke|funny|caption|tagline|slogan|headline|copy|rewrite|polish|name|poem|story|tweet|笑话|段子|文案|标题|取名|润色|改写|更好笑)",
    re.IGNORECASE,
)
# e.g. "review 3 rounds", "最多5轮", "iterate up to 4 times", "3次review"
ROUND_LIMIT_PATTERN = re.compile(
    r"(?:(\d+)\s*(?:轮|次|rounds?|times?|iterations?))|(?:(?:最多|up\s+to|at\s+most|max(?:imum)?)\s*(\d+))|(?:(\d+)\s*(?:轮|次))",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CollaborationIntent:
    mode: str
    review_targets: list[str]
    wants_revision_loop: bool
    require_decision: bool
    required_permission_mode: str | None
    task_kind: str
    primary_artifact_type: str | None
    decision_style: str
    max_review_rounds: int | None
    max_steps: int | None


def extract_referenced_reviewers(
    raw_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
) -> list[str]:
    # Only escalate natural-language reviewer mentions into an automatic review chain
    # when the user also implies an iterative loop.
    if not LOOP_HINT_PATTERN.search(raw_content):
        return []

    lowered = raw_content.lower()
    primary_names = {agent.name.lower() for agent in primary_targets}
    referenced: list[str] = []
    seen: set[str] = set()
    for agent in enabled_agents:
        name = agent.name.lower()
        if name in primary_names or name in seen:
            continue
        display_name = agent.display_name.lower()
        if name in lowered or display_name in lowered or f"@{name}" in lowered:
            referenced.append(name)
            seen.add(name)
    return referenced


def infer_required_permission_mode(raw_content: str) -> str | None:
    if DANGEROUS_HINT_PATTERN.search(raw_content):
        return "bypassPermissions"
    if WRITE_HINT_PATTERN.search(raw_content):
        return "acceptEdits"
    return None


def infer_task_kind(raw_content: str) -> str:
    if CONTENT_HINT_PATTERN.search(raw_content):
        return "content_iteration"
    return "deliverable"


def extract_round_limit(raw_content: str) -> int | None:
    """Extract an explicit round/iteration limit from user text."""
    m = ROUND_LIMIT_PATTERN.search(raw_content)
    if not m:
        return None
    raw_num = m.group(1) or m.group(2) or m.group(3)
    if raw_num:
        n = int(raw_num)
        # Clamp to reasonable range
        return max(1, min(n, 20))
    return None


def infer_primary_artifact_type(
    raw_content: str,
    *,
    task_kind: str,
    required_permission_mode: str | None,
) -> str | None:
    if task_kind == "content_iteration":
        return "content"
    if PLAN_HINT_PATTERN.search(raw_content):
        return "plan"
    if required_permission_mode:
        return "solution"
    return "plan"


def build_collaboration_intent(
    raw_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
    explicit_review_targets: list[str],
) -> CollaborationIntent:
    review_targets = explicit_review_targets or extract_referenced_reviewers(
        raw_content,
        enabled_agents,
        primary_targets,
    )
    wants_revision_loop = bool(review_targets) and bool(LOOP_HINT_PATTERN.search(raw_content))
    required_permission_mode = infer_required_permission_mode(raw_content)
    task_kind = infer_task_kind(raw_content)
    round_limit = extract_round_limit(raw_content)
    primary_artifact_type = infer_primary_artifact_type(
        raw_content,
        task_kind=task_kind,
        required_permission_mode=required_permission_mode,
    )

    if task_kind == "content_iteration":
        if review_targets and wants_revision_loop:
            mode = "content_review_loop"
        elif review_targets:
            mode = "content_review"
        else:
            mode = "content"
        decision_style = "owner_confirmation" if review_targets else "none"
    elif review_targets and wants_revision_loop and required_permission_mode:
        mode = "implement_review_loop"
        decision_style = "readiness"
    elif review_targets and wants_revision_loop:
        mode = "plan_review_loop"
        decision_style = "readiness"
    elif review_targets:
        mode = "plan_review"
        decision_style = "readiness"
    else:
        mode = "custom"
        decision_style = "none"

    return CollaborationIntent(
        mode=mode,
        review_targets=review_targets,
        wants_revision_loop=wants_revision_loop,
        require_decision=decision_style != "none",
        required_permission_mode=required_permission_mode,
        task_kind=task_kind,
        primary_artifact_type=primary_artifact_type,
        decision_style=decision_style,
        max_review_rounds=round_limit,
        max_steps=round_limit * 3 if round_limit else None,
    )
