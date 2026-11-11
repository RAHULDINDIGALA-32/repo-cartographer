from pathlib import Path


def test_runtime_config_path_is_found_from_source_tree():
    backend_root = Path(__file__).parents[1]
    candidates = (backend_root / "config.yaml", backend_root.parent / "config.yaml")
    assert (
        next(path for path in candidates if path.is_file())
        == backend_root.parent / "config.yaml"
    )
