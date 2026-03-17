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

    def __init__(self, command: str, timeout: int = 300):
        self.command = command
        self.timeout = timeout

    @abstractmethod
    def build_command(self, message: str, session_id: str | None = None) -> list[str]:
        """Build the full command + args list for subprocess."""
        ...

    @abstractmethod
    def parse_output(self, raw: str) -> str:
        """Parse the raw stdout from the CLI into a clean response."""
        ...

    async def _spawn(self, cmd: list[str]):
        """Spawn a subprocess, handling Windows shell requirements."""
        if IS_WINDOWS:
            # On Windows, npm-installed CLIs are .cmd scripts that need shell
            cmd_str = subprocess.list2cmdline(cmd)
            logger.info(f"Windows shell command: {cmd_str[:200]}")
            return await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            return await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    async def send(self, message: str, session_id: str | None = None) -> str:
        """Spawn the CLI subprocess, pipe the message, and return the response."""
        cmd = self.build_command(message, session_id)
        logger.info(f"Spawning agent: {' '.join(cmd[:3])}...")

        try:
            process = await self._spawn(cmd)

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
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
