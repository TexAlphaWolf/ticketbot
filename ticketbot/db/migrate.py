"""Run the Alembic migrations from Python (no alembic.ini needed)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

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
