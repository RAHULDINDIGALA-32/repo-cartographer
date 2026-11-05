from __future__ import annotations

import re

TOKENIZER_VERSION = "tok:1"
_WORD = re.compile(r"[^\W_]+(?:[_.-][^\W_]+)*", re.UNICODE)
_CAMEL_1 = re.compile(r"(?<=[a-z\d])(?=[A-Z])")
_CAMEL_2 = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_DIGIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


def _parts(token: str) -> list[str]:
    whole = token.lower()
    separated = re.sub(r"[_.-]+", " ", token)
    separated = _CAMEL_2.sub(" ", separated)
    separated = _CAMEL_1.sub(" ", separated)
    separated = _DIGIT.sub(" ", separated)
    parts = [part.lower() for part in separated.split() if part]
    return [whole, *[part for part in parts if len(part) > 1 or len(whole) == 1 or part.isdigit()]]


def split_identifiers(text: str) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(text):
        for token in _parts(match.group(0)):
            if token not in seen:
                seen.add(token)
                output.append(token)
    return " ".join(output)
