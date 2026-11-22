"""
Async storage used by the bot (and, from Beta3, by the web API).

Every method is one short transaction and returns plain dicts, like the v2 Database class,
so the bot logic did not have to change. The same code runs on SQLite and PostgreSQL.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Table, and_, delete, func, insert, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base

T: dict[str, Table] = Base.metadata.tables
GUILDS, TYPES, QUESTIONS = T["guilds"], T["ticket_types"], T["type_questions"]
TICKETS, NOTES, REPLIES = T["tickets"], T["notes"], T["replies"]
STAFF, BLOCKS, REFS = T["staff_availability"], T["blocked_users"], T["transcript_refs"]
AUDIT, COMMANDS = T["audit_log"], T["bot_commands"]
TYPE_ROLES = T["type_staff_roles"]
LEVELS = T["escalation_levels"]
FAQ, FAQ_RESULTS = T["faq_entries"], T["faq_results"]
SESSIONS = T["web_sessions"]
TRANSCRIPTS = T["transcripts"]
TG_ACCOUNTS, TG_MESSAGES = T["telegram_accounts"], T["telegram_messages"]

GUILD_FIELDS = {c.name for c in GUILDS.columns} - {"guild_id"}
TYPE_FIELDS = {"label", "emoji", "description", "position"}
TICKET_FIELDS = {c.name for c in TICKETS.columns} - {"id"}


def _check(fields: dict, allowed: set) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")


@dataclass(frozen=True)
class TicketScope:
    """Which tickets of a server a staff member may see (admins: no scope at all).
    A ticket is visible when its type is in `types`; or, with `other_types`, when its
    type has no roles of its own (`types_with_roles` lists those that have); or when it
    was escalated to `min_level` or higher."""

    types: frozenset[str] = frozenset()
    other_types: bool = False
    types_with_roles: frozenset[str] = frozenset()
    min_level: int | None = None

    def clause(self):
        parts = []
        if self.other_types:
            parts.append(TICKETS.c.type_key.not_in(self.types_with_roles)
                         if self.types_with_roles else TICKETS.c.type_key.is_not(None))
        if self.types:
            parts.append(TICKETS.c.type_key.in_(self.types))
        if self.min_level is not None:
            parts.append(TICKETS.c.escalation_level >= self.min_level)
        return or_(*parts) if parts else TICKETS.c.id.is_(None)     # nothing


TICKET_STATUSES = {"open", "closed", "all"}
SEARCH_SCAN = 2000           # tickets decrypted per page of a text search


def _open(table=TICKETS):
    return and_(table.c.status != "closed", table.c.channel_deleted.is_(False))


async def _retire_transcripts(conn, where, hold_days: float, now: float) -> None:
    """Transcripts whose ticket goes away: deleted, or hidden until now + hold_days."""
    if hold_days > 0:
        await conn.execute(update(TRANSCRIPTS).where(where, TRANSCRIPTS.c.held_until.is_(None))
                           .values(held_until=now + hold_days * 86400, ticket_id=None))
    else:
        await conn.execute(delete(TRANSCRIPTS).where(where, TRANSCRIPTS.c.held_until.is_(None)))


class Store:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.dialect = engine.dialect.name

    async def close(self) -> None:
        await self.engine.dispose()

    @property
    def sqlite_file(self) -> Path | None:
        """The database file when it is SQLite (for backups), else None."""
        database = self.engine.url.database
        if self.dialect != "sqlite" or not database or database == ":memory:":
            return None
        return Path(database)

    # ---------------------------------------------------------- helpers ---

    def _insert(self, table: Table):
        """INSERT with ON CONFLICT support on both databases."""
        module = postgresql if self.dialect == "postgresql" else sqlite
        return module.insert(table)

    async def _one(self, stmt) -> dict | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return dict(row._mapping) if row else None

    async def _all(self, stmt) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [dict(r._mapping) for r in rows]

    async def _scalar(self, stmt):
        async with self.engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def _write(self, stmt) -> int:
        async with self.engine.begin() as conn:
            return (await conn.execute(stmt)).rowcount

    # ----------------------------------------------------------- guilds ---

    async def get_guild(self, guild_id: int) -> dict | None:
        return await self._one(select(GUILDS).where(GUILDS.c.guild_id == guild_id))

    async def guild_ids(self) -> list[int]:
        return [r["guild_id"] for r in await self._all(select(GUILDS.c.guild_id))]

    async def save_guild(self, guild_id: int, **fields) -> dict:
        _check(fields, GUILD_FIELDS)
        async with self.engine.begin() as conn:
            await conn.execute(self._insert(GUILDS).values(guild_id=guild_id)
                               .on_conflict_do_nothing(index_elements=["guild_id"]))
            if fields:
                await conn.execute(update(GUILDS).where(GUILDS.c.guild_id == guild_id)
                                   .values(**fields))
        return await self.get_guild(guild_id)

    async def delete_guild(self, guild_id: int, hold_days: float = 0,
                           now: float | None = None) -> bool:
        """All the data of a server: its tables cascade, the audit log is removed too.
        Transcripts are deleted, or kept hidden for hold_days (LEGAL_HOLD_DAYS)."""
        async with self.engine.begin() as conn:
            await _retire_transcripts(conn, TRANSCRIPTS.c.guild_id == guild_id, hold_days,
                                      now or time.time())
            await conn.execute(delete(AUDIT).where(AUDIT.c.guild_id == guild_id))
            result = await conn.execute(delete(GUILDS).where(GUILDS.c.guild_id == guild_id))
            return result.rowcount > 0

    async def next_ticket_number(self, guild_id: int) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(
                update(GUILDS).where(GUILDS.c.guild_id == guild_id)
                .values(counter=GUILDS.c.counter + 1).returning(GUILDS.c.counter))
            return result.scalar_one()

    async def next_user_number(self, guild_id: int, owner_id: int) -> int:
        """Progressive number of the tickets opened by one user in a server."""
        return await self._scalar(
            select(func.coalesce(func.max(TICKETS.c.user_number), 0) + 1)
            .where(TICKETS.c.guild_id == guild_id, TICKETS.c.owner_id == owner_id))

    # ----------------------------------------------------- ticket types ---

    async def list_types(self, guild_id: int) -> list[dict]:
        return await self._all(select(TYPES).where(TYPES.c.guild_id == guild_id)
                               .order_by(TYPES.c.position, TYPES.c.key))

    async def get_type(self, guild_id: int, key: str) -> dict | None:
        return await self._one(select(TYPES).where(TYPES.c.guild_id == guild_id,
                                                   TYPES.c.key == key))

    async def add_type(self, guild_id: int, key: str, label: str, emoji: str,
                       description: str = "") -> None:
        async with self.engine.begin() as conn:
            position = (await conn.execute(
                select(func.coalesce(func.max(TYPES.c.position), -1) + 1)
                .where(TYPES.c.guild_id == guild_id))).scalar()
            await conn.execute(insert(TYPES).values(
                guild_id=guild_id, key=key, label=label, emoji=emoji,
                description=description, position=position))

    async def update_type(self, guild_id: int, key: str, **fields) -> None:
        _check(fields, TYPE_FIELDS)
        if fields:
            await self._write(update(TYPES).where(TYPES.c.guild_id == guild_id,
                                                  TYPES.c.key == key).values(**fields))

    async def remove_type(self, guild_id: int, key: str) -> bool:
        return await self._write(delete(TYPES).where(TYPES.c.guild_id == guild_id,
                                                     TYPES.c.key == key)) > 0

    async def ensure_default_types(self, guild_id: int, defaults: list[tuple]) -> None:
        if not await self.list_types(guild_id):
            for key, label, emoji, description in defaults:
                await self.add_type(guild_id, key, label, emoji, description)

    async def type_roles(self, guild_id: int, type_key: str) -> list[int]:
        """Roles that handle this type; empty = the main staff role."""
        rows = await self._all(select(TYPE_ROLES.c.role_id)
                               .where(TYPE_ROLES.c.guild_id == guild_id,
                                      TYPE_ROLES.c.type_key == type_key)
                               .order_by(TYPE_ROLES.c.role_id))
        return [r["role_id"] for r in rows]

    async def all_type_roles(self, guild_id: int) -> dict[str, list[int]]:
        rows = await self._all(select(TYPE_ROLES).where(TYPE_ROLES.c.guild_id == guild_id)
                               .order_by(TYPE_ROLES.c.type_key, TYPE_ROLES.c.role_id))
        found: dict[str, list[int]] = {}
        for r in rows:
            found.setdefault(r["type_key"], []).append(r["role_id"])
        return found

    async def add_type_role(self, guild_id: int, type_key: str, role_id: int) -> bool:
        """False if the role was already there."""
        return await self._write(
            self._insert(TYPE_ROLES).values(guild_id=guild_id, type_key=type_key,
                                            role_id=role_id)
            .on_conflict_do_nothing(index_elements=["guild_id", "type_key", "role_id"])) > 0

    async def remove_type_role(self, guild_id: int, type_key: str, role_id: int) -> bool:
        return await self._write(delete(TYPE_ROLES).where(
            TYPE_ROLES.c.guild_id == guild_id, TYPE_ROLES.c.type_key == type_key,
            TYPE_ROLES.c.role_id == role_id)) > 0

    # -------------------------------------------------------- escalation ---

    async def escalation_levels(self, guild_id: int) -> list[dict]:
        return await self._all(select(LEVELS).where(LEVELS.c.guild_id == guild_id)
                               .order_by(LEVELS.c.level))

    async def add_escalation_level(self, guild_id: int, role_id: int,
                                   after_hours: float | None) -> int:
        """Add the next level (1, 2, 3...) and return its number."""
        async with self.engine.begin() as conn:
            level = (await conn.execute(
                select(func.coalesce(func.max(LEVELS.c.level), 0) + 1)
                .where(LEVELS.c.guild_id == guild_id))).scalar()
            await conn.execute(insert(LEVELS).values(guild_id=guild_id, level=level,
                                                     role_id=role_id, after_hours=after_hours))
        return level

    async def remove_escalation_level(self, guild_id: int, level: int) -> bool:
        """Remove a level and renumber the ones above it."""
        async with self.engine.begin() as conn:
            removed = (await conn.execute(delete(LEVELS).where(
                LEVELS.c.guild_id == guild_id, LEVELS.c.level == level))).rowcount
            if removed:
                above = (await conn.execute(
                    select(LEVELS.c.level).where(LEVELS.c.guild_id == guild_id,
                                                 LEVELS.c.level > level)
                    .order_by(LEVELS.c.level))).scalars().all()
                for old in above:
                    await conn.execute(update(LEVELS).where(LEVELS.c.guild_id == guild_id,
                                                            LEVELS.c.level == old)
                                       .values(level=old - 1))
        return removed > 0

    async def list_questions(self, guild_id: int, type_key: str) -> list[dict]:
        return await self._all(select(QUESTIONS).where(QUESTIONS.c.guild_id == guild_id,
                                                       QUESTIONS.c.type_key == type_key)
                               .order_by(QUESTIONS.c.position))

    async def add_question(self, guild_id: int, type_key: str, label: str,
                           placeholder: str = "", long: bool = False,
                           required: bool = True) -> int:
        async with self.engine.begin() as conn:
            position = (await conn.execute(
                select(func.coalesce(func.max(QUESTIONS.c.position), 0) + 1)
                .where(QUESTIONS.c.guild_id == guild_id,
                       QUESTIONS.c.type_key == type_key))).scalar()
            await conn.execute(insert(QUESTIONS).values(
                guild_id=guild_id, type_key=type_key, position=position, label=label,
                placeholder=placeholder, long=bool(long), required=bool(required)))
        return position

    async def remove_question(self, guild_id: int, type_key: str, position: int) -> bool:
        """Remove a question and renumber the following ones (1, 2, 3...)."""
        same_type = and_(QUESTIONS.c.guild_id == guild_id, QUESTIONS.c.type_key == type_key)
        async with self.engine.begin() as conn:
            removed = (await conn.execute(
                delete(QUESTIONS).where(same_type, QUESTIONS.c.position == position))).rowcount
            if removed:
                # One row at a time, in order: no temporary duplicate primary keys
                later = (await conn.execute(
                    select(QUESTIONS.c.position)
                    .where(same_type, QUESTIONS.c.position > position)
                    .order_by(QUESTIONS.c.position))).scalars().all()
                for old in later:
                    await conn.execute(update(QUESTIONS)
                                       .where(same_type, QUESTIONS.c.position == old)
                                       .values(position=old - 1))
        return removed > 0

    # ---------------------------------------------------------- tickets ---

    async def create_ticket(self, **fields) -> int:
        _check(fields, TICKET_FIELDS)
        async with self.engine.begin() as conn:
            result = await conn.execute(insert(TICKETS).values(updated_at=time.time(),
                                                               **fields)
                                        .returning(TICKETS.c.id))
            return result.scalar_one()

    async def get_ticket(self, ticket_id: int) -> dict | None:
        return await self._one(select(TICKETS).where(TICKETS.c.id == ticket_id))

    async def ticket_by_channel(self, channel_id: int) -> dict | None:
        return await self._one(select(TICKETS).where(TICKETS.c.channel_id == channel_id,
                                                     TICKETS.c.channel_deleted.is_(False)))

    async def update_ticket(self, ticket_id: int, **fields) -> None:
        _check(fields, TICKET_FIELDS)
        if fields:
            await self._write(update(TICKETS).where(TICKETS.c.id == ticket_id)
                              .values(**{"updated_at": time.time(), **fields}))

    async def open_ticket_of_owner(self, guild_id: int, owner_id: int) -> dict | None:
        return await self._one(select(TICKETS).where(
            TICKETS.c.guild_id == guild_id, TICKETS.c.owner_id == owner_id, _open()).limit(1))

    async def queue_counts(self, guild_id: int) -> tuple[int, int]:
        """(waiting, in_progress) among the open tickets of a server."""
        rows = await self._all(select(TICKETS.c.status, func.count().label("n"))
                               .where(TICKETS.c.guild_id == guild_id, _open())
                               .group_by(TICKETS.c.status))
        counts = {r["status"]: r["n"] for r in rows}
        return counts.get("waiting", 0), counts.get("in_progress", 0)

    async def active_tickets(self) -> list[dict]:
        return await self._all(select(TICKETS).where(_open()))

    async def closed_channels_due(self, closed_before: float) -> list[dict]:
        return await self._all(select(TICKETS).where(
            TICKETS.c.status == "closed", TICKETS.c.channel_deleted.is_(False),
            TICKETS.c.closed_at <= closed_before))

    async def mark_channel_deleted(self, ticket_id: int) -> None:
        """The channel is gone: forget the content, keep the metadata for /stats."""
        async with self.engine.begin() as conn:
            await conn.execute(update(TICKETS).where(TICKETS.c.id == ticket_id)
                               .values(channel_deleted=True, subject=None, description=None,
                                       updated_at=time.time()))
            await conn.execute(delete(NOTES).where(NOTES.c.ticket_id == ticket_id))

    async def last_ticket_of_owner(self, guild_id: int, owner_id: int) -> dict | None:
        return await self._one(
            select(TICKETS).where(TICKETS.c.guild_id == guild_id,
                                  TICKETS.c.owner_id == owner_id)
            .order_by(TICKETS.c.opened_at.desc(), TICKETS.c.id.desc()).limit(1))

    async def tickets_of_user(self, guild_id: int, owner_id: int) -> list[dict]:
        """All the tickets of a member in a server, newest first."""
        return await self._all(
            select(TICKETS).where(TICKETS.c.guild_id == guild_id,
                                  TICKETS.c.owner_id == owner_id)
            .order_by(TICKETS.c.opened_at.desc(), TICKETS.c.id.desc()))

    async def list_tickets(self, guild_id: int, *, status: str = "open",
                           type_key: str | None = None, scope: TicketScope | None = None,
                           before_id: int | None = None, limit: int = 50,
                           priority: str | None = None, person: int | None = None,
                           opened_from: float | None = None,
                           opened_to: float | None = None,
                           text: str | None = None) -> tuple[list[dict], int | None]:
        """Newest first, a page at a time: (tickets, the before_id of the next page or
        None). status: open, closed or all; priority: low/medium/high or "none"; person:
        who opened, claimed or was assigned the ticket. `text` looks in the number, the
        channel name, the type, the subject and the form answers; the last two are
        encrypted, so they are decrypted and searched here, at most SEARCH_SCAN rows per
        page (a page may then come back short, with a next page to look further)."""
        stmt = select(TICKETS).where(TICKETS.c.guild_id == guild_id)
        if status == "open":
            stmt = stmt.where(_open())
        elif status == "closed":
            stmt = stmt.where(TICKETS.c.status == "closed")
        if type_key is not None:
            stmt = stmt.where(TICKETS.c.type_key == type_key)
        if scope is not None:
            stmt = stmt.where(scope.clause())
        if priority == "none":
            stmt = stmt.where(TICKETS.c.priority.is_(None))
        elif priority is not None:
            stmt = stmt.where(TICKETS.c.priority == priority)
        if person is not None:
            stmt = stmt.where(or_(TICKETS.c.owner_id == person, TICKETS.c.claimed_by == person,
                                  TICKETS.c.assigned_to == person))
        if opened_from is not None:
            stmt = stmt.where(TICKETS.c.opened_at >= opened_from)
        if opened_to is not None:
            stmt = stmt.where(TICKETS.c.opened_at < opened_to)

        text = (text or "").strip()
        number = text.removeprefix("#")
        if number.isdigit() and len(number) <= 9:           # a ticket number
            stmt = stmt.where(TICKETS.c.number == int(number))
            text = ""
        elif text.isdigit() and 15 <= len(text) <= 20:     # a Discord ID
            stmt = stmt.where(or_(TICKETS.c.owner_id == int(text),
                                  TICKETS.c.claimed_by == int(text),
                                  TICKETS.c.assigned_to == int(text)))
            text = ""
        stmt = stmt.order_by(TICKETS.c.id.desc())

        if not text:
            if before_id is not None:
                stmt = stmt.where(TICKETS.c.id < before_id)
            rows = await self._all(stmt.limit(limit))
            return rows, (rows[-1]["id"] if len(rows) == limit else None)

        needle = text.casefold()
        found: list[dict] = []
        cursor, scanned = before_id, 0
        while scanned < SEARCH_SCAN:
            size = min(200, SEARCH_SCAN - scanned)
            batch_stmt = stmt.where(TICKETS.c.id < cursor) if cursor is not None else stmt
            batch = await self._all(batch_stmt.limit(size))
            for row in batch:
                scanned += 1
                cursor = row["id"]
                haystack = " ".join(str(row[k] or "") for k in (
                    "name", "type_label", "subject", "description")).casefold()
                if needle in haystack:
                    found.append(row)
                    if len(found) == limit:
                        return found, row["id"]
            if len(batch) < size:
                return found, None
        return found, cursor          # looked at SEARCH_SCAN rows: more may follow

    async def tickets_version(self, guild_id: int, scope: TicketScope | None = None) -> tuple:
        """Changes when a visible ticket is opened, changed or deleted (live dashboard)."""
        stmt = select(func.count(), func.max(TICKETS.c.id), func.max(TICKETS.c.updated_at)) \
            .where(TICKETS.c.guild_id == guild_id)
        if scope is not None:
            stmt = stmt.where(scope.clause())
        async with self.engine.connect() as conn:
            return tuple((await conn.execute(stmt)).one())

    async def tickets_since(self, guild_id: int, since: float) -> list[dict]:
        return await self._all(select(TICKETS).where(TICKETS.c.guild_id == guild_id,
                                                     TICKETS.c.opened_at >= since))

    async def purge_closed_before(self, before: float, hold_days: float = 0,
                                  now: float | None = None) -> int:
        old = and_(TICKETS.c.status == "closed", TICKETS.c.channel_deleted.is_(True),
                   TICKETS.c.closed_at < before)
        async with self.engine.begin() as conn:
            await _retire_transcripts(conn, TRANSCRIPTS.c.ticket_id.in_(
                select(TICKETS.c.id).where(old)), hold_days, now or time.time())
            return (await conn.execute(delete(TICKETS).where(old))).rowcount

    async def delete_ticket(self, ticket_id: int, hold_days: float = 0,
                            now: float | None = None) -> list[dict]:
        """Delete a ticket everywhere (notes, transcript; the statistics lose it). Its
        transcript is kept hidden for hold_days if set. Returns the transcripts it had
        (to delete their messages on Discord)."""
        async with self.engine.begin() as conn:
            found = [dict(r._mapping) for r in (await conn.execute(
                select(TRANSCRIPTS.c.id, TRANSCRIPTS.c.archive_channel_id,
                       TRANSCRIPTS.c.archive_message_id, TRANSCRIPTS.c.log_channel_id,
                       TRANSCRIPTS.c.log_message_id)
                .where(TRANSCRIPTS.c.ticket_id == ticket_id))).all()]
            await _retire_transcripts(conn, TRANSCRIPTS.c.ticket_id == ticket_id, hold_days,
                                      now or time.time())
            await conn.execute(delete(TICKETS).where(TICKETS.c.id == ticket_id))
        return found

    # -------------------------------------------------------- telegram ---

    async def link_telegram_account(self, telegram_user_id: int, discord_user_id: int,
                                    now: float | None = None) -> None:
        """One Telegram account per Discord account and the other way round: a new link
        replaces the old ones of both."""
        async with self.engine.begin() as conn:
            await conn.execute(delete(TG_ACCOUNTS).where(
                (TG_ACCOUNTS.c.telegram_user_id == telegram_user_id)
                | (TG_ACCOUNTS.c.discord_user_id == discord_user_id)))
            await conn.execute(insert(TG_ACCOUNTS).values(
                telegram_user_id=telegram_user_id, discord_user_id=discord_user_id,
                linked_at=now or time.time()))

    async def telegram_account(self, telegram_user_id: int) -> dict | None:
        return await self._one(select(TG_ACCOUNTS).where(
            TG_ACCOUNTS.c.telegram_user_id == telegram_user_id))

    async def telegram_account_of(self, discord_user_id: int) -> dict | None:
        return await self._one(select(TG_ACCOUNTS).where(
            TG_ACCOUNTS.c.discord_user_id == discord_user_id))

    async def unlink_telegram_account(self, *, discord_user_id: int | None = None,
                                      telegram_user_id: int | None = None) -> bool:
        column, value = ((TG_ACCOUNTS.c.discord_user_id, discord_user_id)
                         if discord_user_id is not None
                         else (TG_ACCOUNTS.c.telegram_user_id, telegram_user_id))
        return await self._write(delete(TG_ACCOUNTS).where(column == value)) > 0

    async def track_telegram_message(self, chat_id: int, message_id: int, guild_id: int,
                                     ticket_id: int, now: float | None = None) -> None:
        await self._write(insert(TG_MESSAGES).values(
            chat_id=chat_id, message_id=message_id, guild_id=guild_id,
            ticket_id=ticket_id, created_at=now or time.time()))

    async def telegram_message(self, chat_id: int, message_id: int) -> dict | None:
        return await self._one(select(TG_MESSAGES).where(
            TG_MESSAGES.c.chat_id == chat_id, TG_MESSAGES.c.message_id == message_id))

    async def telegram_messages_of(self, ticket_id: int) -> list[list[int]]:
        """[chat ID, message ID] of the Telegram notifications about a ticket."""
        return [[r["chat_id"], r["message_id"]] for r in await self._all(
            select(TG_MESSAGES.c.chat_id, TG_MESSAGES.c.message_id)
            .where(TG_MESSAGES.c.ticket_id == ticket_id))]

    async def purge_telegram_messages_before(self, before: float) -> int:
        return await self._write(delete(TG_MESSAGES).where(TG_MESSAGES.c.created_at < before))

    # ------------------------------------------------------- transcripts ---

    async def save_transcript(self, **values) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(insert(TRANSCRIPTS).values(**values)
                                        .returning(TRANSCRIPTS.c.id))
            # The transcript is saved a few seconds after the ticket closes: tell the
            # open dashboards, so they show it without a reload
            await conn.execute(update(TICKETS).where(TICKETS.c.id == values["ticket_id"])
                               .values(updated_at=time.time()))
            return result.scalar_one()

    async def ticket_transcript(self, ticket_id: int) -> dict | None:
        """The latest visible transcript of a ticket (a reopened ticket has more)."""
        return await self._one(select(TRANSCRIPTS).where(
            TRANSCRIPTS.c.ticket_id == ticket_id, TRANSCRIPTS.c.held_until.is_(None))
            .order_by(TRANSCRIPTS.c.id.desc()).limit(1))

    async def transcript_by_archive_message(self, message_id: int) -> dict | None:
        return await self._one(select(TRANSCRIPTS).where(
            TRANSCRIPTS.c.archive_message_id == message_id,
            TRANSCRIPTS.c.held_until.is_(None)))

    async def held_transcripts(self) -> list[dict]:
        return await self._all(
            select(TRANSCRIPTS.c.id, TRANSCRIPTS.c.guild_id, TRANSCRIPTS.c.channel_name,
                   TRANSCRIPTS.c.created_at, TRANSCRIPTS.c.held_until)
            .where(TRANSCRIPTS.c.held_until.is_not(None)).order_by(TRANSCRIPTS.c.id))

    async def get_transcript(self, transcript_id: int) -> dict | None:
        return await self._one(select(TRANSCRIPTS).where(TRANSCRIPTS.c.id == transcript_id))

    async def purge_held_transcripts(self, now: float) -> int:
        return await self._write(delete(TRANSCRIPTS).where(
            TRANSCRIPTS.c.held_until.is_not(None), TRANSCRIPTS.c.held_until < now))

    # ------------------------------------------------- staff rotation ---

    async def set_available(self, guild_id: int, user_id: int, available: bool) -> None:
        if available:
            await self._write(self._insert(STAFF).values(guild_id=guild_id, user_id=user_id)
                              .on_conflict_do_nothing(index_elements=["guild_id", "user_id"]))
        else:
            await self._write(delete(STAFF).where(STAFF.c.guild_id == guild_id,
                                                  STAFF.c.user_id == user_id))

    async def available_staff(self, guild_id: int) -> list[dict]:
        return await self._all(select(STAFF).where(STAFF.c.guild_id == guild_id)
                               .order_by(STAFF.c.user_id))

    async def mark_assigned(self, guild_id: int, user_id: int, now: float) -> None:
        await self._write(update(STAFF).where(STAFF.c.guild_id == guild_id,
                                              STAFF.c.user_id == user_id)
                          .values(last_assigned_at=now))

    async def open_tickets_per_staff(self, guild_id: int) -> dict[int, int]:
        """Open tickets handled by each staff member (claimed, or assigned and not claimed)."""
        staff = func.coalesce(TICKETS.c.claimed_by, TICKETS.c.assigned_to)
        rows = await self._all(select(staff.label("staff"), func.count().label("n"))
                               .where(TICKETS.c.guild_id == guild_id, _open(),
                                      staff.is_not(None))
                               .group_by(staff))
        return {r["staff"]: r["n"] for r in rows}

    # ---------------------------------------------------- blocked users ---

    async def block_user(self, guild_id: int, user_id: int, reason: str | None,
                         blocked_by: int, blocked_at: float, until: float | None) -> None:
        values = dict(reason=reason, blocked_by=blocked_by, blocked_at=blocked_at, until=until)
        await self._write(self._insert(BLOCKS).values(guild_id=guild_id, user_id=user_id,
                                                      **values)
                          .on_conflict_do_update(index_elements=["guild_id", "user_id"],
                                                 set_=values))

    async def unblock_user(self, guild_id: int, user_id: int) -> bool:
        return await self._write(delete(BLOCKS).where(BLOCKS.c.guild_id == guild_id,
                                                      BLOCKS.c.user_id == user_id)) > 0

    @staticmethod
    def _active(now: float):
        return or_(BLOCKS.c.until.is_(None), BLOCKS.c.until > now)

    async def get_block(self, guild_id: int, user_id: int, now: float) -> dict | None:
        """The block of a member, if it is still active."""
        return await self._one(select(BLOCKS).where(BLOCKS.c.guild_id == guild_id,
                                                    BLOCKS.c.user_id == user_id,
                                                    self._active(now)))

    async def list_blocks(self, guild_id: int, now: float) -> list[dict]:
        return await self._all(select(BLOCKS).where(BLOCKS.c.guild_id == guild_id,
                                                    self._active(now))
                               .order_by(BLOCKS.c.blocked_at.desc()))

    async def purge_expired_blocks(self, now: float) -> int:
        return await self._write(delete(BLOCKS).where(BLOCKS.c.until.is_not(None),
                                                      BLOCKS.c.until <= now))

    # ------------------------------------------------------------ notes ---

    async def add_note(self, ticket_id: int, author_id: int, text: str,
                       created_at: float) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(NOTES).values(ticket_id=ticket_id, author_id=author_id,
                                                    text=text, created_at=created_at))
            await conn.execute(update(TICKETS).where(TICKETS.c.id == ticket_id)
                               .values(updated_at=time.time()))

    async def list_notes(self, ticket_id: int) -> list[dict]:
        return await self._all(select(NOTES).where(NOTES.c.ticket_id == ticket_id)
                               .order_by(NOTES.c.created_at, NOTES.c.id))

    # ---------------------------------------------------- quick replies ---

    async def list_replies(self, guild_id: int) -> list[dict]:
        return await self._all(select(REPLIES).where(REPLIES.c.guild_id == guild_id)
                               .order_by(REPLIES.c.name))

    async def get_reply(self, guild_id: int, name: str) -> dict | None:
        return await self._one(select(REPLIES).where(REPLIES.c.guild_id == guild_id,
                                                     REPLIES.c.name == name.lower()))

    async def save_reply(self, guild_id: int, name: str, content: str) -> None:
        await self._write(self._insert(REPLIES)
                          .values(guild_id=guild_id, name=name.lower(), content=content)
                          .on_conflict_do_update(index_elements=["guild_id", "name"],
                                                 set_={"content": content}))

    async def remove_reply(self, guild_id: int, name: str) -> bool:
        return await self._write(delete(REPLIES).where(REPLIES.c.guild_id == guild_id,
                                                       REPLIES.c.name == name.lower())) > 0

    # -------------------------------------------------------------- FAQ ---

    async def list_faq(self, guild_id: int) -> list[dict]:
        return await self._all(select(FAQ).where(FAQ.c.guild_id == guild_id)
                               .order_by(FAQ.c.id))

    async def faq_for_type(self, guild_id: int, type_key: str, limit: int) -> list[dict]:
        """The entries of this type first, then the ones for every type."""
        return await self._all(
            select(FAQ).where(FAQ.c.guild_id == guild_id,
                              or_(FAQ.c.type_key == type_key, FAQ.c.type_key.is_(None)))
            .order_by(FAQ.c.type_key.is_(None), FAQ.c.id).limit(limit))

    async def get_faq(self, guild_id: int, entry_id: int) -> dict | None:
        return await self._one(select(FAQ).where(FAQ.c.guild_id == guild_id,
                                                 FAQ.c.id == entry_id))

    async def add_faq(self, guild_id: int, type_key: str | None, question: str, answer: str,
                      now: float | None = None) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(insert(FAQ).values(
                guild_id=guild_id, type_key=type_key, question=question, answer=answer,
                created_at=now or time.time()).returning(FAQ.c.id))
            return result.scalar_one()

    async def update_faq(self, guild_id: int, entry_id: int, question: str,
                         answer: str) -> bool:
        return await self._write(update(FAQ).where(FAQ.c.guild_id == guild_id,
                                                   FAQ.c.id == entry_id)
                                 .values(question=question, answer=answer)) > 0

    async def remove_faq(self, guild_id: int, entry_id: int) -> bool:
        return await self._write(delete(FAQ).where(FAQ.c.guild_id == guild_id,
                                                   FAQ.c.id == entry_id)) > 0

    async def record_faq_result(self, guild_id: int, type_key: str, solved: bool,
                                now: float | None = None) -> None:
        await self._write(insert(FAQ_RESULTS).values(guild_id=guild_id, type_key=type_key,
                                                     solved=solved,
                                                     created_at=now or time.time()))

    async def faq_results_since(self, guild_id: int, since: float) -> dict[str, int]:
        """{"solved": tickets avoided, "opened": tickets opened anyway} since a time."""
        rows = await self._all(
            select(FAQ_RESULTS.c.solved, func.count().label("n"))
            .where(FAQ_RESULTS.c.guild_id == guild_id, FAQ_RESULTS.c.created_at >= since)
            .group_by(FAQ_RESULTS.c.solved))
        counts = {bool(r["solved"]): r["n"] for r in rows}
        return {"solved": counts.get(True, 0), "opened": counts.get(False, 0)}

    async def purge_faq_results_before(self, before: float) -> int:
        return await self._write(delete(FAQ_RESULTS).where(FAQ_RESULTS.c.created_at < before))

    # ------------------------------------------------- transcript refs ---

    async def add_transcript_ref(self, guild_id: int, channel_id: int, message_id: int,
                                 priority: str | None, closed_at: float) -> None:
        values = dict(guild_id=guild_id, priority=priority, closed_at=closed_at)
        await self._write(self._insert(REFS)
                          .values(channel_id=channel_id, message_id=message_id, **values)
                          .on_conflict_do_update(index_elements=["channel_id", "message_id"],
                                                 set_=values))

    async def transcript_refs(self, guild_id: int) -> list[dict]:
        return await self._all(select(REFS).where(REFS.c.guild_id == guild_id))

    async def delete_transcript_ref(self, channel_id: int, message_id: int) -> None:
        await self._write(delete(REFS).where(REFS.c.channel_id == channel_id,
                                             REFS.c.message_id == message_id))

    # -------------------------------------------------------- audit log ---

    async def audit(self, guild_id: int | None, actor_id: int | None, action: str, *,
                    source: str = "discord", target: str | None = None,
                    details: dict | None = None, ip: str | None = None,
                    now: float | None = None) -> None:
        await self._write(insert(AUDIT).values(
            guild_id=guild_id, actor_id=actor_id, source=source, action=action,
            target=target, ip=ip, created_at=now if now is not None else time.time(),
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None))

    async def audit_entries(self, guild_id: int, limit: int = 50,
                            before_id: int | None = None) -> list[dict]:
        """Newest first; pass the last id seen as before_id for the next page."""
        stmt = select(AUDIT).where(AUDIT.c.guild_id == guild_id)
        if before_id is not None:
            stmt = stmt.where(AUDIT.c.id < before_id)
        rows = await self._all(stmt.order_by(AUDIT.c.id.desc()).limit(limit))
        for row in rows:
            row["details"] = json.loads(row["details"]) if row["details"] else {}
        return rows

    async def purge_audit_before(self, before: float) -> int:
        return await self._write(delete(AUDIT).where(AUDIT.c.created_at < before))

    # ------------------------------------------------------ web sessions ---

    async def create_web_session(self, **values) -> None:
        await self._write(insert(SESSIONS).values(**values))

    async def get_web_session(self, session_id: str) -> dict | None:
        return await self._one(select(SESSIONS).where(SESSIONS.c.id == session_id))

    async def update_web_session(self, session_id: str, **values) -> None:
        await self._write(update(SESSIONS).where(SESSIONS.c.id == session_id).values(**values))

    async def delete_web_session(self, session_id: str) -> bool:
        return await self._write(delete(SESSIONS).where(SESSIONS.c.id == session_id)) > 0

    async def purge_web_sessions(self, now: float) -> int:
        return await self._write(delete(SESSIONS).where(SESSIONS.c.expires_at < now))

    # ----------------------------------------------- commands from the web ---

    async def enqueue_command(self, guild_id: int, kind: str, requested_by: int,
                              payload: dict | None = None) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(insert(COMMANDS).values(
                guild_id=guild_id, kind=kind, requested_by=requested_by,
                payload=json.dumps(payload or {}, ensure_ascii=False),
                created_at=time.time()).returning(COMMANDS.c.id))
            return result.scalar_one()

    async def take_commands(self, limit: int = 20) -> list[dict]:
        """Pending commands, oldest first, marked as running so nobody else takes them."""
        taken = []
        async with self.engine.begin() as conn:
            rows = (await conn.execute(
                select(COMMANDS).where(COMMANDS.c.status == "pending")
                .order_by(COMMANDS.c.id).limit(limit))).all()
            for row in rows:
                claimed = await conn.execute(
                    update(COMMANDS).where(COMMANDS.c.id == row.id,
                                           COMMANDS.c.status == "pending")
                    .values(status="running"))
                if claimed.rowcount:
                    item = dict(row._mapping, status="running")
                    item["payload"] = json.loads(item["payload"]) if item["payload"] else {}
                    taken.append(item)
        return taken

    async def finish_command(self, command_id: int, ok: bool, result: str = "") -> None:
        await self._write(update(COMMANDS).where(COMMANDS.c.id == command_id).values(
            status="done" if ok else "failed", result=result[:500], finished_at=time.time()))

    async def has_unfinished_command(self, guild_id: int, requested_by: int, kind: str) -> bool:
        stmt = select(COMMANDS.c.id).where(
            COMMANDS.c.guild_id == guild_id, COMMANDS.c.requested_by == requested_by,
            COMMANDS.c.kind == kind, COMMANDS.c.status.in_(("pending", "running"))).limit(1)
        return await self._one(stmt) is not None

    async def tickets_of_owner(self, guild_id: int, owner_id: int,
                               limit: int = 50) -> list[dict]:
        return await self._all(select(TICKETS).where(
            TICKETS.c.guild_id == guild_id, TICKETS.c.owner_id == owner_id)
            .order_by(TICKETS.c.id.desc()).limit(limit))

    async def get_command(self, command_id: int) -> dict | None:
        return await self._one(select(COMMANDS).where(COMMANDS.c.id == command_id))

    async def reset_running_commands(self) -> int:
        """At startup: commands left running by a crash are tried again."""
        return await self._write(update(COMMANDS).where(COMMANDS.c.status == "running")
                                 .values(status="pending"))

    async def purge_finished_commands(self, before: float) -> int:
        return await self._write(delete(COMMANDS).where(
            COMMANDS.c.status.in_(("done", "failed")), COMMANDS.c.finished_at < before))
