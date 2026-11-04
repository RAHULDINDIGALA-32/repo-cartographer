"""Asyncio helpers for psycopg's Windows-compatible selector loop."""

import asyncio
import sys


def run_async(coro):
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coro)
    return asyncio.run(coro)
