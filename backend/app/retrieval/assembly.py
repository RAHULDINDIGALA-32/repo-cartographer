from __future__ import annotations

from app.models import ContextBlock, RetrievalHit


class DefaultContextAssembler:
    name = "default"
    version = "assembler:1"
    block_overhead = 24

    def __init__(self, config=None, **_: object):
        self.config = config
        self.last_report = {"dropped": 0, "oversize": False}

    def assemble(self, hits: list[RetrievalHit], token_budget: int) -> list[ContextBlock]:
        selected: list[RetrievalHit] = []
        occupied: dict[str, list[tuple[int, int]]] = {}
        dropped = 0
        for hit in sorted(hits, key=lambda item: (item.rank, item.chunk.id)):
            ranges = occupied.setdefault(hit.chunk.path, [])
            if any(
                hit.chunk.start_line <= end and hit.chunk.end_line >= start for start, end in ranges
            ):
                dropped += 1
                continue
            ranges.append((hit.chunk.start_line, hit.chunk.end_line))
            selected.append(hit)
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
                dropped += 1
        ordered = sorted(
            kept, key=lambda item: (item.chunk.path, item.chunk.start_line, item.chunk.id)
        )
        self.last_report = {"dropped": dropped, "oversize": oversize, "kept": len(ordered)}
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
