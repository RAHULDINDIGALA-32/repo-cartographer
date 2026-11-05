import logging
from functools import lru_cache

import tiktoken

log = logging.getLogger(__name__)
_warned = False


@lru_cache(maxsize=8)
def _encoder(name: str):
    try:
        return tiktoken.get_encoding(name)
    except ValueError as exc:
        raise ValueError(f"Unknown tokenizer encoding: {name}") from exc


def count_tokens(text: str, tokenizer: str = "cl100k_base") -> int:
    if not text:
        return 0
    global _warned
    try:
        return len(_encoder(tokenizer).encode(text, disallowed_special=()))
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        # tiktoken may need to download its merge table on first use. Chunking
        # remains usable in air-gapped deployments with a conservative estimate;
        # once the table is provisioned, the exact tokenizer is used automatically.
        if not _warned:
            log.warning("tokenizer data unavailable; using deterministic estimate", exc_info=exc)
            _warned = True
        return max(1, (len(text.encode("utf-8")) + 3) // 4)


def tokenizer_identity(tokenizer: str = "cl100k_base", *, require_exact: bool = False) -> str:
    try:
        _encoder(tokenizer)
        return f"tok-{tokenizer.replace('_', '-')}"
    except Exception as exc:
        if require_exact:
            raise RuntimeError(f"Tokenizer data for {tokenizer} is unavailable") from exc
        return "tok-estimate"
