from __future__ import annotations

import httpx

from app.core.errors import RepoFetchError, RepoTooLargeError
from app.models import RemoteInfo, RepoRef


async def get_remote_info(runner, clone_url: str) -> RemoteInfo:
    result = await runner.run(["ls-remote", "--symref", clone_url, "HEAD"])
    lines = result.stdout.decode("utf-8", "replace").splitlines()
    head_sha = None
    branch = "HEAD"
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "ref:" and parts[2] == "HEAD":
            branch = parts[1].removeprefix("refs/heads/")
        elif len(parts) >= 2 and parts[1] == "HEAD":
            head_sha = parts[0]
    if not head_sha:
        raise RepoFetchError("Repository is empty")
    return RemoteInfo(default_branch=branch, head_sha=head_sha)


async def estimate_remote_size_mb(ref: RepoRef, settings) -> float | None:
    """Best-effort GitHub size lookup; API failures intentionally become unknown."""
    headers = {"Accept": "application/vnd.github+json"}
    token = settings.github_token.get_secret_value()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=settings.git_timeout_seconds) as client:
            response = await client.get(
                f"https://api.github.com/repos/{ref.owner}/{ref.name}", headers=headers
            )
            response.raise_for_status()
            size_kb = response.json().get("size")
            if not isinstance(size_kb, (int, float)):
                return None
            size_mb = float(size_kb) / 1024
            if size_mb > settings.max_remote_repo_size_mb:
                raise RepoTooLargeError(
                    "Remote repository exceeds the configured size limit",
                    details={"size_mb": size_mb, "limit_mb": settings.max_remote_repo_size_mb},
                )
            return size_mb
    except RepoTooLargeError:
        raise
    except Exception:
        return None
