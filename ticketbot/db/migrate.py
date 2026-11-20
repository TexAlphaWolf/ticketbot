"""Run the Alembic migrations from Python (no alembic.ini needed)."""

import asyncio
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from .backup import create_backup
from .v2 import complete_v2_schema

MIGRATIONS = Path(__file__).with_name("migrations")


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


async def upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.upgrade(alembic_config(c), revision))


async def downgrade(engine: AsyncEngine, revision: str) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(alembic_config(c), revision))


async def stamp(engine: AsyncEngine, revision: str) -> None:
    """Mark the database as already at `revision` without running anything."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.stamp(alembic_config(c), revision))


async def current_revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda c: MigrationContext.configure(c).get_current_revision())


async def _tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


def _sqlite_file(engine: AsyncEngine) -> Path | None:
    database = engine.url.database
    if engine.dialect.name != "sqlite" or not database or database == ":memory:":
        return None
    return Path(database)


async def prepare(engine: AsyncEngine, backup_dir: Path | None = None) -> str:
    """
    Bring the database to the latest schema and say what was done:
    a new database is created, a TicketBot 2 database is adopted (after a backup),
    an older V3 database is migrated (after a backup).
    """
    head = head_revision()
    revision = await current_revision(engine)
    if revision == head:
        return "up to date"

    tables = await _tables(engine) - {"alembic_version"}
    file = _sqlite_file(engine)
    note = ""
    if tables and file is not None and file.exists() and backup_dir is not None:
        def copy() -> Path:
            source = sqlite3.connect(file)
            try:
                return create_backup(source, backup_dir)
            finally:
                source.close()
        note = f" (backup: {(await asyncio.to_thread(copy)).name})"

    if revision is None and "guilds" in tables:
        if engine.dialect.name != "sqlite":
            raise RuntimeError("the database has tables but no migration history: "
                               "use an empty PostgreSQL database")
        async with engine.begin() as conn:
            added = await conn.run_sync(complete_v2_schema)
        await stamp(engine, "0001")
        await upgrade(engine)
        extra = f", added {len(added)} missing v2 column(s)" if added else ""
        return f"adopted the TicketBot 2 database{extra}{note}"

    if revision is None:
        await upgrade(engine)
        return "created"
    await upgrade(engine)
    return f"migrated from {revision} to {head}{note}"
