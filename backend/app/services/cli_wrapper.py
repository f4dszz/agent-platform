"""Base class for CLI agent wrappers.

Each agent type (Claude, Codex, etc.) subclasses CLIAgent and implements
`build_command()` and `parse_output()`.
"""

import asyncio
import logging
import subprocess
import sys
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


class CLIAgent(ABC):
    """Base class for spawning CLI agents as subprocesses."""

    def __init__(
        self,
        command: str,
        timeout: int = 300,
        permission_mode: str = "acceptEdits",
        allowed_tools: str | None = None,
        system_prompt: str | None = None,
    ):
        self.command = command
        self.timeout = timeout
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt

    @abstractmethod
    def build_command(self, message: str, session_id: str | None = None) -> list[str]:
        """Build the full command + args list for subprocess.

        Returns (cmd_args, stdin_text): cmd_args is the command without the
        message, stdin_text is the prompt to pipe via stdin.  Subclasses may
        return the message as the last element of cmd_args for backward compat,
        but the base send() will pop it and use stdin instead when the message
        contains newlines (e.g. chat history).
        """
        ...

    @abstractmethod
    def parse_output(self, raw: str) -> str:
        """Parse the raw stdout from the CLI into a clean response."""
        ...

    async def _spawn(self, cmd: list[str], stdin_data: bytes | None = None):
        """Spawn a subprocess, handling Windows shell requirements."""
        if IS_WINDOWS:
            cmd_str = subprocess.list2cmdline(cmd)
            logger.info(f"Windows shell command: {cmd_str[:200]}")
            return await asyncio.create_subprocess_shell(
                cmd_str,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            return await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    async def send(self, message: str, session_id: str | None = None) -> str:
        """Spawn the CLI subprocess, pipe the message, and return the response."""
        cmd = self.build_command(message, session_id)
        logger.info(f"Spawning agent: {' '.join(cmd[:3])}...")

        # On Windows, multiline prompts get truncated by cmd.exe shell quoting.
        # Use stdin to pass the prompt instead of a command-line argument.
        # Both `claude -p` and `codex exec` read from stdin when no prompt arg given.
        stdin_data: bytes | None = None
        if "\n" in message and IS_WINDOWS:
            # Remove the message from cmd args (it's the last element)
            cmd = cmd[:-1]
            stdin_data = message.encode("utf-8")

        try:
            process = await self._spawn(cmd, stdin_data)

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=stdin_data), timeout=self.timeout
            )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                logger.error(
                    f"Agent exited with code {process.returncode}: {stderr_text}"
                )
                raise RuntimeError(
                    f"Agent process failed (exit code {process.returncode}): "
                    f"{stderr_text or stdout_text}"
                )

            if stderr_text:
                logger.warning(f"Agent stderr: {stderr_text}")

            result = self.parse_output(stdout_text)
            logger.info(f"Agent responded ({len(result)} chars)")
            return result

        except asyncio.TimeoutError:
            logger.error(f"Agent timed out after {self.timeout}s")
            try:
                process.kill()  # type: ignore[possibly-undefined]
            except ProcessLookupError:
                pass
            raise TimeoutError(
                f"Agent did not respond within {self.timeout} seconds"
            )

    async def send_streaming(
        self, message: str, session_id: str | None = None
    ):
        """Spawn the CLI subprocess and yield output chunks as they arrive."""
        cmd = self.build_command(message, session_id)
        logger.info(f"Spawning agent (streaming): {' '.join(cmd[:3])}...")

        process = await self._spawn(cmd)

        try:
            assert process.stdout is not None
            while True:
                chunk = await asyncio.wait_for(
                    process.stdout.read(4096), timeout=self.timeout
                )
                if not chunk:
                    break
                yield chunk.decode("utf-8", errors="replace")

            await process.wait()
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(
                f"Agent did not respond within {self.timeout} seconds"
            )
