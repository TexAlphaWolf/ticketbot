"""Async database engine and sessions for SQLite (default) and PostgreSQL."""

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Driver used when the URL in .env names only the database
ASYNC_DRIVERS = {"sqlite": "sqlite+aiosqlite", "postgresql": "postgresql+asyncpg",
                 "postgres": "postgresql+asyncpg"}
SUPPORTED = {"sqlite+aiosqlite", "postgresql+asyncpg"}


def normalize_url(url: str | URL) -> URL:
    """`sqlite:///data/x.db` → `sqlite+aiosqlite:///data/x.db`, same for postgresql://."""
    parsed = make_url(url)
    driver = ASYNC_DRIVERS.get(parsed.drivername, parsed.drivername)
    if driver not in SUPPORTED:
        raise ValueError(f"unsupported database '{parsed.drivername}': "
                         "use sqlite:///path/to/file.db or postgresql://user:password@host/db")
    return parsed.set(drivername=driver)


def safe_url(url: str | URL) -> str:
    """The URL with the password hidden, for logs and `python -m ticketbot settings`."""
    return normalize_url(url).render_as_string(hide_password=True)


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")    # ON DELETE CASCADE needs it on SQLite
    cursor.execute("PRAGMA busy_timeout = 5000")  # bot and web API share the file
    cursor.execute("PRAGMA journal_mode = WAL")   # readers don't block the writer
    cursor.execute("PRAGMA secure_delete = ON")   # overwrite deleted data with zeros
    cursor.close()


def create_engine(url: str | URL, **kwargs) -> AsyncEngine:
    url = normalize_url(url)
    if url.get_backend_name() == "sqlite":
        engine = create_async_engine(url, **kwargs)
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
        return engine
    return create_async_engine(url, pool_pre_ping=True, **kwargs)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit (no lazy reload in async)
    return async_sessionmaker(engine, expire_on_commit=False)
