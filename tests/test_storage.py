"""V3 storage: SQLAlchemy models, Alembic migrations, SQLite and PostgreSQL.

PostgreSQL tests run when TEST_DATABASE_URL points to an empty test database
(GitHub Actions starts one), e.g. postgresql://tb:tb@localhost:5432/ticketbot_test.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ticketbot.db import migrate  # noqa: E402
from ticketbot.db.engine import (  # noqa: E402
    create_engine,
    normalize_url,
    safe_url,
    session_factory,
)
from ticketbot.db.models import Base, Guild, Note, Ticket, TicketType, TypeQuestion  # noqa: E402
from ticketbot.db.v2 import create_v2_database  # noqa: E402

BIG_ID = 1563556506434019338          # Discord IDs don't fit in 32 bits
PG_URL = os.getenv("TEST_DATABASE_URL")


def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'ticketbot.db').as_posix()}"


@pytest.fixture(params=["sqlite", "postgresql"])
def url(request, tmp_path):
    if request.param == "sqlite":
        return sqlite_url(tmp_path)
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    asyncio.run(_reset_postgres(PG_URL))
    return PG_URL


async def _reset_postgres(url: str) -> None:
    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        await conn.exec_driver_sql("CREATE SCHEMA public")
    await engine.dispose()


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ URLs ---

def test_urls_get_the_async_driver_and_hide_the_password():
    assert str(normalize_url("sqlite:///data/x.db")) == "sqlite+aiosqlite:///data/x.db"
    assert normalize_url("postgresql://u:p@h/db").drivername == "postgresql+asyncpg"
    assert normalize_url("postgres://u:p@h/db").drivername == "postgresql+asyncpg"
    assert safe_url("postgresql://tb:secret@db:5432/tickets") == \
        "postgresql+asyncpg://tb:***@db:5432/tickets"
    with pytest.raises(ValueError, match="unsupported database"):
        normalize_url("mysql://u:p@h/db")


# ------------------------------------------------------------ migrations ---

async def _schema_diff(engine) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda c: compare_metadata(
                MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata))


def test_migrations_build_exactly_the_models(url):
    async def scenario():
        engine = create_engine(url)
        try:
            await migrate.upgrade(engine)
            assert await migrate.current_revision(engine) == migrate.head_revision()
            assert await _schema_diff(engine) == []      # models and migrations agree
            await migrate.downgrade(engine, "base")
            assert await _table_names(engine) <= {"alembic_version"}
        finally:
            await engine.dispose()

    run(scenario())


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


def _foreign_keys(sync_conn, table: str) -> list:
    """(columns, table, columns, ON DELETE) read with PRAGMA: SQLAlchemy's SQLite
    reflection misses ON DELETE on inline REFERENCES, like the ones of the v2 schema."""
    keys: dict[int, list] = {}
    for row in sync_conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})"):
        fk_id, _seq, referred, column, referred_column, _upd, on_delete = row[:7]
        entry = keys.setdefault(fk_id, [[], referred, [], on_delete])
        entry[0].append(column)
        entry[2].append(referred_column)
    return sorted((tuple(c), t, tuple(r), d) for c, t, r, d in keys.values())


def _structure(sync_conn) -> dict:
    """Tables, columns, nullability, keys and indexes: what stamping a v2 file relies on."""
    insp = inspect(sync_conn)
    out = {}
    for table in insp.get_table_names():
        if table == "alembic_version":
            continue
        out[table] = {
            "columns": {c["name"]: c["nullable"] or c.get("primary_key", 0) > 0
                        for c in insp.get_columns(table)},
            "pk": sorted(insp.get_pk_constraint(table)["constrained_columns"]),
            "fks": _foreign_keys(sync_conn, table),
            "indexes": sorted(tuple(i["column_names"]) for i in insp.get_indexes(table)),
            "unique": sorted(tuple(u["column_names"])
                             for u in insp.get_unique_constraints(table)),
        }
    return out


def test_first_migration_is_the_v2_3_schema(tmp_path):
    """A v2.3 database has the same tables, columns and keys as migration 0001."""
    legacy = tmp_path / "legacy.db"
    create_v2_database(legacy)

    def structure(url):
        async def go():
            engine = create_engine(url)
            async with engine.connect() as conn:
                result = await conn.run_sync(_structure)
            await engine.dispose()
            return result
        return run(go())

    engine = create_engine(sqlite_url(tmp_path))
    run(migrate.upgrade(engine, "0001"))
    run(engine.dispose())
    v2 = structure(f"sqlite:///{legacy.as_posix()}")
    v3 = structure(sqlite_url(tmp_path))
    assert v2.keys() == v3.keys()
    for table in v2:
        # SQLite reports an INTEGER PRIMARY KEY column as nullable: compare names there
        assert v2[table]["columns"].keys() == v3[table]["columns"].keys(), table
        for key in ("pk", "fks", "indexes", "unique"):
            assert v2[table][key] == v3[table][key], (table, key)


# ---------------------------------------------------------------- models ---

def test_models_store_big_ids_and_cascade(url):
    async def scenario():
        engine = create_engine(url)
        await migrate.upgrade(engine)
        session_maker = session_factory(engine)
        async with session_maker() as s:
            s.add(Guild(guild_id=BIG_ID, staff_role=BIG_ID + 1))
            await s.flush()
            s.add(TicketType(guild_id=BIG_ID, key="bug", label="Bug", emoji="🐞"))
            await s.flush()
            s.add(TypeQuestion(guild_id=BIG_ID, type_key="bug", position=0, label="Version"))
            ticket = Ticket(guild_id=BIG_ID, channel_id=BIG_ID + 2, owner_id=BIG_ID + 3,
                            type_key="bug", type_label="Bug", type_emoji="🐞",
                            opened_at=1_000.5, last_activity=1_000.5)
            s.add(ticket)
            await s.flush()
            s.add(Note(ticket_id=ticket.id, author_id=BIG_ID, text="ok", created_at=1.0))
            await s.commit()

        async with session_maker() as s:
            guild = await s.get(Guild, BIG_ID)
            assert guild.language == "en" and guild.staff_reminders is True
            assert guild.auto_assign is False and guild.retention_days == 30
            saved = (await s.scalars(select(Ticket))).one()
            assert saved.owner_id == BIG_ID + 3 and saved.status == "waiting"
            assert saved.warned is False and saved.opened_at == 1_000.5
            question = (await s.scalars(select(TypeQuestion))).one()
            assert question.required is True and question.long is False

            await s.delete(guild)          # removing a server removes all its data
            await s.commit()
        async with session_maker() as s:
            for model in (TicketType, TypeQuestion, Ticket, Note):
                assert (await s.scalars(select(model))).all() == [], model.__name__
        await engine.dispose()

    run(scenario())


def test_ticket_ids_are_never_reused(tmp_path):
    async def scenario():
        engine = create_engine(sqlite_url(tmp_path))
        await migrate.upgrade(engine)
        session_maker = session_factory(engine)
        async with session_maker() as s:
            s.add(Guild(guild_id=1))
            await s.flush()
            fields = dict(guild_id=1, owner_id=2, type_key="t", type_label="T",
                          type_emoji="x", opened_at=0.0, last_activity=0.0)
            first = Ticket(**fields)
            s.add(first)
            await s.commit()
            first_id = first.id
            await s.delete(first)
            await s.commit()
            second = Ticket(**fields)
            s.add(second)
            await s.commit()
            assert second.id > first_id
        await engine.dispose()

    run(scenario())


def test_stamp_adopts_an_existing_v2_database(tmp_path):
    """Step 5 adopts v2.3 files this way: no copy, the data stays where it is."""
    import sqlite3

    path = tmp_path / "ticketbot.db"
    create_v2_database(path)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("INSERT INTO guilds (guild_id, language) VALUES (?, 'it')", (BIG_ID,))
    conn.close()

    async def scenario():
        engine = create_engine(sqlite_url(tmp_path))
        assert await migrate.current_revision(engine) is None
        await migrate.stamp(engine, "0001")
        await migrate.upgrade(engine)
        assert await migrate.current_revision(engine) == migrate.head_revision()
        async with session_factory(engine)() as s:
            guild = await s.get(Guild, BIG_ID)
            assert guild.language == "it" and guild.staff_reminders is True
        await engine.dispose()

    run(scenario())


# ----------------------------------------------------------------- store ---

def test_store_works_the_same_on_both_databases(url):
    """The queries that differ between SQLite and PostgreSQL (upserts, RETURNING...)."""
    from ticketbot.db import Store

    async def scenario():
        store = Store(create_engine(url))
        await migrate.prepare(store.engine)
        g = BIG_ID
        assert (await store.save_guild(g, language="de"))["language"] == "de"
        assert (await store.save_guild(g))["language"] == "de"          # no overwrite
        assert [await store.next_ticket_number(g) for _ in range(2)] == [1, 2]

        await store.add_type(g, "bug", "Bug", "🐞")
        await store.add_type(g, "pay", "Pay", "💳")
        assert [t["key"] for t in await store.list_types(g)] == ["bug", "pay"]
        for label in ("A", "B", "C"):
            await store.add_question(g, "bug", label)
        assert await store.remove_question(g, "bug", 1)
        assert [(q["position"], q["label"]) for q in await store.list_questions(g, "bug")] \
            == [(1, "B"), (2, "C")]

        fields = dict(guild_id=g, owner_id=BIG_ID + 9, type_key="bug", type_label="Bug",
                      type_emoji="🐞", opened_at=1.0, last_activity=1.0)
        first = await store.create_ticket(channel_id=g + 1, assigned_to=7, **fields)
        await store.create_ticket(channel_id=g + 2, claimed_by=8, status="in_progress",
                                  **fields)
        assert await store.queue_counts(g) == (1, 1)
        assert await store.open_tickets_per_staff(g) == {7: 1, 8: 1}
        assert (await store.open_ticket_of_owner(g, BIG_ID + 9))["owner_id"] == BIG_ID + 9
        await store.update_ticket(first, warned=True, status="closed", closed_at=5.0)
        await store.mark_channel_deleted(first)
        ticket = await store.get_ticket(first)
        assert ticket["warned"] is True and ticket["channel_deleted"] is True
        assert await store.purge_closed_before(10.0) == 1

        for _ in range(2):                                               # upserts
            await store.set_available(g, 5, True)
        await store.block_user(g, 6, "spam", 1, 1.0, None)
        await store.block_user(g, 6, "again", 1, 2.0, 100.0)
        await store.save_reply(g, "Logs", "one")
        await store.save_reply(g, "logs", "two")
        await store.add_transcript_ref(g, 1, 2, "low", 1.0)
        await store.add_transcript_ref(g, 1, 2, "high", 2.0)
        assert len(await store.available_staff(g)) == 1
        assert (await store.get_block(g, 6, 50.0))["reason"] == "again"
        assert await store.get_block(g, 6, 100.0) is None
        assert [r["content"] for r in await store.list_replies(g)] == ["two"]
        assert [r["priority"] for r in await store.transcript_refs(g)] == ["high"]

        assert await store.delete_guild(g)
        assert await store.guild_ids() == []
        await store.close()

    run(scenario())


def test_prepare_creates_adopts_and_reports(tmp_path):
    from ticketbot.db.backup import list_backups

    async def scenario():
        fresh = create_engine(sqlite_url(tmp_path))
        assert await migrate.prepare(fresh, tmp_path / "backups") == "created"
        assert await migrate.prepare(fresh, tmp_path / "backups") == "up to date"
        await fresh.dispose()
        assert list_backups(tmp_path / "backups") == []          # nothing to protect yet

        legacy = tmp_path / "old" / "ticketbot.db"
        legacy.parent.mkdir()
        create_v2_database(legacy)
        engine = create_engine(f"sqlite:///{legacy.as_posix()}")
        status = await migrate.prepare(engine, tmp_path / "old-backups")
        assert status.startswith("adopted the TicketBot 2 database (backup: ticketbot-")
        assert await migrate.current_revision(engine) == migrate.head_revision()
        await engine.dispose()
        assert len(list_backups(tmp_path / "old-backups")) == 1

    run(scenario())


# -------------------------------------------------------------- transfer ---

async def _fill(store):
    g = BIG_ID
    await store.save_guild(g, language="it", telegram_chat_id="-100123")
    await store.ensure_default_types(g, [("bug", "Bug", "🐞", "")])
    await store.add_question(g, "bug", "Version", long=True)
    fields = dict(guild_id=g, owner_id=BIG_ID + 9, type_key="bug", type_label="Bug",
                  type_emoji="🐞", opened_at=1.0, last_activity=1.0)
    first = await store.create_ticket(channel_id=g + 1, **fields)
    second = await store.create_ticket(channel_id=g + 2, **fields)
    await store.update_ticket(first, status="closed", closed_at=2.0, rating=5)
    await store.add_note(second, 7, "nota", 3.0)
    await store.save_reply(g, "logs", "Send the logs")
    await store.set_available(g, 8, True)
    await store.block_user(g, 9, "spam", 7, 1.0, None)
    await store.add_transcript_ref(g, 1, 2, "low", 2.0)
    return second


def test_copy_to_another_database(url, tmp_path):
    from ticketbot.db import Store
    from ticketbot.db.transfer import TransferError, copy_database, count_rows

    async def scenario():
        source = Store(create_engine(f"sqlite:///{(tmp_path / 'source.db').as_posix()}"))
        await migrate.prepare(source.engine)
        last_id = await _fill(source)
        target_url = url if "postgresql" in url else \
            f"sqlite:///{(tmp_path / 'target.db').as_posix()}"
        target = Store(create_engine(target_url))

        copied = await copy_database(source.engine, target.engine)
        assert copied["tickets"] == 2 and copied["notes"] == 1 and copied["guilds"] == 1
        assert await count_rows(target.engine) == copied
        assert await migrate.current_revision(target.engine) == migrate.head_revision()

        guild = await target.get_guild(BIG_ID)
        assert guild["language"] == "it" and guild["telegram_chat_id"] == "-100123"
        assert (await target.list_questions(BIG_ID, "bug"))[0]["long"] is True
        assert (await target.get_ticket(last_id))["owner_id"] == BIG_ID + 9   # same ids
        new_id = await target.create_ticket(                                  # ids go on
            guild_id=BIG_ID, channel_id=BIG_ID + 3, owner_id=1, type_key="bug",
            type_label="Bug", type_emoji="🐞", opened_at=4.0, last_activity=4.0)
        assert new_id > last_id

        with pytest.raises(TransferError, match="not empty"):
            await copy_database(source.engine, target.engine)
        with pytest.raises(TransferError, match="same database"):
            await copy_database(source.engine, source.engine)
        await source.close()
        await target.close()

    run(scenario())


def test_db_commands(tmp_path, monkeypatch, capsys):
    from ticketbot import __main__ as cli
    from ticketbot.core.settings import get_settings

    monkeypatch.chdir(tmp_path)
    for name in ("DATABASE_URL", "DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        async def make():
            engine = create_engine(sqlite_url(tmp_path / "data"))
            await migrate.prepare(engine)
            await engine.dispose()
        (tmp_path / "data").mkdir()
        run(make())
        assert cli.main(["db", "status"]) == 0
        out = capsys.readouterr().out
        assert "sqlite+aiosqlite:///data/ticketbot.db" in out and "(latest)" in out

        target = f"sqlite:///{(tmp_path / 'copy.db').as_posix()}"
        assert cli.main(["db", "copy", target, "--yes"]) == 0
        assert "the row counts match" in capsys.readouterr().out
        assert cli.main(["db", "copy", target, "--yes"]) == 1
        assert "not empty" in capsys.readouterr().out
        assert cli.main(["db", "copy", "mysql://x@y/z", "--yes"]) == 2
        # The question comes before any database is opened (Windows: no input() inside
        # the event loop)
        other = f"sqlite:///{(tmp_path / 'other.db').as_posix()}"
        monkeypatch.setattr("builtins.input", lambda _prompt: "no")
        assert cli.main(["db", "copy", other]) == 1
        assert "Copy cancelled" in capsys.readouterr().out
        assert not (tmp_path / "other.db").exists()
        monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
        assert cli.main(["db", "copy", other]) == 0
    finally:
        get_settings.cache_clear()
