"""Claude Code CLI agent wrapper.

Uses `claude -p` for single-shot prompts with optional session continuity.
"""

import json
import logging

from app.services.cli_wrapper import CLIAgent

logger = logging.getLogger(__name__)


class ClaudeAgent(CLIAgent):
    """Wrapper for Claude Code CLI (`claude -p`)."""

    def __init__(self, command: str = "claude", timeout: int = 300, **kwargs):
        super().__init__(command=command, timeout=timeout, **kwargs)

    def build_command(self, message: str, session_id: str | None = None) -> list[str]:
        """Build the claude CLI command.

        Example:
            claude -p --output-format json --permission-mode acceptEdits "fix the bug"
        """
        cmd = [
            self.command,
            "-p",
            "--output-format", "json",
        ]

        # Permission mode
        if self.permission_mode == "bypassPermissions":
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd.extend(["--permission-mode", self.permission_mode])

        # Allowed tools
        if self.allowed_tools:
            cmd.extend(["--allowedTools", self.allowed_tools])

        # System prompt
        if self.system_prompt:
            cmd.extend(["--append-system-prompt", self.system_prompt])

        if session_id:
            cmd.extend(["--session-id", session_id])

        cmd.append(message)

        return cmd

    def parse_output(self, raw: str) -> str:
        """Parse Claude's JSON output format.

        Real output looks like:
        {"type":"result","subtype":"success","is_error":false,
         "result":"Hello!","session_id":"...","duration_ms":...}
        """
        if not raw:
            return "(no response)"

        try:
            data = json.loads(raw)

            if isinstance(data, dict):
                # Store session_id for reuse
                if "session_id" in data:
                    self._last_session_id = data["session_id"]

                # Check for errors
                if data.get("is_error"):
                    return f"⚠️ Agent error: {data.get('result', 'unknown error')}"

                if "result" in data:
                    return str(data["result"])

                return json.dumps(data, indent=2)

        except json.JSONDecodeError:
            logger.debug("Claude output is not JSON, returning raw text")

        return raw
