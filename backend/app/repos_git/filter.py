from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from app.config.pipeline import PipelineConfig
from app.models import FilterDecision

EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "third_party",
    "dist",
    "build",
    "out",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".next",
    ".nuxt",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    "site-packages",
    "bower_components",
    "Pods",
    ".gradle",
}
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "pipfile.lock",
    "cargo.lock",
    "go.sum",
    "composer.lock",
    "gemfile.lock",
    "bun.lockb",
}
BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".tiff",
    ".svg",
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".o",
    ".a",
    ".jar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}
DATA_EXTS = {".csv", ".tsv", ".parquet", ".sqlite", ".db", ".npy", ".pkl", ".ipynb"}
LANGUAGES = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".jsx": "JSX",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".rst": "reStructuredText",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "SQL",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".dockerfile": "Dockerfile",
}


class FileFilter:
    def __init__(self, config: PipelineConfig, *, max_file_bytes: int):
        self.config = config
        self.max_file_bytes = max_file_bytes

    def _glob(self, path: str, patterns: list[str]) -> bool:
        return any(
            fnmatchcase(path, pattern) or fnmatchcase(PurePosixPath(path).name, pattern)
            for pattern in patterns
        )

    def decide(
        self,
        path: str,
        size: int | None = None,
        leading_bytes: bytes | None = None,
        content: bytes | None = None,
        *,
        is_symlink: bool = False,
        is_regular: bool = True,
    ) -> FilterDecision:
        path = path.replace("\\", "/")
        name = PurePosixPath(path).name
        suffix = PurePosixPath(name).suffix.lower()
        if is_symlink:
            return FilterDecision(include=False, reason="symlink")
        if not is_regular:
            return FilterDecision(include=False, reason="not_regular")
        rescued = self._glob(path, self.config.include_globs)
        if not rescued:
            if any(part in EXCLUDED_DIRS for part in PurePosixPath(path).parts):
                return FilterDecision(include=False, reason="excluded_dir")
            if name.lower() in LOCKFILES or suffix == ".lock":
                return FilterDecision(include=False, reason="lockfile")
            if name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                return FilterDecision(include=False, reason="license")
            if suffix in BINARY_EXTS:
                return FilterDecision(include=False, reason="binary_ext")
            if suffix in DATA_EXTS:
                return FilterDecision(include=False, reason="data_ext")
            if (
                fnmatchcase(name, "*.min.js")
                or fnmatchcase(name, "*.min.css")
                or fnmatchcase(name, "*.map")
                or fnmatchcase(name, "*.snap")
                or fnmatchcase(name, "*_pb2.py")
                or fnmatchcase(name, "*.pb.go")
                or fnmatchcase(name, "*_generated.*")
            ):
                return FilterDecision(include=False, reason="minified_name")
            if self._glob(path, self.config.exclude_globs):
                return FilterDecision(include=False, reason="custom_exclude")
        if size is not None and size > self.max_file_bytes:
            return FilterDecision(include=False, reason="too_large")
        if size == 0 or (content is not None and not content.strip()):
            return FilterDecision(include=False, reason="empty")
        sample = leading_bytes if leading_bytes is not None else content
        if sample is not None and b"\x00" in sample[:8192]:
            return FilterDecision(include=False, reason="binary_content")
        if content is None:
            return FilterDecision(include=True)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return FilterDecision(include=False, reason="undecodable")
        first_lines = "\n".join(text.splitlines()[:20]).lower()
        if any(
            marker in first_lines
            for marker in (
                "do not edit",
                "code generated",
                "@generated",
                "auto-generated",
                "autogenerated",
                "generated by",
            )
        ):
            return FilterDecision(include=False, reason="generated")
        lines = text.splitlines() or [text]
        if max(map(len, lines)) > 5000 or sum(map(len, lines)) / len(lines) > 300:
            return FilterDecision(include=False, reason="minified_or_data")
        return FilterDecision(include=True)

    @staticmethod
    def language(path: str) -> str:
        name = PurePosixPath(path).name
        if name == "Dockerfile" or name.lower().startswith("dockerfile."):
            return "Dockerfile"
        if name in {"Makefile", "makefile"}:
            return "text"
        return LANGUAGES.get(PurePosixPath(name).suffix.lower(), "text")
