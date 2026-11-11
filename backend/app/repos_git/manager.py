from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import stat
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import structlog

from app.config.pipeline import PipelineConfig
from app.config.settings import Settings
from app.core.errors import (
    ConflictError,
    IndexingError,
    NotFoundError,
    RepoFetchError,
    RepoTooLargeError,
)
from app.models import (
    FetchResult,
    FileEntry,
    RemoteCheck,
    Repo,
    RepoRef,
    RepoRegistration,
    ScanReport,
    SkipSummary,
    SourceFile,
)
from app.repos_git.filter import FileFilter
from app.repos_git.git_runner import GitRunner
from app.repos_git.remote import estimate_remote_size_mb, get_remote_info
from app.repos_git.store import RepoStore

log = structlog.get_logger(__name__)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remove_tree(path: Path) -> None:
    def onerror(function, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=onerror)


class RepoManager:
    def __init__(
        self,
        db,
        settings: Settings,
        pipeline: PipelineConfig | None = None,
        *,
        runner: GitRunner | None = None,
        transport_resolver: Callable[[RepoRef], str] | None = None,
    ):
        self.settings = settings
        self.pipeline = pipeline or PipelineConfig()
        self.store = RepoStore(db, settings)
        self.runner = runner or GitRunner(settings)
        self.transport_resolver = transport_resolver or (lambda ref: ref.url)
        self.root = Path(settings.data_dir) / "repos"
        self._locks: dict[int, asyncio.Lock] = {}

    def _clone_dir(self, repo_id: int) -> Path:
        return self.root / str(repo_id)

    def _lock_path(self, repo_id: int) -> Path:
        return self.root / f".{repo_id}.lock"

    async def _repo_lock(self, repo_id: int):
        lock = self._locks.setdefault(repo_id, asyncio.Lock())
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    async def register(self, url: str) -> RepoRegistration:
        ref = RepoRef.parse(url)
        existing = await self.store.get_repo_by_url(ref.url)
        info = await get_remote_info(self.runner, self.transport_resolver(ref))
        transport_url = self.transport_resolver(ref)
        if transport_url.startswith("https://github.com/"):
            await estimate_remote_size_mb(ref, self.settings)
        if existing is not None:
            updated = await self.store.update_repo_fields(
                existing.id,
                default_branch=info.default_branch,
                last_checked_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )
            return RepoRegistration(repo=updated, already_existed=True)
        try:
            repo = await self.store.create_repo(ref, info.default_branch)
        except ConflictError:
            existing = await self.store.get_repo_by_url(ref.url)
            if existing is None:
                raise
            return RepoRegistration(repo=existing, already_existed=True)
        log.info(
            "repo_registered",
            repo_id=repo.id,
            url=ref.url,
            default_branch=info.default_branch,
            head_sha=info.head_sha,
        )
        return RepoRegistration(repo=repo, already_existed=False)

    async def check_remote(self, repo_id: int, *, persist: bool = True) -> RemoteCheck:
        repo = await self.store.get_repo(repo_id)
        info = await get_remote_info(self.runner, self.transport_resolver(repo.ref))
        if persist:
            await self.store.update_repo_fields(
                repo_id,
                default_branch=info.default_branch,
                last_checked_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
                remote_sha=info.head_sha,
                remote_checked_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )
        return RemoteCheck(
            remote_sha=info.head_sha,
            indexed_sha=repo.indexed_sha,
            is_stale=repo.indexed_sha != info.head_sha,
            default_branch=info.default_branch,
        )

    async def _acquire_file_lock(self, repo_id: int):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._lock_path(repo_id)
        deadline = time.monotonic() + self.settings.clone_timeout_seconds
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return path
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise RepoFetchError("Timed out waiting for repository lock") from None
                await asyncio.sleep(0.1)

    async def _clone(self, repo: Repo, clone_url: str, branch: str, destination: Path):
        args = ["clone", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules"]
        if branch != "HEAD":
            args += ["--branch", branch]
        args += [clone_url, str(destination)]
        await self.runner.run(args, timeout=self.settings.clone_timeout_seconds)
        result = await self.runner.run(["rev-parse", "HEAD"], cwd=destination)
        return result.stdout.decode().strip()

    async def fetch(self, repo_id: int) -> FetchResult:
        repo = await self.store.get_repo(repo_id)
        lock_path = await self._acquire_file_lock(repo_id)
        destination = self._clone_dir(repo_id)
        try:
            for temp in self.root.glob(".tmp-*"):
                if temp.is_dir():
                    _remove_tree(temp)
            info = await get_remote_info(self.runner, self.transport_resolver(repo.ref))
            if info.default_branch != repo.default_branch:
                repo = await self.store.update_repo_fields(
                    repo_id, default_branch=info.default_branch
                )
            clone_url = self.transport_resolver(repo.ref)
            previous = None
            cloned = not destination.is_dir() or not (destination / ".git").exists()
            if not cloned:
                try:
                    previous = (
                        (await self.runner.run(["rev-parse", "HEAD"], cwd=destination))
                        .stdout.decode()
                        .strip()
                    )
                except RepoFetchError:
                    cloned = True
            if cloned:
                if destination.exists():
                    _remove_tree(destination)
                temp = self.root / f".tmp-{uuid.uuid4().hex}"
                try:
                    head = await self._clone(repo, clone_url, info.default_branch, temp)
                    os.replace(temp, destination)
                finally:
                    if temp.exists():
                        _remove_tree(temp)
            else:
                try:
                    refspec = (
                        "FETCH_HEAD"
                        if info.default_branch == "HEAD"
                        else f"+refs/heads/{info.default_branch}:refs/remotes/origin/"
                        f"{info.default_branch}"
                    )
                    await self.runner.run(
                        ["fetch", "--depth", "1", "--no-tags", "origin", refspec], cwd=destination
                    )
                    await self.runner.run(["reset", "--hard", "FETCH_HEAD"], cwd=destination)
                    await self.runner.run(["clean", "-ffdx"], cwd=destination)
                    head = (
                        (await self.runner.run(["rev-parse", "HEAD"], cwd=destination))
                        .stdout.decode()
                        .strip()
                    )
                except RepoFetchError:
                    log.warning("repo_fetch_self_heal", repo_id=repo_id)
                    _remove_tree(destination)
                    temp = self.root / f".tmp-{uuid.uuid4().hex}"
                    try:
                        head = await self._clone(repo, clone_url, info.default_branch, temp)
                        if destination.exists():
                            _remove_tree(destination)
                        os.replace(temp, destination)
                        cloned = True
                    finally:
                        if temp.exists():
                            _remove_tree(temp)
            log.info("repo_fetched", repo_id=repo_id, cloned=cloned, head_sha=head)
            return FetchResult(
                head_sha=head,
                cloned=cloned,
                previous_head_sha=previous,
                default_branch=info.default_branch,
            )
        except Exception as exc:
            await self.store.update_repo_fields(repo_id, last_error="Repository fetch failed")
            if isinstance(exc, RepoFetchError):
                raise
            raise RepoFetchError("Repository fetch failed", details={"retryable": True}) from exc
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def scan(
        self, repo_id: int, *, include_skipped: bool = False, skipped_reason: str | None = None
    ) -> ScanReport:
        await self.store.get_repo(repo_id)
        clone = self._clone_dir(repo_id)
        if not clone.is_dir():
            raise NotFoundError("Repository clone not found; run repo fetch first")
        started = time.perf_counter()
        head = (await self.runner.run(["rev-parse", "HEAD"], cwd=clone)).stdout.decode().strip()
        paths = (await self.runner.run(["ls-files", "-z"], cwd=clone)).stdout.split(b"\0")
        filterer = FileFilter(self.pipeline, max_file_bytes=self.settings.max_file_bytes)
        entries, skipped = [], Counter()
        skipped_bytes = Counter()
        skipped_paths: list[dict[str, str | int]] = []

        def record_skip(path: str, reason: str, size: int = 0):
            skipped[reason] += 1
            skipped_bytes[reason] += size
            if include_skipped and (skipped_reason is None or skipped_reason == reason):
                skipped_paths.append({"path": path, "reason": reason, "size_bytes": size})

        root = clone.resolve()
        for raw_path in paths:
            if not raw_path:
                continue
            rel = raw_path.decode("utf-8", "surrogateescape").replace("\\", "/")
            candidate = clone / Path(rel)
            try:
                candidate.resolve(strict=False).relative_to(root)
            except ValueError:
                record_skip(rel, "not_regular")
                continue
            try:
                stat = candidate.lstat()
            except OSError:
                record_skip(rel, "not_regular")
                continue
            decision = filterer.decide(
                rel, stat.st_size, is_symlink=candidate.is_symlink(), is_regular=candidate.is_file()
            )
            if not decision.include and decision.reason:
                record_skip(rel, decision.reason, stat.st_size)
                continue
            if stat.st_size > self.settings.max_file_bytes:
                record_skip(rel, "too_large", stat.st_size)
                continue
            try:
                content = await asyncio.to_thread(candidate.read_bytes)
            except OSError:
                record_skip(rel, "not_regular", stat.st_size)
                continue
            decision = filterer.decide(rel, len(content), content=content)
            if not decision.include:
                record_skip(rel, decision.reason, len(content))
                continue
            entries.append(
                FileEntry(
                    path=rel,
                    file_hash=_hash_bytes(content),
                    size_bytes=len(content),
                    language=filterer.language(rel),
                )
            )
        entries.sort(key=lambda item: item.path)
        if (
            len(entries) > self.settings.max_repo_files
            or sum(e.size_bytes for e in entries) > self.settings.max_repo_source_bytes
        ):
            cap, value, limit = (
                ("max_repo_files", len(entries), self.settings.max_repo_files)
                if len(entries) > self.settings.max_repo_files
                else (
                    "max_repo_source_bytes",
                    sum(e.size_bytes for e in entries),
                    self.settings.max_repo_source_bytes,
                )
            )
            message = f"Repository exceeds {cap} ({value} > {limit})"
            await self.store.update_repo_fields(repo_id, status="failed", last_error=message)
            _remove_tree(clone)
            raise RepoTooLargeError(message, details={"cap": cap, "value": value, "limit": limit})
        report = ScanReport(
            repo_id=repo_id,
            head_sha=head,
            entries=entries,
            skipped=[
                SkipSummary(reason=k, count=skipped[k], total_bytes=skipped_bytes[k])
                for k in sorted(skipped)
            ],
            total_included_files=len(entries),
            total_included_bytes=sum(e.size_bytes for e in entries),
            scan_duration_ms=int((time.perf_counter() - started) * 1000),
            skipped_paths=skipped_paths if include_skipped else None,
        )
        log.info(
            "repo_scanned",
            repo_id=repo_id,
            included_files=report.total_included_files,
            included_bytes=report.total_included_bytes,
            skipped=skipped,
            duration_ms=report.scan_duration_ms,
        )
        return report

    async def load_source_file(self, repo_id: int, entry: FileEntry) -> SourceFile:
        clone = self._clone_dir(repo_id).resolve()
        path = (clone / Path(entry.path)).resolve()
        try:
            path.relative_to(clone)
        except ValueError as exc:
            raise IndexingError("Source path escapes repository clone") from exc
        try:
            raw = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise IndexingError("Source file disappeared from repository clone") from exc
        if _hash_bytes(raw) != entry.file_hash:
            raise IndexingError("Repository clone changed underneath the scan")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IndexingError("Indexed source file is not valid UTF-8") from exc
        """Content preserves CRLF; consumers split only on '\\n' and retain trailing '\\r'."""
        return SourceFile(
            repo_id=repo_id,
            path=entry.path,
            language=entry.language,
            content=content,
            file_hash=entry.file_hash,
            size_bytes=len(raw),
        )

    async def iter_source_files(
        self, repo_id: int, entries: list[FileEntry]
    ) -> AsyncIterator[SourceFile]:
        for entry in entries:
            yield await self.load_source_file(repo_id, entry)

    async def remove(self, repo_id: int):
        await self.store.delete_repo(repo_id)
        _remove_tree(self._clone_dir(repo_id))
