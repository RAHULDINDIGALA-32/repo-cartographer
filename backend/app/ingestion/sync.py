"""Pure change-set calculation used by incremental indexing and previews."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReprocessItem:
    path: str
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        return ",".join(self.reasons)


@dataclass(frozen=True)
class ChangeSet:
    added: tuple[dict, ...] = ()
    modified: tuple[dict, ...] = ()
    deleted: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    reprocess: tuple[ReprocessItem, ...] = ()
    renamed_hint: tuple[tuple[str, str], ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        return {"added": len(self.added), "modified": len(self.modified), "deleted": len(self.deleted), "unchanged": len(self.unchanged), "reprocess": len(self.reprocess)}

    @property
    def reason_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.reprocess:
            for reason in item.reasons:
                out[reason] = out.get(reason, 0) + 1
        out["deleted"] = len(self.deleted)
        return dict(sorted(out.items()))

    @property
    def bytes_by_group(self) -> dict[str, int]:
        return {
            "added": sum(int(_get(x, "size_bytes", 0) or 0) for x in self.added),
            "modified": sum(int(_get(x, "size_bytes", 0) or 0) for x in self.modified),
        }


@dataclass(frozen=True)
class SyncResult:
    run_id: int | None
    status: str
    from_sha: str | None
    to_sha: str | None
    counts: dict
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    chunks_deleted: int = 0
    reuse_ratio: float = 0.0
    embed_tokens: int = 0
    tokens_saved_estimate: int = 0
    duration_ms: int = 0
    degraded_or_warnings: tuple[str, ...] = ()
    error: str | None = None


def _get(value, key, default=None):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def compute_change_set(inventory: Iterable, existing: Iterable, summaries: Mapping | None = None, active_versions: Mapping | None = None) -> ChangeSet:
    """Compare scan rows with indexed rows without I/O.

    The function accepts pydantic models, dataclasses, or mappings, which keeps
    it useful to DB adapters and deterministic unit tests.
    """
    summaries = summaries or {}
    active_versions = active_versions or {}
    inv = {str(_get(x, "path")): x for x in inventory}
    old = {str(_get(x, "path")): x for x in existing}
    added, modified, deleted, unchanged, reprocess = [], [], [], [], []
    for path in sorted(inv):
        item = inv[path]
        previous = old.get(path)
        if previous is None:
            added.append(item)
            reprocess.append(ReprocessItem(path, ("added",)))
            continue
        reasons: list[str] = []
        if _get(item, "file_hash") != _get(previous, "file_hash"):
            modified.append(item)
            reasons.append("modified")
        summary = summaries.get(path, {})
        if _get(item, "language") != _get(previous, "language"):
            reasons.append("language_changed")
        if _get(summary, "chunker_drift", False):
            reasons.append("chunker_version")
        if _get(summary, "enricher_drift", False):
            reasons.append("enricher_version")
        if _get(summary, "embedder_drift", False):
            reasons.append("embedder_version")
        if _get(summary, "chunk_count", 0) == 0:
            reasons.append("no_chunks")
        if reasons:
            if not any(reason in ("modified",) for reason in reasons):
                unchanged.append(path)
            reprocess.append(ReprocessItem(path, tuple(dict.fromkeys(reasons))))
        else:
            unchanged.append(path)
    deleted = sorted(set(old) - set(inv))
    by_hash: dict[str, list[str]] = {}
    for path in deleted:
        by_hash.setdefault(str(_get(old[path], "file_hash")), []).append(path)
    hints = []
    for path in sorted(inv.keys() - old.keys()):
        digest = str(_get(inv[path], "file_hash"))
        for old_path in by_hash.get(digest, []):
            hints.append((old_path, path))
    return ChangeSet(tuple(added), tuple(modified), tuple(deleted), tuple(sorted(set(unchanged))), tuple(sorted(reprocess, key=lambda x: x.path)), tuple(sorted(hints)))
