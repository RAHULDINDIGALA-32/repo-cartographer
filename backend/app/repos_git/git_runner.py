from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.config.settings import Settings
from app.core.errors import RepoFetchError

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GitResult:
    stdout: bytes
    stderr: bytes
    returncode: int


class GitRunner:
    """Single hardened async subprocess gateway for every git operation."""

    def __init__(self, settings: Settings, *, allow_file_protocol: bool = False):
        self.settings = settings
        self.allow_file_protocol = allow_file_protocol
        self._semaphore = asyncio.Semaphore(settings.git_max_concurrency)
        self._hooks_dir = Path(tempfile.gettempdir()) / "repo-cartographer-empty-hooks"
        self._hooks_dir.mkdir(parents=True, exist_ok=True)

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": os.devnull,
                "SSH_ASKPASS": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_ALLOW_PROTOCOL": "file:https" if self.allow_file_protocol else "https",
            }
        )
        return env

    def _args(self, args: Sequence[str]) -> list[str]:
        protocol = "always" if self.allow_file_protocol else "never"
        return [
            "git",
            "-c",
            f"core.hooksPath={self._hooks_dir}",
            "-c",
            "submodule.recurse=false",
            "-c",
            f"protocol.file.allow={protocol}",
            *args,
        ]

    async def run(
        self, args: Sequence[str], *, cwd: Path | None = None, timeout: int | None = None
    ) -> GitResult:
        command = self._args(args)
        limit = timeout or self.settings.git_timeout_seconds
        async with self._semaphore:
            try:
                if sys.platform == "win32":
                    completed = await asyncio.to_thread(
                        subprocess.run,
                        command,
                        cwd=str(cwd) if cwd else None,
                        env=self._environment(),
                        capture_output=True,
                        timeout=limit,
                        check=False,
                    )
                    stdout, stderr, returncode = (
                        completed.stdout,
                        completed.stderr,
                        completed.returncode,
                    )
                else:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=str(cwd) if cwd else None,
                        env=self._environment(),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=limit)
                    returncode = process.returncode
            except subprocess.TimeoutExpired as exc:
                raise RepoFetchError(
                    "Git operation timed out", details={"retryable": True}
                ) from exc
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise RepoFetchError(
                    "Git operation timed out", details={"retryable": True}
                ) from exc
            except OSError as exc:
                raise RepoFetchError(
                    "Git is unavailable or could not start", details={"retryable": True}
                ) from exc
        max_output = 1_000_000
        stdout, stderr = stdout[:max_output], stderr[:max_output]
        if stderr:
            log.debug(
                "git_stderr", command=command[1:], stderr=stderr.decode("utf-8", "replace")[:2000]
            )
        if returncode != 0:
            text = stderr.decode("utf-8", "replace").lower()
            if any(
                x in text
                for x in (
                    "not found",
                    "could not read",
                    "repository does not exist",
                    "authentication",
                )
            ):
                message = "Repository not found or private"
            elif "empty repository" in text:
                message = "Repository is empty"
            elif "no space" in text or "disk full" in text:
                message = "Insufficient disk space for repository"
            else:
                message = "Git operation failed"
            raise RepoFetchError(message, details={"retryable": True, "returncode": returncode})
        return GitResult(stdout, stderr, returncode)
