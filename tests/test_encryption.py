"""Encryption of the sensitive text in the database (AES-256-GCM, key rotation)."""

import asyncio
import base64
import os
import sqlite3

import pytest
from conftest import TEST_KEY, SyncStore, new_store

from ticketbot.core import crypto
from ticketbot.db import Store, migrate
from ticketbot.db.encryption import encrypt_pending
from ticketbot.db.engine import create_engine
from ticketbot.db.v2 import create_v2_database

PG_URL = os.getenv("TEST_DATABASE_URL")
SECRET = "My password is hunter2"


@pytest.fixture
def keyring():
    """Restore the test key after a test that changes it."""
    yield
    crypto.configure(crypto.Keyring(TEST_KEY))


def raw(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------- crypto ---

def test_encrypt_decrypt_and_tampering():
    ring = crypto.Keyring(TEST_KEY)
    token = ring.encrypt(SECRET, "tickets.subject")
    assert token.startswith(f"enc:v1:{ring.current_id}:") and SECRET not in token
    assert ring.decrypt(token, "tickets.subject") == SECRET
    assert ring.encrypt(SECRET, "tickets.subject") != token        # random nonce
    with pytest.raises(crypto.CryptoError):                          # moved to another column
        ring.decrypt(token, "notes.text")
    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(crypto.CryptoError):
        ring.decrypt(tampered, "tickets.subject")
    assert ring.decrypt("plain text from v2", "tickets.subject") == "plain text from v2"
    other = crypto.Keyring(os.urandom(32))
    with pytest.raises(crypto.CryptoError, match="ENCRYPTION_OLD_KEYS"):
        other.decrypt(token, "tickets.subject")


def test_keys_are_checked():
    key = crypto.generate_key()
    assert len(crypto.parse_key(key)) == 32
    for bad in ("not base64!", base64.urlsafe_b64encode(b"short").decode()):
        with pytest.raises(ValueError, match="keygen"):
            crypto.parse_key(bad)


# ---------------------------------------------------------- in the store ---

def test_sensitive_columns_are_encrypted_on_disk(db):
    db.save_guild(1)
    tid = db.create_ticket(guild_id=1, channel_id=5, owner_id=2, type_key="bug",
                           type_label="Bug", type_emoji="🐞", subject=SECRET,
                           description="Steps: " + SECRET, opened_at=1.0, last_activity=1.0)
    db.add_note(tid, 3, "staff note " + SECRET, 2.0)
    db.update_ticket(tid, close_reason="reason " + SECRET, rating_comment="ok " + SECRET)
    db.block_user(1, 9, "spam " + SECRET, 3, 1.0, None)

    ticket = db.get_ticket(tid)
    assert ticket["subject"] == SECRET and ticket["rating_comment"] == "ok " + SECRET
    assert db.list_notes(tid)[0]["text"] == "staff note " + SECRET

    with open(db.path, "rb") as f:   # WAL: committed pages may still be in the -wal file
        on_disk = f.read()
    wal = db.path.with_name(db.path.name + "-wal")
    if wal.exists():
        on_disk += wal.read_bytes()
    assert SECRET.encode() not in on_disk
    rows = raw(db.path, "SELECT subject, description, close_reason, rating_comment FROM tickets")
    assert all(v.startswith("enc:v1:") for v in rows[0])
    assert raw(db.path, "SELECT type_label FROM tickets") == [("Bug",)]   # not sensitive


def test_plain_v2_data_is_encrypted_at_start(tmp_path):
    path = tmp_path / "ticketbot.db"
    create_v2_database(path)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("INSERT INTO guilds (guild_id) VALUES (1)")
        conn.execute("INSERT INTO tickets (guild_id, channel_id, owner_id, type_key, "
                     "type_label, type_emoji, subject, description, opened_at, "
                     "last_activity) VALUES (1, 5, 2, 'bug', 'Bug', 'x', ?, ?, 1, 1)",
                     (SECRET, "long form answers " * 400))   # spills into overflow pages
        conn.execute("INSERT INTO notes (ticket_id, author_id, text, created_at) "
                     "VALUES (1, 3, 'note', 1)")
    conn.close()

    async def scenario():
        store = await new_store(path)          # adopts the v2 file
        assert await encrypt_pending(store.engine) == 2     # one ticket, one note
        assert await encrypt_pending(store.engine) == 0     # nothing left
        assert (await store.get_ticket(1))["subject"] == SECRET
        await store.close()

    asyncio.run(scenario())
    assert raw(path, "SELECT subject FROM tickets")[0][0].startswith("enc:v1:")
    # No plain copy left in free pages or in the WAL file
    files = [path, path.with_name(path.name + "-wal")]
    for f in files:
        if f.exists():
            data = f.read_bytes()
            assert SECRET.encode() not in data and b"long form answers" not in data


def test_key_rotation(tmp_path, keyring):
    path = tmp_path / "ticketbot.db"
    db = SyncStore(path)
    db.save_guild(1)
    db.create_ticket(guild_id=1, channel_id=5, owner_id=2, type_key="bug", type_label="Bug",
                     type_emoji="x", subject=SECRET, opened_at=1.0, last_activity=1.0)
    old_id = crypto.key_id(TEST_KEY)

    new_key = os.urandom(32)
    crypto.configure(crypto.Keyring(new_key))                  # old key forgotten
    with pytest.raises(crypto.CryptoError, match="ENCRYPTION_OLD_KEYS"):
        db.get_ticket(1)
    with pytest.raises(crypto.CryptoError):
        db.run(encrypt_pending(db.engine))                     # changes nothing

    crypto.configure(crypto.Keyring(new_key, [TEST_KEY]))      # old key in OLD_KEYS
    assert db.get_ticket(1)["subject"] == SECRET
    assert db.run(encrypt_pending(db.engine)) == 1
    stored = raw(path, "SELECT subject FROM tickets")[0][0]
    assert stored.startswith(f"enc:v1:{crypto.key_id(new_key)}:") and old_id not in stored

    crypto.configure(crypto.Keyring(new_key))                  # old key can go now
    assert db.get_ticket(1)["subject"] == SECRET
    db.close()


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set")
def test_encryption_on_postgresql():
    async def scenario():
        engine = create_engine(PG_URL)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
        await migrate.prepare(engine)
        store = Store(engine)
        await store.save_guild(1)
        tid = await store.create_ticket(guild_id=1, channel_id=5, owner_id=2, type_key="b",
                                        type_label="B", type_emoji="x", subject=SECRET,
                                        opened_at=1.0, last_activity=1.0)
        assert (await store.get_ticket(tid))["subject"] == SECRET
        async with engine.connect() as conn:
            stored = (await conn.exec_driver_sql("SELECT subject FROM tickets")).scalar()
        assert stored.startswith("enc:v1:") and SECRET not in stored
        await store.close()

    asyncio.run(scenario())


# ------------------------------------------------------------- settings ---

def test_settings_and_keygen(tmp_path, monkeypatch, capsys):
    from ticketbot import __main__ as cli
    from ticketbot.core.settings import Settings, SettingsError

    monkeypatch.chdir(tmp_path)
    for name in ("ENCRYPTION_KEY", "ENCRYPTION_OLD_KEYS"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SettingsError, match="keygen"):
        Settings().keyring()

    assert cli.main(["keygen"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    key = line.removeprefix("ENCRYPTION_KEY=")
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    monkeypatch.setenv("ENCRYPTION_OLD_KEYS", base64.urlsafe_b64encode(TEST_KEY).decode())
    settings = Settings()
    ring = settings.keyring()
    assert ring.current_id == crypto.key_id(crypto.parse_key(key))
    assert ("ENCRYPTION_KEY", f"set (id {ring.current_id})") in settings.summary()
    assert key not in repr(settings)

    monkeypatch.setenv("ENCRYPTION_KEY", "too-short")
    with pytest.raises(Exception, match="encryption key"):
        Settings()
