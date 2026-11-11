from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float
    touched: float


class TokenBucketLimiter:
    def __init__(self, *, rate_per_minute: int, burst: int, clock=time.monotonic):
        self.rate = rate_per_minute / 60.0
        self.burst = float(burst)
        self.clock = clock
        self.buckets: dict[str, _Bucket] = {}
        self.lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = self.clock()
        async with self.lock:
            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self.burst, now, now)
                self.buckets[key] = bucket
            else:
                bucket.tokens = min(self.burst, bucket.tokens + (now - bucket.updated) * self.rate)
                bucket.updated = now
                bucket.touched = now
            if bucket.tokens < 1:
                return False
            bucket.tokens -= 1
            return True

    async def evict(self, idle_seconds: float = 3600) -> None:
        cutoff = self.clock() - idle_seconds
        async with self.lock:
            self.buckets = {k: v for k, v in self.buckets.items() if v.touched >= cutoff}
