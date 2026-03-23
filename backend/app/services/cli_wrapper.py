"""Base class for CLI agent wrappers.

Each agent type (Claude, Codex, etc.) subclasses CLIAgent and implements
`build_command()` and `parse_output()`.
"""

import asyncio
import json
import logging
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
STREAM_FALLBACK_CHUNK_SIZE = 80
STREAM_FALLBACK_DELAY_S = 0.02


class CLIAgent(ABC):
    """Base class for spawning CLI agents as subprocesses."""

    def __init__(
        self,
        command: str,
        timeout: int = 300,
        model: str | None = None,
        reasoning_effort: str | None = None,
        permission_mode: str = "acceptEdits",
        allowed_tools: str | None = None,
        system_prompt: str | None = None,
        default_args: str | None = None,
    ):
        self.command = command
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt
        self.default_args = default_args
        self._last_session_id: str | None = None

    @property
    def last_session_id(self) -> str | None:
        return self._last_session_id

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

    def build_stream_preview(self, raw: str) -> str | None:
        """Build a user-visible preview from partial raw output.

        Return None when a provider does not support meaningful live previews.
        """
        return None

    def get_default_args(self) -> list[str]:
        """Parse persisted default args from JSON or shell-style text."""
        if not self.default_args:
            return []

        raw = self.default_args.strip()
        if not raw:
            return []

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, list):
            return [str(item) for item in parsed]

        if isinstance(parsed, str):
            raw = parsed
        elif parsed is not None:
            logger.warning("Ignoring unsupported default_args value: %r", parsed)
            return []

        try:
            return shlex.split(raw, posix=not IS_WINDOWS)
        except ValueError:
            logger.warning("Falling back to a single CLI argument for default_args: %s", raw)
            return [raw]

    def _prepare_command(
        self,
        message: str,
        session_id: str | None = None,
    ) -> tuple[list[str], bytes | None]:
        cmd = self.build_command(message, session_id)
        stdin_data: bytes | None = None
        if "\n" in message and IS_WINDOWS:
            cmd = cmd[:-1]
            stdin_data = message.encode("utf-8")
        return cmd, stdin_data

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

    async def _write_stdin(
        self,
        process: asyncio.subprocess.Process,
        stdin_data: bytes | None,
    ) -> None:
        """Write prompt data to stdin for providers that read from a pipe."""
        if not stdin_data or process.stdin is None:
            return

        process.stdin.write(stdin_data)
        await process.stdin.drain()
        process.stdin.close()
        try:
            await process.stdin.wait_closed()
        except (AttributeError, BrokenPipeError):
            pass

    async def send(self, message: str, session_id: str | None = None) -> str:
        """Spawn the CLI subprocess, pipe the message, and return the response."""
        cmd, stdin_data = self._prepare_command(message, session_id)
        logger.info(f"Spawning agent: {' '.join(cmd[:3])}...")

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
        cmd, stdin_data = self._prepare_command(message, session_id)
        logger.info(f"Spawning agent (streaming): {' '.join(cmd[:3])}...")

        process = await self._spawn(cmd, stdin_data)

        try:
            await self._write_stdin(process, stdin_data)
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

    async def send_with_stream(
        self,
        message: str,
        on_update: Callable[[str], Awaitable[None]],
        session_id: str | None = None,
    ) -> str:
        """Spawn the CLI subprocess and stream cleaned output when possible."""
        cmd, stdin_data = self._prepare_command(message, session_id)
        logger.info(f"Spawning agent (stream+final): {' '.join(cmd[:3])}...")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        preview = ""

        process = await self._spawn(cmd, stdin_data)

        async def read_stdout() -> None:
            nonlocal preview
            assert process.stdout is not None
            while True:
                chunk = await asyncio.wait_for(
                    process.stdout.read(512), timeout=self.timeout
                )
                if not chunk:
                    break

                stdout_parts.append(chunk.decode("utf-8", errors="replace"))
                candidate = self.build_stream_preview("".join(stdout_parts))
                if candidate is not None and candidate != preview:
                    preview = candidate
                    await on_update(preview)

        async def read_stderr() -> None:
            assert process.stderr is not None
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                stderr_parts.append(chunk.decode("utf-8", errors="replace"))

        try:
            await asyncio.gather(
                self._write_stdin(process, stdin_data),
                read_stdout(),
                read_stderr(),
            )
            await process.wait()

            stdout_text = "".join(stdout_parts).strip()
            stderr_text = "".join(stderr_parts).strip()

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
            if result and preview != result:
                start = len(preview) if result.startswith(preview) else 0
                for end in range(
                    max(start + STREAM_FALLBACK_CHUNK_SIZE, 1),
                    len(result) + STREAM_FALLBACK_CHUNK_SIZE,
                    STREAM_FALLBACK_CHUNK_SIZE,
                ):
                    await on_update(result[: min(end, len(result))])
                    if end < len(result):
                        await asyncio.sleep(STREAM_FALLBACK_DELAY_S)

            logger.info(f"Agent responded ({len(result)} chars)")
            return result

        except asyncio.TimeoutError:
            logger.error(f"Agent timed out after {self.timeout}s")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(
                f"Agent did not respond within {self.timeout} seconds"
            )
