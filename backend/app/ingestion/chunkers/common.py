from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.config.pipeline import PipelineConfig
from app.models import Chunk, SourceFile

from .tokens import count_tokens


@dataclass(frozen=True)
class LineTable:
    lines: list[str]

    @classmethod
    def from_text(cls, text: str) -> LineTable:
        return cls(text.splitlines(keepends=True) or ([text] if text else []))

    def text(self, start: int, end: int) -> str:
        return "".join(self.lines[start - 1 : end])

    def nonblank(self, start: int, end: int) -> bool:
        return any(line.strip() for line in self.lines[start - 1 : end])


def make_chunk(
    file: SourceFile,
    table: LineTable,
    start: int,
    end: int,
    config: PipelineConfig,
    *,
    symbol: str | None = None,
    symbols: Iterable[str] = (),
    symbol_type: str = "text_block",
    parent_symbol: str | None = None,
    part_index: int | None = None,
    part_count: int | None = None,
    fallback_reason: str | None = None,
    version: str,
) -> Chunk | None:
    start = max(1, start)
    end = min(len(table.lines), end)
    text = table.text(start, end)
    if not text or not text.strip():
        return None
    names = list(dict.fromkeys(x for x in symbols if x))
    if symbol and symbol not in names:
        names.insert(0, symbol)
    return Chunk(
        repo_id=file.repo_id,
        path=file.path,
        symbol=symbol,
        symbols=names,
        symbol_type=symbol_type,  # type: ignore[arg-type]
        parent_symbol=parent_symbol,
        start_line=start,
        end_line=end,
        text=text,
        token_count=count_tokens(text, config.tokenizer),
        chunker_version=version,
        part_index=part_index,
        part_count=part_count,
        fallback_reason=fallback_reason,
    )


def line_split(
    file: SourceFile,
    table: LineTable,
    start: int,
    end: int,
    config: PipelineConfig,
    *,
    version: str,
    symbol: str | None = None,
    symbol_type: str = "text_block",
    parent_symbol: str | None = None,
    fallback_reason: str | None = None,
    overlap: bool = False,
) -> list[Chunk]:
    result: list[Chunk] = []
    cursor = start
    while cursor <= end:
        best = cursor
        for candidate in range(cursor, end + 1):
            text = table.text(cursor, candidate)
            if (
                count_tokens(text, config.tokenizer) <= config.max_chunk_tokens
                or candidate == cursor
            ):
                best = candidate
                if count_tokens(text, config.tokenizer) <= config.max_chunk_tokens:
                    continue
                break
            break
        chunk = make_chunk(
            file,
            table,
            cursor,
            best,
            config,
            symbol=symbol,
            symbol_type=symbol_type,
            parent_symbol=parent_symbol,
            fallback_reason=fallback_reason,
            version=version,
        )
        if chunk:
            result.append(chunk)
        next_cursor = best + 1
        if overlap and next_cursor <= end:
            next_cursor = max(cursor + 1, next_cursor - config.chunk_overlap_lines)
        cursor = next_cursor
    return result


def block_split(
    file: SourceFile,
    table: LineTable,
    start: int,
    end: int,
    config: PipelineConfig,
    *,
    version: str,
    symbol_type: str = "text_block",
    reason: str | None = None,
) -> list[Chunk]:
    blocks: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        while cursor <= end and not table.lines[cursor - 1].strip():
            cursor += 1
        if cursor > end:
            break
        block_start = cursor
        while cursor <= end and table.lines[cursor - 1].strip():
            cursor += 1
        blocks.append((block_start, cursor - 1))
    result: list[Chunk] = []
    pending: tuple[int, int] | None = None
    for bstart, bend in blocks:
        if count_tokens(table.text(bstart, bend), config.tokenizer) > config.max_chunk_tokens:
            if pending:
                result.append(
                    make_chunk(
                        file,
                        table,
                        *pending,
                        config,
                        symbol_type=symbol_type,
                        fallback_reason=reason,
                        version=version,
                    )
                )
                pending = None
            result.extend(
                line_split(
                    file,
                    table,
                    bstart,
                    bend,
                    config,
                    version=version,
                    symbol_type=symbol_type,
                    fallback_reason=reason,
                )
            )
            continue
        candidate = (pending[0], bend) if pending else (bstart, bend)
        if (
            pending
            and count_tokens(table.text(*candidate), config.tokenizer) > config.max_chunk_tokens
        ):
            result.append(
                make_chunk(
                    file,
                    table,
                    *pending,
                    config,
                    symbol_type=symbol_type,
                    fallback_reason=reason,
                    version=version,
                )
            )
            pending = (bstart, bend)
        else:
            pending = candidate
    if pending:
        result.append(
            make_chunk(
                file,
                table,
                *pending,
                config,
                symbol_type=symbol_type,
                fallback_reason=reason,
                version=version,
            )
        )
    return [c for c in result if c]


def merge_small(
    chunks: list[Chunk], file: SourceFile, table: LineTable, config: PipelineConfig, version: str
) -> list[Chunk]:
    merged: list[Chunk] = []
    for chunk in sorted(chunks, key=lambda c: c.start_line):
        if merged:
            previous = merged[-1]
            combined = table.text(previous.start_line, chunk.end_line)
            if (
                previous.end_line + 1 >= chunk.start_line
                and previous.token_count < config.min_chunk_tokens
                and chunk.token_count < config.min_chunk_tokens
                and previous.symbol_type not in {"class", "class_skeleton"}
                and chunk.symbol_type not in {"class", "class_skeleton"}
                and count_tokens(combined, config.tokenizer) <= config.max_chunk_tokens
            ):
                names = list(dict.fromkeys(previous.symbols + chunk.symbols))
                merged[-1] = make_chunk(
                    file,
                    table,
                    previous.start_line,
                    chunk.end_line,
                    config,
                    symbols=names,
                    symbol_type="module_header"
                    if previous.symbol_type == chunk.symbol_type == "module_header"
                    else "text_block",
                    parent_symbol=previous.parent_symbol
                    if previous.parent_symbol == chunk.parent_symbol
                    else None,
                    version=version,
                )
                continue
        merged.append(chunk)
    return merged


def fill_gaps(
    chunks: list[Chunk], file: SourceFile, table: LineTable, config: PipelineConfig, version: str
) -> list[Chunk]:
    covered = {line for chunk in chunks for line in range(chunk.start_line, chunk.end_line + 1)}
    missing = [
        line
        for line in range(1, len(table.lines) + 1)
        if line not in covered and table.lines[line - 1].strip()
    ]
    if missing:
        ranges: list[tuple[int, int]] = []
        start = previous = missing[0]
        for line in missing[1:]:
            if line != previous + 1:
                ranges.append((start, previous))
                start = line
            previous = line
        ranges.append((start, previous))
        for start, end in ranges:
            chunks.extend(
                block_split(file, table, start, end, config, version=version, reason="gap_fill")
            )
    return sorted(chunks, key=lambda c: (c.start_line, c.end_line))


def fallback_chunks(
    file: SourceFile, config: PipelineConfig, reason: str, version: str
) -> list[Chunk]:
    table = LineTable.from_text(file.content)
    return block_split(file, table, 1, len(table.lines), config, version=version, reason=reason)
