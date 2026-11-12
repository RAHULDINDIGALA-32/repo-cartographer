"""Production ASGI launcher with Windows psycopg event-loop compatibility."""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        # Uvicorn's CLI and asyncio.run() can create a Proactor loop before
        # application startup. Psycopg's async pool rejects that loop. An
        # explicit Runner makes the loop choice authoritative for the server.
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve())
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
