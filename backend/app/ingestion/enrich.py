from __future__ import annotations

import hashlib

from app.config.pipeline import PipelineConfig
from app.models import Chunk, SourceFile

from .tokenizer import TOKENIZER_VERSION, split_identifiers

ENRICHER_VERSION = "enr:1"


class Enricher:
    name = "deterministic"

    def __init__(self, config: PipelineConfig | None = None, **_: object):
        self.config = config or PipelineConfig()
        self.version = f"{ENRICHER_VERSION}|hdr:{'on' if self.config.contextual_headers else 'off'}|{TOKENIZER_VERSION}"

    def _header(self, chunk: Chunk, file: SourceFile) -> str:
        lines = [f"path: {file.path}"]
        if file.language:
            lines.append(f"language: {file.language}")
        symbols = chunk.symbols or ([chunk.symbol] if chunk.symbol else [])
        if symbols:
            qualified = ", ".join(
                f"{chunk.parent_symbol}.{symbol}" if chunk.parent_symbol and symbol else str(symbol)
                for symbol in symbols
            )
            part = (
                f", part {chunk.part_index}/{chunk.part_count}"
                if chunk.part_index and chunk.part_count
                else ""
            )
            lines.append(f"symbol: {qualified} ({chunk.symbol_type}{part})")
        lines.append(f"lines: {chunk.start_line}-{chunk.end_line}")
        return "\n".join(lines)

    def enrich(self, chunk: Chunk, file: SourceFile) -> Chunk:
        embed_text = (
            f"{self._header(chunk, file)}\n\n{chunk.text}"
            if self.config.contextual_headers
            else chunk.text
        )
        search_source = " ".join(
            [file.path, *chunk.symbols, chunk.symbol or "", chunk.parent_symbol or "", chunk.text]
        )
        return chunk.model_copy(
            update={
                "embed_text": embed_text,
                "search_text": split_identifiers(search_source),
                "content_hash": hashlib.sha256(embed_text.encode("utf-8")).hexdigest(),
                "enricher_version": self.version,
            }
        )
