from __future__ import annotations

import re
from collections import defaultdict

from app.models import ContextBlock, RetrievalHit


def _shingles(text: str, size: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}


def _similarity(left: str, right: str) -> float:
    a, b = _shingles(left), _shingles(right)
    return len(a & b) / len(a | b) if a or b else 1.0


class DefaultContextAssembler:
    name = "default"
    version = "assembler:2"
    block_overhead = 24

    def __init__(self, config=None, db=None, settings=None, **_: object):
        self.config = config
        self.db = db
        self.schema = settings.db_schema if settings is not None else "cartographer"
        self._expanded_ids: set[int] = set()
        self.last_report = {"dropped": 0, "oversize": False}

    async def expand(self, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        settings = self.config.assembler
        if self.db is None or (not settings.expand_parent and not settings.expand_adjacent_parts):
            return []
        from app.retrieval.sparse import _hit

        result = []
        seen = {hit.chunk.id for hit in hits}
        for hit in hits[: settings.expansion_max_blocks]:
            if settings.expand_parent and hit.chunk.parent_symbol:
                sql = f"""SELECT c.id,c.file_id,c.repo_id,f.path,c.symbol,c.symbol_type,c.parent_symbol,
                    c.start_line,c.end_line,c.text,c.content_hash,c.search_text,c.token_count,
                    c.chunker_version,c.enricher_version,c.embedder_version,1.0
                    FROM {self.schema}.chunks c JOIN {self.schema}.files f ON f.id=c.file_id
                    WHERE c.repo_id=%s AND c.file_id=%s AND lower(c.symbol)=lower(%s) LIMIT 1"""
                async with self.db.connection() as conn:
                    cur = await conn.execute(
                        sql, (hit.chunk.repo_id, hit.chunk.file_id, hit.chunk.parent_symbol)
                    )
                    row = await cur.fetchone()
                if row and row[0] not in seen:
                    result.append(_hit(row, len(result) + 1, "fused"))
                    seen.add(row[0])
            if (
                settings.expand_adjacent_parts
                and hit.chunk.symbol
                and len(result) < settings.expansion_max_blocks
            ):
                sql = f"""SELECT c.id,c.file_id,c.repo_id,f.path,c.symbol,c.symbol_type,c.parent_symbol,
                    c.start_line,c.end_line,c.text,c.content_hash,c.search_text,c.token_count,
                    c.chunker_version,c.enricher_version,c.embedder_version,1.0
                    FROM {self.schema}.chunks c JOIN {self.schema}.files f ON f.id=c.file_id
                    WHERE c.repo_id=%s AND c.file_id=%s AND c.symbol=%s AND c.id<>%s
                    ORDER BY abs(c.start_line-%s),c.id LIMIT %s"""
                async with self.db.connection() as conn:
                    cur = await conn.execute(
                        sql,
                        (
                            hit.chunk.repo_id,
                            hit.chunk.file_id,
                            hit.chunk.symbol,
                            hit.chunk.id,
                            hit.chunk.start_line,
                            settings.expansion_max_blocks,
                        ),
                    )
                    rows = await cur.fetchall()
                for row in rows:
                    if row[0] not in seen and len(result) < settings.expansion_max_blocks:
                        result.append(_hit(row, len(result) + 1, "fused"))
                        seen.add(row[0])
        self._expanded_ids = {hit.chunk.id for hit in result}
        return result

    def assemble(self, hits: list[RetrievalHit], token_budget: int) -> list[ContextBlock]:
        settings = self.config.assembler if self.config is not None else None
        threshold = settings.near_duplicate_threshold if settings else 1.0
        per_file = settings.max_chunks_per_file if settings else 0
        selected: list[RetrievalHit] = []
        occupied: dict[str, list[tuple[int, int]]] = defaultdict(list)
        file_counts: dict[str, int] = defaultdict(int)
        dropped_budget = dropped_duplicate = dropped_file = 0
        for hit in sorted(hits, key=lambda item: (item.rank, item.chunk.id)):
            if per_file and file_counts[hit.chunk.path] >= per_file:
                dropped_file += 1
                continue
            ranges = occupied[hit.chunk.path]
            if any(
                hit.chunk.start_line <= end and hit.chunk.end_line >= start for start, end in ranges
            ):
                dropped_duplicate += 1
                continue
            if threshold < 1.0 and any(
                _similarity(hit.chunk.text, other.chunk.text) >= threshold for other in selected
            ):
                dropped_duplicate += 1
                continue
            ranges.append((hit.chunk.start_line, hit.chunk.end_line))
            selected.append(hit)
            file_counts[hit.chunk.path] += 1
        kept: list[RetrievalHit] = []
        used = 0
        oversize = False
        for hit in selected:
            cost = hit.chunk.token_count + self.block_overhead
            if not kept and cost > token_budget:
                kept.append(hit)
                oversize = True
            elif used + cost <= token_budget:
                kept.append(hit)
                used += cost
            else:
                dropped_budget += 1
        ordered = sorted(
            kept, key=lambda item: (item.chunk.path, item.chunk.start_line, item.chunk.id)
        )
        self.last_report = {
            "dropped": dropped_budget + dropped_duplicate + dropped_file,
            "dropped_budget": dropped_budget,
            "dropped_near_duplicate": dropped_duplicate,
            "dropped_file_cap": dropped_file,
            "added_expansion": len(self._expanded_ids),
            "expansion_block_ids": sorted(self._expanded_ids),
            "oversize": oversize,
            "kept": len(ordered),
        }
        return [
            ContextBlock(
                index=index,
                chunk_id=hit.chunk.id,
                path=hit.chunk.path,
                start_line=hit.chunk.start_line,
                end_line=hit.chunk.end_line,
                text=hit.chunk.text,
                symbol=hit.chunk.symbol,
            )
            for index, hit in enumerate(ordered, 1)
        ]
