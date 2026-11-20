"""Copy all the data to another database, e.g. from SQLite to PostgreSQL."""

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from . import migrate
from .engine import safe_url
from .models import Base

BATCH = 500


class TransferError(Exception):
    """The copy can't start or didn't produce the same data."""


async def count_rows(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        return {table.name: (await conn.execute(select(func.count()).select_from(table)))
                .scalar_one() for table in Base.metadata.sorted_tables}


async def copy_database(source: AsyncEngine, target: AsyncEngine) -> dict[str, int]:
    """
    Copy every row from `source` (at the latest schema) to an empty `target`.
    The target gets the same schema, the same ids and, on PostgreSQL, id sequences that
    continue after the copied rows. Returns the rows copied per table.
    """
    if safe_url(source.url) == safe_url(target.url):
        raise TransferError("source and target are the same database")
    if await migrate.current_revision(source) != migrate.head_revision():
        raise TransferError("start the bot once on the source database first, "
                            "so that it has the latest schema")
    if await migrate.current_revision(target) is not None or await migrate.table_names(target):
        raise TransferError("the target database is not empty")

    copied = {}
    # One transaction on the target: schema and data land together or not at all
    async with source.connect() as src, target.begin() as dst:
        await dst.run_sync(migrate.upgrade_connection)
        for table in Base.metadata.sorted_tables:        # parents before children
            order = list(table.primary_key.columns)
            result = await src.stream(select(table).order_by(*order))
            copied[table.name] = 0
            async for rows in result.mappings().partitions(BATCH):
                await dst.execute(insert(table), [dict(r) for r in rows])
                copied[table.name] += len(rows)
        if target.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:   # tickets.id, notes.id
                column = table.autoincrement_column
                if column is not None:
                    # Names come from our own models, never from user input
                    await dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', "
                        f"'{column.name}'), COALESCE(MAX({column.name}), 0) + 1, false) "
                        f"FROM {table.name}"))

    if await count_rows(target) != copied or await count_rows(source) != copied:
        raise TransferError("the number of rows doesn't match after the copy")
    return copied
