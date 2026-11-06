from __future__ import annotations

import json
import math
from collections.abc import Iterable

from app.core.errors import RetrievalError


def vector_to_list(value: object, *, dimension: int | None = None) -> list[float]:
    """Convert pgvector's Vector, arrays, and other sequence-like values safely."""
    raw = getattr(value, "to_list", None)
    if callable(raw):
        value = raw()
    elif hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
        value = list(value)  # pgvector Vector is iterable in some adapter versions.
    elif isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RetrievalError("Stored embedding is not a vector") from exc
    else:
        raise RetrievalError("Stored embedding is not a vector")
    try:
        result = [float(item) for item in value]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RetrievalError("Stored embedding contains a non-numeric value") from exc
    if dimension is not None and len(result) != dimension:
        raise RetrievalError("Stored embedding has the wrong dimension")
    if not all(math.isfinite(item) for item in result):
        raise RetrievalError("Stored embedding contains a non-finite value")
    return result


def vector_literal(values: Iterable[float]) -> list[float]:
    return vector_to_list(list(values))
