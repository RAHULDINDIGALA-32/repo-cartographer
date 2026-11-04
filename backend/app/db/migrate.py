from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core.errors import MigrationError


class MigrationRunner:
    def __init__(self, db, directory: str | Path, *, schema: str, embedding_dim: int):
        self.db = db
        self.directory = Path(directory)
        self.schema = schema
        self.embedding_dim = embedding_dim

    def files(self):
        result = []
        seen = set()
        for path in sorted(self.directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(path.name[:4])
            if version in seen:
                raise MigrationError(f"Duplicate migration version: {version}")
            seen.add(version)
            result.append((version, path))
        if [v for v, _ in result] != list(range(len(result))):
            raise MigrationError("Migration versions must be contiguous from 0000")
        return result

    def rendered(self, path):
        raw = path.read_text(encoding="utf-8")
        if re.search(r"{{(?!SCHEMA}}|EMBEDDING_DIM}})", raw):
            raise MigrationError(f"Unsupported placeholder in {path.name}")
        return raw.replace("{{SCHEMA}}", self.schema).replace(
            "{{EMBEDDING_DIM}}", str(self.embedding_dim)
        ), hashlib.sha256(raw.encode()).hexdigest()

    async def run(self):
        files = self.files()
        applied = []
        async with self.db.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"cartographer:migrations:{self.schema}",),
                )
                await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
                await conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {self.schema}.schema_migrations ("
                    "version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL, "
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                )
                rows = await conn.execute(
                    f"SELECT version, checksum FROM {self.schema}.schema_migrations"
                )
                existing = {r[0]: r[1] for r in await rows.fetchall()}
                for version, path in files:
                    rendered, checksum = self.rendered(path)
                    if version in existing:
                        if existing[version] != checksum:
                            raise MigrationError(f"Checksum mismatch for {path.name}")
                        continue
                    try:
                        await conn.execute(rendered)
                        await conn.execute(
                            f"INSERT INTO {self.schema}.schema_migrations(version,name,checksum) "
                            "VALUES (%s,%s,%s)",
                            (version, path.name, checksum),
                        )
                        applied.append(version)
                    except Exception as exc:
                        raise MigrationError(f"Migration {path.name} failed: {exc}") from exc
        return applied

    async def status(self):
        files = self.files()
        async with self.db.connection() as conn:
            cur = await conn.execute(
                f"SELECT version,name,checksum FROM {self.schema}.schema_migrations "
                "ORDER BY version"
            )
            existing = {r[0]: r for r in await cur.fetchall()}
        return {
            "applied": list(existing.values()),
            "pending": [p.name for v, p in files if v not in existing],
        }
