from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from app.models import Citation, ContextBlock

_MARKER = re.compile(
    r"(?:\[\s*\d+\s*\]\s*(?:-|–|—)\s*\[\s*\d+\s*\]|\[\s*\d+(?:\s*(?:,|-|–|—)\s*\d+)*\s*\]|【\s*\d+(?:†[^】]*)?\s*】)"
)


@dataclass(frozen=True)
class CitationResult:
    citations: list[Citation]
    used: list[int]
    invalid: list[int]
    unused_blocks: list[int]
    uncited_answer: bool
    variants_normalized: list[str] = field(default_factory=list)

    def as_dict(self):
        return {
            "used": self.used,
            "invalid": self.invalid,
            "unused_blocks": self.unused_blocks,
            "uncited_answer": self.uncited_answer,
            "variants_normalized": self.variants_normalized,
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
        for char in line:
            if char == "`":
                in_inline = not in_inline
                result.append(" ")
            else:
                result.append(char if not in_inline else " ")
        output.append("".join(result))
    return "".join(output)


def _expand(marker: str) -> tuple[list[int], set[str]]:
    variants = set()
    if marker.startswith("【"):
        variants.add("fullwidth")
        if "†" in marker:
            variants.add("line_suffix")
        return [int(value) for value in re.findall(r"\d+", marker)[:1]], variants
    if "–" in marker or "—" in marker:
        variants.add("range")
        values = [int(value) for value in re.findall(r"\d+", marker)]
        return list(range(values[0], values[1] + 1)) if len(values) == 2 and values[0] <= values[
            1
        ] else values, variants
    if "-" in marker and re.search(r"\[\s*\d+\s*-\s*\d+\s*\]", marker):
        variants.add("range")
        values = [int(value) for value in re.findall(r"\d+", marker)]
        return list(range(values[0], values[1] + 1)) if len(values) == 2 and values[0] <= values[
            1
        ] else values, variants
    if "," in marker:
        variants.add("comma")
    else:
        variants.add("ascii")
    return [int(value) for value in re.findall(r"\d+", marker)], variants


def validate_citations(
    text: str, blocks: list[ContextBlock], owner: str, name: str, commit_sha: str
) -> CitationResult:
    valid_indices = {block.index for block in blocks}
    found: list[int] = []
    variants: set[str] = set()
    for match in _MARKER.finditer(_without_code(text)):
        values, seen = _expand(match.group(0))
        found.extend(values)
        variants.update(seen)
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
        sorted(variants),
    )
