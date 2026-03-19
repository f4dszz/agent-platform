"""Codex CLI agent wrapper.

Uses `codex exec` for non-interactive single-shot prompts.
Parses the verbose output to extract the final agent response.
"""

import logging

from app.services.cli_wrapper import CLIAgent

logger = logging.getLogger(__name__)

# Lines from codex output that are metadata / boilerplate
_SKIP_PREFIXES = (
    "OpenAI Codex",
    "--------",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning summaries:",
    "session id:",
    "user",
    "mcp startup:",
    "thinking",
    "tokens used",
)


class CodexAgent(CLIAgent):
    """Wrapper for Codex CLI (`codex exec`)."""

    def __init__(self, command: str = "codex", timeout: int = 300, **kwargs):
        super().__init__(command=command, timeout=timeout, **kwargs)

    # Map platform permission_mode → codex --sandbox value
    _SANDBOX_MAP = {
        "acceptEdits": "workspace-write",
        "bypassPermissions": "danger-full-access",
        "plan": "read-only",
        "default": "read-only",
    }

    def build_command(self, message: str, session_id: str | None = None) -> list[str]:
        """Build the codex CLI command.

        Example:
            codex exec --sandbox workspace-write "say hello"
        """
        # Prepend system prompt to message if set
        prompt = message
        if self.system_prompt:
            prompt = f"{self.system_prompt}\n\n{message}"

        sandbox = self._SANDBOX_MAP.get(self.permission_mode, "read-only")

        cmd = [
            self.command,
            "exec",
            "--sandbox", sandbox,
            prompt,
        ]
        return cmd

    def parse_output(self, raw: str) -> str:
        """Parse Codex exec output.

        Codex exec outputs verbose metadata + the actual response.
        We extract text after the 'codex' marker line, skipping metadata.

        Example output:
            OpenAI Codex v0.114.0 (research preview)
            --------
            workdir: ...
            ...
            user
            say hello in one word
            mcp startup: no servers
            codex
            Hello
            tokens used
            2,328
            Hello
        """
        if not raw:
            return "(no response)"

        lines = raw.strip().splitlines()

        # Strategy: find the last 'codex' marker line, take content between
        # that marker and the 'tokens used' line (or end)
        codex_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "codex":
                codex_idx = i

        if codex_idx is not None:
            # Extract lines after the 'codex' marker
            after = lines[codex_idx + 1 :]
            # Stop at 'tokens used' line
            result_lines = []
            for line in after:
                if line.strip() == "tokens used":
                    break
                result_lines.append(line)

            result = "\n".join(result_lines).strip()
            if result:
                return result

        # Fallback: filter out all known metadata lines
        filtered = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if filtered:
                    filtered.append(line)
                continue
            if any(stripped.startswith(p) for p in _SKIP_PREFIXES):
                continue
            # Skip lines that are just numbers (token counts)
            if stripped.replace(",", "").isdigit():
                continue
            filtered.append(line)

        # Remove trailing empty lines
        while filtered and not filtered[-1].strip():
            filtered.pop()

        return "\n".join(filtered).strip() if filtered else raw.strip()

    def build_stream_preview(self, raw: str) -> str | None:
        """Extract the current assistant response from partial Codex output."""
        if not raw.strip():
            return ""

        lines = raw.splitlines()
        codex_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "codex":
                codex_idx = i

        if codex_idx is None:
            return ""

        preview_lines: list[str] = []
        for line in lines[codex_idx + 1 :]:
            if line.strip() == "tokens used":
                break
            preview_lines.append(line)

        return "\n".join(preview_lines).rstrip()
