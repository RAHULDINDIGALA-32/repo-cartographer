from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from app.models import Citation, ContextBlock

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class CitationResult:
    citations: list[Citation]
    used: list[int]
    invalid: list[int]
    unused_blocks: list[int]
    uncited_answer: bool

    def as_dict(self):
        return {
            "used": self.used,
            "invalid": self.invalid,
            "unused_blocks": self.unused_blocks,
            "uncited_answer": self.uncited_answer,
        }


class CitationParser:
    def __init__(self):
        self._text = ""

    def feed(self, token: str) -> None:
        self._text += token
        if len(self._text) > 1_000_000:
            self._text = self._text[-1_000_000:]

    def finish(self) -> str:
        return self._text


def _without_code(text: str) -> str:
    output: list[str] = []
    in_fence = False
    in_inline = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            output.append("\n")
            continue
        if in_fence:
            output.append("\n")
            continue
        result = []
        i = 0
        while i < len(line):
            if line[i] == "`":
                in_inline = not in_inline
                result.append(" ")
            elif not in_inline:
                result.append(line[i])
            else:
                result.append(" ")
            i += 1
        output.append("".join(result))
    return "".join(output)


def validate_citations(
    text: str, blocks: list[ContextBlock], owner: str, name: str, commit_sha: str
) -> CitationResult:
    valid_indices = {block.index for block in blocks}
    found: list[int] = []
    for match in _MARKER.finditer(_without_code(text)):
        found.extend(int(value.strip()) for value in match.group(1).split(","))
    used = sorted({value for value in found if value in valid_indices})
    invalid = sorted({value for value in found if value <= 0 or value not in valid_indices})
    citations = []
    for index in used:
        block = next(block for block in blocks if block.index == index)
        path = quote(block.path, safe="/")
        citations.append(
            Citation(
                index=index,
                chunk_id=block.chunk_id,
                path=block.path,
                start_line=block.start_line,
                end_line=block.end_line,
                commit_sha=commit_sha,
                url=f"https://github.com/{owner}/{name}/blob/{commit_sha}/{path}#L{block.start_line}-L{block.end_line}",
            )
        )
    normalized = text.lower()
    insufficient = any(
        phrase in normalized
        for phrase in (
            "insufficient context",
            "not enough context",
            "cannot determine from the provided context",
        )
    )
    return CitationResult(
        citations,
        used,
        invalid,
        sorted(valid_indices - set(used)),
        not bool(used) and not insufficient,
    )
