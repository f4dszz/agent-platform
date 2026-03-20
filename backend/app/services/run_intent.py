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
    r"(implement|edit|write|fix|refactor|patch|code|修改|实现|重构|修复|编写|落地|完成代码)",
    re.IGNORECASE,
)
DANGEROUS_HINT_PATTERN = re.compile(
    r"(install|npm install|pnpm install|pip install|apt|brew|删除|remove|rm\s|git push|发布|deploy)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CollaborationIntent:
    mode: str
    review_targets: list[str]
    wants_revision_loop: bool
    require_decision: bool
    required_permission_mode: str | None


def extract_referenced_reviewers(
    raw_content: str,
    enabled_agents: list[AgentConfig],
    primary_targets: list[AgentConfig],
) -> list[str]:
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

    if review_targets and wants_revision_loop and required_permission_mode:
        mode = "implement_review_loop"
    elif review_targets and wants_revision_loop:
        mode = "plan_review_loop"
    elif review_targets:
        mode = "plan_review"
    else:
        mode = "custom"

    return CollaborationIntent(
        mode=mode,
        review_targets=review_targets,
        wants_revision_loop=wants_revision_loop,
        require_decision=bool(review_targets),
        required_permission_mode=required_permission_mode,
    )
