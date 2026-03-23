import re

from app.models.agent import AgentConfig

MENTION_PATTERN = re.compile(r"@(\w+)")
LINE_HANDOFF_PATTERN = re.compile(r"(?m)^\s*@(\w+)\b")
LINE_HANDOFF_WITH_REQUEST_PATTERN = re.compile(r"^\s*@(\w+)\b(.*)$")
REVIEW_DIRECTIVE_PATTERN = re.compile(r"#review-by=([a-zA-Z0-9_, -]+)")
HANDOFF_DIRECTIVE_PATTERN = re.compile(r"#handoff=([a-zA-Z0-9_, -]+)")


def extract_mentions(content: str) -> list[str]:
    return [match.lower() for match in MENTION_PATTERN.findall(content)]


def _extract_directive_targets(content: str, pattern: re.Pattern[str]) -> list[str]:
    match = pattern.search(content)
    if not match:
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for raw_target in match.group(1).split(","):
        target = raw_target.strip().lower()
        if target and target not in seen:
            targets.append(target)
            seen.add(target)
    return targets


def extract_agent_handoff_targets(content: str) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    for target in LINE_HANDOFF_PATTERN.findall(content):
        lowered = target.lower()
        if lowered not in seen:
            targets.append(lowered)
            seen.add(lowered)

    for target in _extract_directive_targets(content, HANDOFF_DIRECTIVE_PATTERN):
        if target not in seen:
            targets.append(target)
            seen.add(target)

    return targets


def extract_agent_handoff_request(content: str) -> str:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        handoff_match = LINE_HANDOFF_WITH_REQUEST_PATTERN.match(line)
        if handoff_match:
            inline_request = handoff_match.group(2).strip()
            if inline_request:
                return inline_request

            trailing_request = "\n".join(lines[index + 1 :]).strip()
            if trailing_request:
                return trailing_request
            break

        directive_match = HANDOFF_DIRECTIVE_PATTERN.fullmatch(line.strip())
        if directive_match:
            trailing_request = "\n".join(lines[index + 1 :]).strip()
            if trailing_request:
                return trailing_request
            break

    return re.sub(r"[ \t]{2,}", " ", strip_control_syntax(content)).strip()


def extract_referenced_agent_names(
    content: str,
    enabled_agents: list[AgentConfig],
) -> list[str]:
    lowered = content.lower()
    referenced: list[str] = []
    seen: set[str] = set()

    for agent in enabled_agents:
        name = agent.name.lower()
        display_name = agent.display_name.lower()
        if (
            name in lowered
            or display_name in lowered
            or f"@{name}" in lowered
        ) and name not in seen:
            referenced.append(name)
            seen.add(name)

    return referenced


def strip_mentions(content: str) -> str:
    return MENTION_PATTERN.sub("", content).strip()


def extract_review_targets(content: str) -> list[str]:
    return _extract_directive_targets(content, REVIEW_DIRECTIVE_PATTERN)


def strip_review_directives(content: str) -> str:
    return REVIEW_DIRECTIVE_PATTERN.sub("", content).strip()


def strip_handoff_directives(content: str) -> str:
    return HANDOFF_DIRECTIVE_PATTERN.sub("", content).strip()


def strip_control_syntax(content: str) -> str:
    return strip_mentions(
        strip_handoff_directives(strip_review_directives(content))
    ).strip()
