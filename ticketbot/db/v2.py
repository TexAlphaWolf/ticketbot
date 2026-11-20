"""
The v2.x SQLite schema, kept to recognise and adopt databases made by TicketBot 2.

A v2.3 file is adopted as migration 0001 (same tables); files from v2.0-v2.2 first get
the columns those versions were missing, as TicketBot 2 itself did at startup.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id           INTEGER PRIMARY KEY,
    language           TEXT    NOT NULL DEFAULT 'en',
    staff_role         INTEGER,
    category           INTEGER,
    log_channel        INTEGER,
    archive_channel    INTEGER,
    panel_channel      INTEGER,
    panel_message      INTEGER,
    guidelines_channel INTEGER,
    guidelines_message INTEGER,
    counter            INTEGER NOT NULL DEFAULT 0,
    retention_days     INTEGER NOT NULL DEFAULT 30,
    telegram_chat_id   TEXT,
    staff_reminders    INTEGER NOT NULL DEFAULT 1,
    ticket_cooldown    INTEGER NOT NULL DEFAULT 0,
    auto_assign        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_types (
    guild_id    INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    key         TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    emoji       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS tickets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id          INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id        INTEGER UNIQUE,
    number            INTEGER,
    user_number       INTEGER,
    name              TEXT,
    owner_id          INTEGER NOT NULL,
    type_key          TEXT    NOT NULL,
    type_label        TEXT    NOT NULL,
    type_emoji        TEXT    NOT NULL,
    subject           TEXT,
    description       TEXT,
    status            TEXT    NOT NULL DEFAULT 'waiting',
    priority          TEXT,
    claimed_by        INTEGER,
    assigned_to       INTEGER,
    control_message   INTEGER,
    opened_at         REAL    NOT NULL,
    first_response_at REAL,
    last_actor        TEXT,
    last_activity     REAL    NOT NULL,
    warned            INTEGER NOT NULL DEFAULT 0,
    awaiting_staff_since REAL,
    staff_reminded_at REAL,
    closed_at         REAL,
    closed_by         INTEGER,
    close_reason      TEXT,
    channel_deleted   INTEGER NOT NULL DEFAULT 0,
    rating            INTEGER,
    rating_comment    TEXT,
    rated_at          REAL
);
CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS type_questions (
    guild_id    INTEGER NOT NULL,
    type_key    TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    label       TEXT    NOT NULL,
    placeholder TEXT    NOT NULL DEFAULT '',
    long        INTEGER NOT NULL DEFAULT 0,
    required    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, type_key, position),
    FOREIGN KEY (guild_id, type_key) REFERENCES ticket_types(guild_id, key)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS replies (
    guild_id INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    name     TEXT    NOT NULL,
    content  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS staff_availability (
    guild_id         INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id          INTEGER NOT NULL,
    last_assigned_at REAL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS blocked_users (
    guild_id   INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    reason     TEXT,
    blocked_by INTEGER NOT NULL,
    blocked_at REAL    NOT NULL,
    until      REAL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS transcript_refs (
    guild_id   INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    priority   TEXT,
    closed_at  REAL    NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);
"""

# Columns added during v2.x, with their SQLite definition
V2_ADDED_COLUMNS = {
    "tickets": (("user_number", "INTEGER"), ("name", "TEXT"),
                ("awaiting_staff_since", "REAL"), ("staff_reminded_at", "REAL"),
                ("assigned_to", "INTEGER")),
    "guilds": (("staff_reminders", "INTEGER NOT NULL DEFAULT 1"),
               ("ticket_cooldown", "INTEGER NOT NULL DEFAULT 0"),
               ("auto_assign", "INTEGER NOT NULL DEFAULT 0")),
}


def complete_v2_schema(conn) -> list[str]:
    """Bring a v2.0-v2.2 database to the v2.3 schema. Works on a sqlite3 connection or a
    SQLAlchemy one. Returns the columns that were added."""
    run = getattr(conn, "exec_driver_sql", None) or conn.execute
    for statement in SCHEMA.split(";"):          # tables added during v2.x
        if statement.strip():
            run(statement)
    added = []
    for table, columns in V2_ADDED_COLUMNS.items():
        existing = {row[1] for row in run(f"PRAGMA table_info({table})").fetchall()}
        for column, kind in columns:
            if column not in existing:
                run(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                added.append(f"{table}.{column}")
    return added


def create_v2_database(path: str | Path) -> None:
    """An empty v2.3 database, as TicketBot 2.3 created it (for tests and tools)."""
    conn = sqlite3.connect(path)
    with conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version = 1")
    conn.close()
