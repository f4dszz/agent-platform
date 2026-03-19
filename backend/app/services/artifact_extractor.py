from dataclasses import dataclass
import re


ARTIFACT_DIRECTIVE_PATTERN = re.compile(r"(?mi)^\s*#artifact=([a-z_]+)\s*$")
STATUS_DIRECTIVE_PATTERN = re.compile(r"(?mi)^\s*#status=([a-z_]+)\s*$")
EXPECTS_DIRECTIVE_PATTERN = re.compile(r"(?mi)^\s*#expects=([a-z_]+)\s*$")
HANDOFF_DIRECTIVE_PATTERN = re.compile(r"(?mi)^\s*#handoff=([a-z0-9_, -]+)\s*$")
CONTROL_LINE_PATTERN = re.compile(r"(?mi)^\s*#(?:artifact|status|expects|handoff)=.*$")
MAX_ARTIFACT_TITLE_LENGTH = 120


@dataclass(slots=True)
class ExtractedArtifact:
    clean_content: str
    artifact_type: str | None
    status: str | None
    expects: str | None
    handoff_targets: list[str]
    title: str | None


def _extract_targets(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    targets: list[str] = []
    seen: set[str] = set()
    for raw_target in raw_value.split(","):
        target = raw_target.strip().lower()
        if target and target not in seen:
            targets.append(target)
            seen.add(target)
    return targets


def _build_title(clean_content: str) -> str | None:
    for line in clean_content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        normalized = " ".join(stripped.split())
        if len(normalized) <= MAX_ARTIFACT_TITLE_LENGTH:
            return normalized
        return normalized[: MAX_ARTIFACT_TITLE_LENGTH - 3].rstrip() + "..."
    return None


def extract_artifact(
    raw_content: str,
    *,
    default_artifact_type: str | None = None,
    default_status: str | None = None,
) -> ExtractedArtifact:
    artifact_match = ARTIFACT_DIRECTIVE_PATTERN.search(raw_content)
    status_match = STATUS_DIRECTIVE_PATTERN.search(raw_content)
    expects_match = EXPECTS_DIRECTIVE_PATTERN.search(raw_content)
    handoff_match = HANDOFF_DIRECTIVE_PATTERN.search(raw_content)

    clean_content = CONTROL_LINE_PATTERN.sub("", raw_content)
    clean_content = re.sub(r"\n{3,}", "\n\n", clean_content).strip()

    artifact_type = (
        artifact_match.group(1).strip().lower()
        if artifact_match
        else default_artifact_type
    )
    status = (
        status_match.group(1).strip().lower()
        if status_match
        else default_status
    )
    expects = expects_match.group(1).strip().lower() if expects_match else None
    handoff_targets = _extract_targets(handoff_match.group(1) if handoff_match else None)
    title = _build_title(clean_content)

    if not artifact_type and handoff_targets:
        artifact_type = "handoff"

    return ExtractedArtifact(
        clean_content=clean_content or raw_content.strip(),
        artifact_type=artifact_type,
        status=status,
        expects=expects,
        handoff_targets=handoff_targets,
        title=title,
    )
