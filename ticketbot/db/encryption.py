"""Keep every sensitive value encrypted with the current key."""

from sqlalchemy import Text, and_, or_, select, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncEngine

from ..core import crypto
from .models import Base
from .types import EncryptedText


def encrypted_columns() -> dict:
    """{table: [encrypted columns]} for every table that has some."""
    found = {}
    for table in Base.metadata.sorted_tables:
        columns = [c for c in table.columns if isinstance(c.type, EncryptedText)]
        if columns:
            found[table] = columns
    return found


async def encrypt_pending(engine: AsyncEngine) -> int:
    """
    Encrypt plain values (from TicketBot 2) and re-encrypt values made with an older key.
    Runs at every start; returns the number of rows changed (0 when all is up to date).
    """
    current = f"{crypto.PREFIX}{crypto.active().current_id}:%"
    changed = 0
    async with engine.begin() as conn:
        for table, columns in encrypted_columns().items():
            raw = [type_coerce(c, Text()) for c in columns]   # the stored text, as is
            pending = or_(*[and_(r.is_not(None), r.not_like(current)) for r in raw])
            keys = list(table.primary_key.columns)
            rows = (await conn.execute(select(*keys, *columns).where(pending))).all()
            for row in rows:
                data = row._mapping
                where = [k == data[k.name] for k in keys]
                await conn.execute(update(table).where(*where)
                                   .values({c.name: data[c.name] for c in columns}))
            changed += len(rows)
    if changed and engine.dialect.name == "sqlite":
        await _rewrite_sqlite_file(engine)
    return changed


async def _rewrite_sqlite_file(engine: AsyncEngine) -> None:
    """SQLite keeps old page contents in free pages and in the WAL file: rewrite the file
    so that no plain copy of the values just encrypted stays on disk."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        await conn.exec_driver_sql("VACUUM")
        await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
