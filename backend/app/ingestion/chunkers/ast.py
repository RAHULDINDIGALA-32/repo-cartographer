from __future__ import annotations

import importlib.metadata
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config.pipeline import PipelineConfig
from app.models import Chunk, SourceFile

from .common import (
    LineTable,
    block_split,
    fallback_chunks,
    fill_gaps,
    line_split,
    make_chunk,
    merge_small,
)

log = logging.getLogger(__name__)
_thread_state = threading.local()
_SUPPORTED = {
    "Python": "python",
    "TypeScript": "typescript",
    "TSX": "tsx",
    "JavaScript": "javascript",
    "JSX": "javascript",
}
_DEFINITION_TYPES = {
    "function_definition": ("function", "function"),
    "class_definition": ("class", "class"),
    "function_declaration": ("function", "function"),
    "generator_function_declaration": ("function", "function"),
    "class_declaration": ("class", "class"),
    "abstract_class_declaration": ("class", "class"),
    "method_definition": ("method", "method"),
    "interface_declaration": ("class", "class"),
    "type_alias_declaration": ("class", "class"),
    "enum_declaration": ("class", "class"),
}


def _grammar_version() -> str:
    try:
        return importlib.metadata.version("tree-sitter-language-pack")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _parser(language: str):
    cache = getattr(_thread_state, "parsers", None)
    if cache is None:
        cache = _thread_state.parsers = {}
    if language not in cache:
        try:
            import tree_sitter_language_pack as pack

            if not getattr(_thread_state, "configured", False):
                from pathlib import Path

                pack.configure(
                    pack.PackConfig(
                        cache_dir=os.getenv(
                            "TREE_SITTER_CACHE_DIR", str(Path(".tree-sitter-cache"))
                        )
                    )
                )
                _thread_state.configured = True
            cache[language] = pack.get_parser(language)
        except Exception as exc:
            raise LookupError(language) from exc
    return cache[language]


@dataclass(frozen=True)
class _NodeInfo:
    node: object
    base: object
    symbol: str | None
    symbol_type: str
    start: int
    end: int


def _line_range(node) -> tuple[int, int]:
    start = node.start_point[0] + 1
    end = node.end_point[0] + (1 if node.end_point[1] else 0)
    return start, max(start, end)


def _descendants(node):
    yield node
    for child in node.named_children:
        yield from _descendants(child)


def _name(node) -> str | None:
    named = node.child_by_field_name("name")
    if named is not None:
        value = named.text.decode("utf-8", errors="replace").strip()
        return value or None
    for candidate in _descendants(node):
        if candidate.type in {
            "identifier",
            "type_identifier",
            "property_identifier",
            "namespace_name",
        }:
            value = candidate.text.decode("utf-8", errors="replace").strip()
            if value:
                return value
    return None


def _definition(node) -> _NodeInfo | None:
    for candidate in _descendants(node):
        if candidate.type in _DEFINITION_TYPES:
            symbol_type, _ = _DEFINITION_TYPES[candidate.type]
            return _NodeInfo(
                candidate, candidate, _name(candidate), symbol_type, *_line_range(node)
            )
    if node.type in {"lexical_declaration", "variable_declaration"}:
        if any(
            candidate.type in {"arrow_function", "function_expression"}
            for candidate in _descendants(node)
        ):
            return _NodeInfo(node, node, _name(node), "function", *_line_range(node))
    if node.type in {"public_field_definition", "field_definition", "property_definition"}:
        if any(
            candidate.type in {"arrow_function", "function_expression"}
            for candidate in _descendants(node)
        ):
            return _NodeInfo(node, node, _name(node), "method", *_line_range(node))
    if node.type in {"export_statement", "decorated_definition"}:
        return None
    return None


def _is_container(info: _NodeInfo) -> bool:
    return info.base.type in {"class_definition", "class_declaration", "abstract_class_declaration"}


def _children_definitions(
    node,
    parent: str | None,
    table: LineTable,
    file: SourceFile,
    config: PipelineConfig,
    version: str,
) -> list[Chunk]:
    body = node.child_by_field_name("body")
    if body is None:
        for candidate in node.named_children:
            if candidate.type in {"block", "class_body", "class_body_declaration_list"}:
                body = candidate
                break
    if body is None:
        return []
    children = []
    for child in body.named_children:
        info = _definition(child)
        if info:
            children.append((child, info))
    result: list[Chunk] = []
    for _child, info in children:
        name = info.symbol
        if count := _tokens(table.text(info.start, info.end), config):
            if count <= config.max_chunk_tokens:
                result.append(
                    make_chunk(
                        file,
                        table,
                        info.start,
                        info.end,
                        config,
                        symbol=name,
                        symbol_type=info.symbol_type,
                        parent_symbol=parent,
                        version=version,
                    )
                )
            else:
                pieces = line_split(
                    file,
                    table,
                    info.start,
                    info.end,
                    config,
                    version=version,
                    symbol=name,
                    symbol_type=info.symbol_type,
                    parent_symbol=parent,
                )
                for i, piece in enumerate(pieces, 1):
                    result.append(
                        piece.model_copy(update={"part_index": i, "part_count": len(pieces)})
                    )
    return [x for x in result if x]


def _tokens(text: str, config: PipelineConfig) -> int:
    from .tokens import count_tokens

    return count_tokens(text, config.tokenizer)


class AstChunker:
    name = "ast"

    def __init__(self, config: PipelineConfig | None = None, **_: object):
        self.config = config or PipelineConfig()
        self.version = f"ast:1.0.0+tslp-{_grammar_version()}"

    def chunk(self, file: SourceFile) -> list[Chunk]:
        if not file.content.strip():
            return []
        if file.language == "Markdown":
            return self._markdown(file)
        if file.language in {"YAML", "TOML", "JSON", "Dockerfile", "text", "shell"}:
            return self._config(file)
        language = _SUPPORTED.get(file.language)
        if language is None:
            return fallback_chunks(file, self.config, "unsupported_language", self.version)
        try:
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self._parse, language, file.content.encode("utf-8"))
            try:
                tree = future.result(timeout=self.config.parse_timeout_ms / 1000)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        except TimeoutError:
            return fallback_chunks(file, self.config, "parse_timeout", self.version)
        except LookupError:
            log.warning("tree-sitter grammar unavailable", extra={"language": language})
            return fallback_chunks(file, self.config, "no_grammar", self.version)
        except Exception:
            return fallback_chunks(file, self.config, "parse_error_ratio", self.version)
        table = LineTable.from_text(file.content)
        error_lines = {
            n.start_point[0] + 1 for n in _descendants(tree.root_node) if n.type == "ERROR"
        }
        if (
            error_lines
            and len(error_lines) / max(1, len(table.lines)) > self.config.max_parse_error_ratio
        ):
            return fallback_chunks(file, self.config, "parse_error_ratio", self.version)
        chunks: list[Chunk] = []
        consumed_comments: set[int] = set()
        root_children = list(tree.root_node.named_children)
        for index, node in enumerate(root_children):
            info = _definition(node)
            if info is None:
                continue
            start = info.start
            if index and root_children[index - 1].type in {
                "comment",
                "line_comment",
                "block_comment",
            }:
                previous = root_children[index - 1]
                if not any(
                    not line.strip()
                    for line in table.lines[previous.end_point[0] : node.start_point[0]]
                ):
                    start = _line_range(previous)[0]
                    consumed_comments.add(index - 1)
            info = _NodeInfo(
                info.node,
                info.base,
                info.symbol or ("default" if node.type == "export_statement" else None),
                info.symbol_type,
                start,
                info.end,
            )
            text = table.text(start, info.end)
            if _tokens(text, self.config) <= self.config.max_chunk_tokens:
                chunks.append(
                    make_chunk(
                        file,
                        table,
                        start,
                        info.end,
                        self.config,
                        symbol=info.symbol,
                        symbol_type=info.symbol_type,
                        version=self.version,
                    )
                )
            elif _is_container(info):
                members = _children_definitions(
                    info.base, info.symbol, table, file, self.config, self.version
                )
                first = min((m.start_line for m in members), default=info.end + 1)
                skeleton_end = max(start, first - 1)
                if _tokens(table.text(start, skeleton_end), self.config) <= self.config.max_chunk_tokens:
                    skeleton = make_chunk(
                        file,
                        table,
                        start,
                        skeleton_end,
                        self.config,
                        symbol=info.symbol,
                        symbols=[info.symbol] if info.symbol else [],
                        symbol_type="class_skeleton",
                        version=self.version,
                    )
                    if skeleton:
                        chunks.append(skeleton)
                else:
                    chunks.extend(
                        line_split(
                            file,
                            table,
                            start,
                            skeleton_end,
                            self.config,
                            version=self.version,
                            symbol=info.symbol,
                            symbol_type="class_skeleton",
                        )
                    )
                chunks.extend(members)
            else:
                pieces = line_split(
                    file,
                    table,
                    start,
                    info.end,
                    self.config,
                    version=self.version,
                    symbol=info.symbol,
                    symbol_type=info.symbol_type,
                )
                chunks.extend(
                    piece.model_copy(update={"part_index": i, "part_count": len(pieces)})
                    for i, piece in enumerate(pieces, 1)
                )
        for node in root_children:
            if (
                node.type in {"comment", "line_comment", "block_comment"}
                and node.start_point[0] + 1 in consumed_comments
            ):
                continue
            if _definition(node) is None:
                start, end = _line_range(node)
                if node.type in {
                    "import_statement",
                    "import_from_statement",
                    "import_clause",
                    "module",
                    "expression_statement",
                }:
                    chunks.extend(
                        block_split(
                            file,
                            table,
                            start,
                            end,
                            self.config,
                            version=self.version,
                            symbol_type="module_header" if "import" in node.type else "text_block",
                        )
                    )
        chunks = fill_gaps(chunks, file, table, self.config, self.version)
        chunks = merge_small(chunks, file, table, self.config, self.version)
        if len(chunks) > self.config.max_chunks_per_file:
            log.warning("chunk cap exceeded", extra={"path": file.path, "chunks": len(chunks)})
            chunks = fallback_chunks(file, self.config, "chunk_cap_exceeded", self.version)
        return chunks

    @staticmethod
    def _parse(language: str, content: bytes):
        return _parser(language).parse(content)

    def _markdown(self, file: SourceFile) -> list[Chunk]:
        table = LineTable.from_text(file.content)
        headings: list[tuple[int, int, str]] = []
        fenced = False
        for line_no, line in enumerate(table.lines, 1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fenced = not fenced
                continue
            if not fenced:
                value = line.lstrip()
                hashes = len(value) - len(value.lstrip("#"))
                if 1 <= hashes <= 6 and value[hashes : hashes + 1] == " ":
                    headings.append((line_no, hashes, value[hashes:].strip()))
        sections: list[Chunk] = []
        boundaries = [1] + [h[0] for h in headings]
        for i, start in enumerate(boundaries):
            end = (boundaries[i + 1] - 1) if i + 1 < len(boundaries) else len(table.lines)
            heading = next((h for h in headings if h[0] == start), None)
            symbol = heading[2] if heading else PurePosixPath(file.path).stem
            parent = None
            if heading:
                parent = next((h[2] for h in reversed(headings[:i]) if h[1] < heading[1]), None)
            if _tokens(table.text(start, end), self.config) <= self.config.max_chunk_tokens:
                chunk = make_chunk(
                    file,
                    table,
                    start,
                    end,
                    self.config,
                    symbol=symbol,
                    symbol_type="doc_section",
                    parent_symbol=parent,
                    version=self.version,
                )
                if chunk:
                    sections.append(chunk)
            else:
                sections.extend(
                    line_split(
                        file,
                        table,
                        start,
                        end,
                        self.config,
                        version=self.version,
                        symbol=symbol,
                        symbol_type="doc_section",
                        parent_symbol=parent,
                    )
                )
        return merge_small(sections, file, table, self.config, self.version)

    def _config(self, file: SourceFile) -> list[Chunk]:
        table = LineTable.from_text(file.content)
        if not table.lines:
            return []
        if _tokens(file.content, self.config) <= self.config.max_chunk_tokens:
            return [
                make_chunk(
                    file,
                    table,
                    1,
                    len(table.lines),
                    self.config,
                    symbol=PurePosixPath(file.path).stem,
                    symbol_type="config",
                    version=self.version,
                )
            ]
        return block_split(
            file,
            table,
            1,
            len(table.lines),
            self.config,
            version=self.version,
            symbol_type="config",
        )


def tree_dump(file: SourceFile, depth: int = 4) -> str:
    language = _SUPPORTED.get(file.language)
    if not language:
        return f"unsupported language: {file.language}"
    tree = _parser(language).parse(file.content.encode("utf-8"))
    lines: list[str] = []

    def walk(node, level: int):
        lines.append(
            "  " * level
            + f"{node.type} [{node.start_point[0] + 1}:{node.start_point[1]}-{node.end_point[0] + 1}:{node.end_point[1]}]"
        )
        if level < depth:
            for child in node.named_children:
                walk(child, level + 1)

    walk(tree.root_node, 0)
    return "\n".join(lines)
