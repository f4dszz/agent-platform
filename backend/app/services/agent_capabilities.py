import logging
from pathlib import Path
import tomllib

from app.models.agent import AgentConfig
from app.schemas.schemas import AgentCapabilitiesResponse, AgentConfigOption

logger = logging.getLogger(__name__)


def _dedupe_options(options: list[AgentConfigOption]) -> list[AgentConfigOption]:
    seen: set[str] = set()
    deduped: list[AgentConfigOption] = []
    for option in options:
        if option.value in seen:
            continue
        seen.add(option.value)
        deduped.append(option)
    return deduped


def _load_codex_config() -> dict:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return {}

    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Failed to read Codex config from %s: %s", config_path, exc)
        return {}


def _codex_model_options() -> list[AgentConfigOption]:
    config = _load_codex_config()
    options: list[AgentConfigOption] = []

    model = config.get("model")
    if isinstance(model, str) and model.strip():
        options.append(
            AgentConfigOption(
                value=model.strip(),
                label=model.strip(),
                description="Current local Codex default",
            )
        )

    notice = config.get("notice")
    if isinstance(notice, dict):
        migrations = notice.get("model_migrations")
        if isinstance(migrations, dict):
            for target in migrations.values():
                if isinstance(target, str) and target.strip():
                    options.append(
                        AgentConfigOption(
                            value=target.strip(),
                            label=target.strip(),
                            description="Available from local migration hints",
                        )
                    )

    if not options:
        options.append(
            AgentConfigOption(
                value="gpt-5.4",
                label="gpt-5.4",
                description="Current recommended Codex model",
            )
        )

    return _dedupe_options(options)


def get_agent_capabilities(agent: AgentConfig) -> AgentCapabilitiesResponse:
    if agent.agent_type == "claude":
        execution_options = [
            AgentConfigOption(
                value="plan",
                label="Plan Only",
                description="Read-only analysis and planning",
            ),
            AgentConfigOption(
                value="acceptEdits",
                label="Implement",
                description="Let Claude Code edit files when needed",
            ),
            AgentConfigOption(
                value="bypassPermissions",
                label="Full Access",
                description="Skip Claude Code permission prompts",
            ),
        ]
        if agent.permission_mode == "default":
            execution_options.append(
                AgentConfigOption(
                    value="default",
                    label="Provider Default",
                    description="Use Claude Code's default permission behavior",
                )
            )

        return AgentCapabilitiesResponse(
            agent_name=agent.name,
            agent_type=agent.agent_type,
            model_placeholder="sonnet, opus, or a full Claude model id",
            model_help="Claude Code supports aliases for the latest Sonnet 4.6 and Opus 4.6 models.",
            model_options=[
                AgentConfigOption(
                    value="sonnet",
                    label="Sonnet 4.6",
                    description="Alias for the latest Claude Sonnet 4.6",
                ),
                AgentConfigOption(
                    value="opus",
                    label="Opus 4.6",
                    description="Alias for the latest Claude Opus 4.6",
                ),
            ],
            reasoning_supported=True,
            reasoning_label="Thinking",
            reasoning_help="Claude Code maps this directly to --effort.",
            reasoning_options=[
                AgentConfigOption(
                    value="low",
                    label="Low",
                    description="Fastest, lighter reasoning",
                ),
                AgentConfigOption(
                    value="medium",
                    label="Medium",
                    description="Balanced default",
                ),
                AgentConfigOption(
                    value="high",
                    label="High",
                    description="More deliberate reasoning",
                ),
                AgentConfigOption(
                    value="max",
                    label="Max",
                    description="Deepest Claude Code effort level",
                ),
            ],
            execution_label="Execution",
            execution_help="This controls Claude Code's own permission mode when the platform runs it.",
            execution_options=execution_options,
            tool_rules_supported=True,
            tool_rules_label="Tool Rules",
            tool_rules_help="Provider-native allow list passed to Claude Code as --allowedTools.",
            tool_rules_placeholder='Examples: "Read Edit Bash(git:*)" or leave blank for provider default',
            advanced_fields=["system_prompt", "allowed_tools", "default_args", "command", "avatar"],
        )

    execution_options = [
        AgentConfigOption(
            value="plan",
            label="Read Only",
            description="Codex exec uses read-only sandboxing",
        ),
        AgentConfigOption(
            value="acceptEdits",
            label="Workspace Write",
            description="Codex exec uses --full-auto in the workspace sandbox",
        ),
        AgentConfigOption(
            value="bypassPermissions",
            label="Full Access",
            description="Codex exec bypasses sandboxing and approvals",
        ),
    ]
    if agent.permission_mode == "default":
        execution_options.append(
            AgentConfigOption(
                value="default",
                label="Provider Default",
                description="Use Codex CLI defaults without extra execution flags",
            )
        )

    return AgentCapabilitiesResponse(
        agent_name=agent.name,
        agent_type=agent.agent_type,
        model_placeholder="gpt-5.4 or another Codex-capable model id",
        model_help="Suggestions come from the local Codex config when available.",
        model_options=_codex_model_options(),
        reasoning_supported=True,
        reasoning_label="Reasoning",
        reasoning_help="Codex exec receives this via -c model_reasoning_effort=...",
        reasoning_options=[
            AgentConfigOption(
                value="low",
                label="Low",
                description="Fastest, lighter reasoning",
            ),
            AgentConfigOption(
                value="medium",
                label="Medium",
                description="Balanced default",
            ),
            AgentConfigOption(
                value="high",
                label="High",
                description="More deliberate reasoning",
            ),
            AgentConfigOption(
                value="xhigh",
                label="Max",
                description="Deepest Codex reasoning tier",
            ),
        ],
        execution_label="Execution",
        execution_help="Codex exec does not expose per-command approval policy, so this stays coarse.",
        execution_options=execution_options,
        tool_rules_supported=False,
        advanced_fields=["system_prompt", "default_args", "command", "avatar"],
    )
