import pytest

from app.config.pipeline import PipelineConfig
from app.ingestion.chunkers import AstChunker, FixedChunker
from app.ingestion.chunkers.tokens import count_tokens
from app.interfaces.registry import REGISTRY, build_pipeline
from app.models import SourceFile
from app.repos_git.filter import FileFilter


def source(path: str, language: str, text: str) -> SourceFile:
    return SourceFile(
        repo_id=7,
        path=path,
        language=language,
        content=text,
        file_hash="0" * 64,
        size_bytes=len(text.encode()),
    )


def assert_exact(file: SourceFile, chunks):
    lines = file.content.splitlines(keepends=True)
    for chunk in chunks:
        assert chunk.text == "".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert chunk.text.strip()
    covered = {line for chunk in chunks for line in range(chunk.start_line, chunk.end_line + 1)}
    assert all(not line.strip() or i in covered for i, line in enumerate(lines, 1))


def test_token_count_is_deterministic_for_unicode_and_empty():
    assert count_tokens("") == 0
    assert count_tokens("λ unicode café") == count_tokens("λ unicode café")
    assert count_tokens("word " * 10_000) > 0


def test_fixed_chunker_exact_ranges_and_determinism():
    config = PipelineConfig(chunker="fixed", max_chunk_tokens=10, min_chunk_tokens=2)
    file = source(
        "notes.txt", "text", "one two three\nfour five six\nseven eight nine\nten eleven\n"
    )
    chunker = FixedChunker(config)
    first = chunker.chunk(file)
    assert first == chunker.chunk(file)
    assert_exact(file, first)
    assert all(chunk.symbol_type == "text_block" for chunk in first)


def test_markdown_fenced_hash_is_not_heading():
    config = PipelineConfig(max_chunk_tokens=80, min_chunk_tokens=5)
    file = source(
        "README.md",
        "Markdown",
        "---\ntitle: Demo\n---\n# Install\n\n```python\n"
        "# not a heading\n```\n\n## Windows\n\nUse it.\n",
    )
    chunks = AstChunker(config).chunk(file)
    assert [chunk.symbol for chunk in chunks if chunk.symbol_type == "doc_section"] == [
        "README",
        "Install",
        "Windows",
    ]
    assert_exact(file, chunks)


def test_unsupported_language_records_fallback_and_covers_file():
    file = source("main.go", "Go", 'package main\n\nfunc main() {\n    println("hi")\n}\n')
    chunks = AstChunker(PipelineConfig()).chunk(file)
    assert chunks and all(chunk.fallback_reason == "unsupported_language" for chunk in chunks)
    assert_exact(file, chunks)


def test_solidity_language_is_recognized():
    assert FileFilter.language("contracts/Avatar.sol") == "Solidity"


def test_solidity_structure_when_grammar_is_available():
    file = source(
        "C.sol",
        "Solidity",
        "pragma solidity ^0.8.0;\ncontract C {\n event E(address a);\n"
        " constructor() {}\n function f(uint x) public {}\n}\n",
    )
    chunks = AstChunker(PipelineConfig()).chunk(file)
    if any(chunk.fallback_reason == "no_grammar" for chunk in chunks):
        pytest.skip("Solidity grammar is not installed")
    assert any(chunk.symbol == "C" and chunk.symbol_type == "class" for chunk in chunks)


def test_registry_exposes_both_chunkers():
    try:
        build_pipeline(PipelineConfig(chunker="ast"))
    except Exception:
        pass
    assert set(REGISTRY["chunker"]) >= {"ast", "fixed"}
