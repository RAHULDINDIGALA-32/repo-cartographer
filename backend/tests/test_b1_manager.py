import asyncio
import subprocess
from pathlib import Path

import pytest

from app.config.pipeline import PipelineConfig
from app.core.errors import IndexingError
from app.repos_git.git_runner import GitRunner
from app.repos_git.manager import RepoManager


async def git(*args, cwd: Path):
    result = await asyncio.to_thread(
        subprocess.run, ["git", *args], cwd=cwd, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout.decode().strip()


@pytest.mark.asyncio
async def test_manager_local_remote_end_to_end(test_db, tmp_path):
    settings, db = test_db
    remote = tmp_path / "remote"
    remote.mkdir()
    await git("init", cwd=remote)
    await git("config", "user.email", "test@example.com", cwd=remote)
    await git("config", "user.name", "Test", cwd=remote)
    (remote / "main.py").write_text("print('one')\n", encoding="utf-8")
    await git("add", ".", cwd=remote)
    await git("commit", "-m", "initial", cwd=remote)
    manager = RepoManager(
        db,
        settings,
        PipelineConfig(),
        runner=GitRunner(settings, allow_file_protocol=True),
        transport_resolver=lambda ref: remote.as_uri(),
    )
    registration = await manager.register("owner/project")
    fetched = await manager.fetch(registration.repo.id)
    assert fetched.cloned and fetched.head_sha
    report = await manager.scan(registration.repo.id)
    assert [entry.path for entry in report.entries] == ["main.py"]
    source = await manager.load_source_file(registration.repo.id, report.entries[0])
    assert source.content == "print('one')\n"
    (remote / "main.py").write_text("print('two')\r\n", encoding="utf-8")
    await git("add", ".", cwd=remote)
    await git("commit", "-m", "update", cwd=remote)
    updated = await manager.fetch(registration.repo.id)
    assert not updated.cloned and updated.head_sha != fetched.head_sha
    updated_report = await manager.scan(registration.repo.id)
    assert (
        await manager.load_source_file(registration.repo.id, updated_report.entries[0])
    ).content.endswith("\r\n")
    await manager.remove(registration.repo.id)
    assert not (settings.data_dir / "repos" / str(registration.repo.id)).exists()


@pytest.mark.asyncio
async def test_source_hash_mismatch(test_db, tmp_path):
    settings, db = test_db
    remote = tmp_path / "remote"
    remote.mkdir()
    await git("init", cwd=remote)
    await git("config", "user.email", "test@example.com", cwd=remote)
    await git("config", "user.name", "Test", cwd=remote)
    (remote / "a.py").write_text("a\n", encoding="utf-8")
    await git("add", ".", cwd=remote)
    await git("commit", "-m", "initial", cwd=remote)
    manager = RepoManager(
        db,
        settings,
        runner=GitRunner(settings, allow_file_protocol=True),
        transport_resolver=lambda ref: remote.as_uri(),
    )
    result = await manager.register("owner/hash")
    await manager.fetch(result.repo.id)
    report = await manager.scan(result.repo.id)
    (settings.data_dir / "repos" / str(result.repo.id) / "a.py").write_text(
        "changed\n", encoding="utf-8"
    )
    with pytest.raises(IndexingError):
        await manager.load_source_file(result.repo.id, report.entries[0])
