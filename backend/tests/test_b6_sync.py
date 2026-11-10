from app.ingestion.sync import compute_change_set


def row(path, digest="a", language="Python", size=1):
    return {"path": path, "file_hash": digest, "language": language, "size_bytes": size}


def test_change_set_groups_and_rename():
    result = compute_change_set(
        [row("b.py", "new"), row("c.py", "same", "JavaScript"), row("new.py", "old")],
        [row("b.py", "old"), row("c.py", "same"), row("old.py", "old"), row("empty.py")],
        {
            "c.py": {"chunk_count": 2, "chunker_drift": True, "embedder_drift": True},
            "empty.py": {"chunk_count": 0},
        },
    )
    assert [x["path"] for x in result.added] == ["new.py"]
    assert [x["path"] for x in result.modified] == ["b.py"]
    assert result.deleted == ("empty.py", "old.py")
    assert result.renamed_hint == (("old.py", "new.py"),)
    assert result.reprocess[1].reasons == (
        "language_changed", "chunker_version", "embedder_version"
    )


def test_empty_state_and_no_chunks_reprocess():
    assert compute_change_set([row("a.py")], [], {}).counts["reprocess"] == 1
    result = compute_change_set([row("a.py")], [row("a.py")], {"a.py": {"chunk_count": 0}})
    assert result.reprocess[0].reasons == ("no_chunks",)
