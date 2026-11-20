"""Shared test helpers: a synchronous view of the async Store for short storage tests."""

import asyncio
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ticketbot.db import Store, migrate  # noqa: E402
from ticketbot.db.engine import create_engine  # noqa: E402


class SyncStore:
    """Calls the async Store methods on a private event loop: `db.save_guild(1)` works in
    a plain test function. Async scenarios (the bot itself) use a real Store instead."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.store = Store(create_engine(f"sqlite:///{self.path.as_posix()}"))
        self.run(migrate.prepare(self.store.engine))

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def __getattr__(self, name):
        attr = getattr(self.store, name)
        if inspect.iscoroutinefunction(attr):
            return lambda *args, **kwargs: self.run(attr(*args, **kwargs))
        return attr

    def count(self, table: str) -> int:
        """Rows in a table, read straight from the file."""
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def close(self) -> None:
        self.run(self.store.close())
        self.loop.close()


@pytest.fixture
def db(tmp_path):
    store = SyncStore(tmp_path / "ticketbot.db")
    yield store
    store.close()


async def new_store(path: Path) -> Store:
    """A real Store with the latest schema, inside the running event loop."""
    store = Store(create_engine(f"sqlite:///{Path(path).as_posix()}"))
    await migrate.prepare(store.engine)
    return store


def unused_store() -> Store:
    """For tests that build the bot without touching the database."""
    return Store(create_engine("sqlite:///:memory:"))
