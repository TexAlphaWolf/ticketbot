"""SQLite storage for servers, ticket types, tickets, staff notes and transcripts."""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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
    telegram_chat_id   TEXT
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
    control_message   INTEGER,
    opened_at         REAL    NOT NULL,
    first_response_at REAL,
    last_actor        TEXT,
    last_activity     REAL    NOT NULL,
    warned            INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS replies (
    guild_id INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    name     TEXT    NOT NULL,
    content  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, name)
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

GUILD_FIELDS = {
    "language", "staff_role", "category", "log_channel", "archive_channel",
    "panel_channel", "panel_message", "guidelines_channel", "guidelines_message",
    "counter", "retention_days", "telegram_chat_id",
}
TYPE_FIELDS = {"label", "emoji", "description", "position"}
TICKET_FIELDS = {
    "guild_id", "channel_id", "number", "user_number", "name", "owner_id", "type_key",
    "type_label",
    "type_emoji", "subject", "description", "status", "priority", "claimed_by",
    "control_message", "opened_at", "first_response_at", "last_actor",
    "last_activity", "warned", "closed_at", "closed_by", "close_reason",
    "channel_deleted", "rating", "rating_comment", "rated_at",
}


def _check(fields: dict, allowed: set) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")


class Database:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._upgrade()
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def _upgrade(self) -> None:
        """Add columns introduced after a database was first created."""
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(tickets)")}
        for column, kind in (("user_number", "INTEGER"), ("name", "TEXT")):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {kind}")

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------- helpers ---

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.conn:
            return self.conn.execute(sql, params)

    # ----------------------------------------------------------- guilds ---

    def get_guild(self, guild_id: int) -> dict | None:
        return self._one("SELECT * FROM guilds WHERE guild_id = ?", (guild_id,))

    def guild_ids(self) -> list[int]:
        return [r["guild_id"] for r in self._all("SELECT guild_id FROM guilds")]

    def save_guild(self, guild_id: int, **fields) -> dict:
        _check(fields, GUILD_FIELDS)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (guild_id,))
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                self.conn.execute(f"UPDATE guilds SET {cols} WHERE guild_id = ?",
                                  (*fields.values(), guild_id))
        return self.get_guild(guild_id)

    def delete_guild(self, guild_id: int) -> bool:
        return self._write("DELETE FROM guilds WHERE guild_id = ?", (guild_id,)).rowcount > 0

    def next_ticket_number(self, guild_id: int) -> int:
        with self.conn:
            self.conn.execute("UPDATE guilds SET counter = counter + 1 WHERE guild_id = ?",
                              (guild_id,))
            return self.conn.execute("SELECT counter FROM guilds WHERE guild_id = ?",
                                     (guild_id,)).fetchone()[0]

    def next_user_number(self, guild_id: int, owner_id: int) -> int:
        """Progressive number of the tickets opened by one user in a server."""
        row = self.conn.execute(
            "SELECT COALESCE(MAX(user_number), 0) + 1 FROM tickets "
            "WHERE guild_id = ? AND owner_id = ?", (guild_id, owner_id)).fetchone()
        return row[0]

    # ----------------------------------------------------- ticket types ---

    def list_types(self, guild_id: int) -> list[dict]:
        return self._all("SELECT * FROM ticket_types WHERE guild_id = ? "
                         "ORDER BY position, rowid", (guild_id,))

    def get_type(self, guild_id: int, key: str) -> dict | None:
        return self._one("SELECT * FROM ticket_types WHERE guild_id = ? AND key = ?",
                         (guild_id, key))

    def add_type(self, guild_id: int, key: str, label: str, emoji: str,
                 description: str = "") -> None:
        with self.conn:
            pos = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM ticket_types WHERE guild_id = ?",
                (guild_id,)).fetchone()[0]
            self.conn.execute(
                "INSERT INTO ticket_types (guild_id, key, label, emoji, description, position) "
                "VALUES (?, ?, ?, ?, ?, ?)", (guild_id, key, label, emoji, description, pos))

    def update_type(self, guild_id: int, key: str, **fields) -> None:
        _check(fields, TYPE_FIELDS)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            self._write(f"UPDATE ticket_types SET {cols} WHERE guild_id = ? AND key = ?",
                        (*fields.values(), guild_id, key))

    def remove_type(self, guild_id: int, key: str) -> bool:
        return self._write("DELETE FROM ticket_types WHERE guild_id = ? AND key = ?",
                           (guild_id, key)).rowcount > 0

    def ensure_default_types(self, guild_id: int, defaults: list[tuple]) -> None:
        if not self.list_types(guild_id):
            for key, label, emoji, description in defaults:
                self.add_type(guild_id, key, label, emoji, description)

    # ---------------------------------------------------------- tickets ---

    def create_ticket(self, **fields) -> int:
        _check(fields, TICKET_FIELDS)
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self._write(f"INSERT INTO tickets ({cols}) VALUES ({marks})",
                           tuple(fields.values())).lastrowid

    def get_ticket(self, ticket_id: int) -> dict | None:
        return self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))

    def ticket_by_channel(self, channel_id: int) -> dict | None:
        return self._one("SELECT * FROM tickets WHERE channel_id = ? AND channel_deleted = 0",
                         (channel_id,))

    def update_ticket(self, ticket_id: int, **fields) -> None:
        _check(fields, TICKET_FIELDS)
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            self._write(f"UPDATE tickets SET {cols} WHERE id = ?", (*fields.values(), ticket_id))

    def open_ticket_of_owner(self, guild_id: int, owner_id: int) -> dict | None:
        return self._one("SELECT * FROM tickets WHERE guild_id = ? AND owner_id = ? "
                         "AND status != 'closed' AND channel_deleted = 0",
                         (guild_id, owner_id))

    def queue_counts(self, guild_id: int) -> tuple[int, int]:
        """(waiting, in_progress) among the open tickets of a server."""
        rows = self._all("SELECT status, COUNT(*) AS n FROM tickets WHERE guild_id = ? "
                         "AND status != 'closed' AND channel_deleted = 0 GROUP BY status",
                         (guild_id,))
        counts = {r["status"]: r["n"] for r in rows}
        return counts.get("waiting", 0), counts.get("in_progress", 0)

    def active_tickets(self) -> list[dict]:
        return self._all("SELECT * FROM tickets WHERE status != 'closed' AND channel_deleted = 0")

    def closed_channels_due(self, closed_before: float) -> list[dict]:
        return self._all("SELECT * FROM tickets WHERE status = 'closed' AND channel_deleted = 0 "
                         "AND closed_at <= ?", (closed_before,))

    def mark_channel_deleted(self, ticket_id: int) -> None:
        """The channel is gone: forget the content, keep the metadata for /stats."""
        self._write("UPDATE tickets SET channel_deleted = 1, subject = NULL, description = NULL "
                    "WHERE id = ?", (ticket_id,))
        self._write("DELETE FROM notes WHERE ticket_id = ?", (ticket_id,))

    def tickets_since(self, guild_id: int, since: float) -> list[dict]:
        return self._all("SELECT * FROM tickets WHERE guild_id = ? AND opened_at >= ?",
                         (guild_id, since))

    def purge_closed_before(self, before: float) -> int:
        return self._write("DELETE FROM tickets WHERE status = 'closed' AND channel_deleted = 1 "
                           "AND closed_at < ?", (before,)).rowcount

    # ------------------------------------------------------------ notes ---

    def add_note(self, ticket_id: int, author_id: int, text: str, created_at: float) -> None:
        self._write("INSERT INTO notes (ticket_id, author_id, text, created_at) "
                    "VALUES (?, ?, ?, ?)", (ticket_id, author_id, text, created_at))

    def list_notes(self, ticket_id: int) -> list[dict]:
        return self._all("SELECT * FROM notes WHERE ticket_id = ? ORDER BY created_at",
                         (ticket_id,))

    # ---------------------------------------------------- quick replies ---

    def list_replies(self, guild_id: int) -> list[dict]:
        return self._all("SELECT * FROM replies WHERE guild_id = ? ORDER BY name", (guild_id,))

    def get_reply(self, guild_id: int, name: str) -> dict | None:
        return self._one("SELECT * FROM replies WHERE guild_id = ? AND name = ?",
                         (guild_id, name.lower()))

    def save_reply(self, guild_id: int, name: str, content: str) -> None:
        self._write("INSERT INTO replies (guild_id, name, content) VALUES (?, ?, ?) "
                    "ON CONFLICT (guild_id, name) DO UPDATE SET content = excluded.content",
                    (guild_id, name.lower(), content))

    def remove_reply(self, guild_id: int, name: str) -> bool:
        return self._write("DELETE FROM replies WHERE guild_id = ? AND name = ?",
                           (guild_id, name.lower())).rowcount > 0

    # ------------------------------------------------- transcript refs ---

    def add_transcript_ref(self, guild_id: int, channel_id: int, message_id: int,
                           priority: str | None, closed_at: float) -> None:
        self._write("INSERT OR REPLACE INTO transcript_refs "
                    "(guild_id, channel_id, message_id, priority, closed_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (guild_id, channel_id, message_id, priority, closed_at))

    def transcript_refs(self, guild_id: int) -> list[dict]:
        return self._all("SELECT * FROM transcript_refs WHERE guild_id = ?", (guild_id,))

    def delete_transcript_ref(self, channel_id: int, message_id: int) -> None:
        self._write("DELETE FROM transcript_refs WHERE channel_id = ? AND message_id = ?",
                    (channel_id, message_id))
