"""
Async storage used by the bot (and, from Beta3, by the web API).

Every method is one short transaction and returns plain dicts, like the v2 Database class,
so the bot logic did not have to change. The same code runs on SQLite and PostgreSQL.
"""

import json
import time
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

GUILD_FIELDS = {c.name for c in GUILDS.columns} - {"guild_id"}
TYPE_FIELDS = {"label", "emoji", "description", "position"}
TICKET_FIELDS = {c.name for c in TICKETS.columns} - {"id"}


def _check(fields: dict, allowed: set) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")


def _open(table=TICKETS):
    return and_(table.c.status != "closed", table.c.channel_deleted.is_(False))


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

    async def delete_guild(self, guild_id: int) -> bool:
        """All the data of a server: its tables cascade, the audit log is removed too."""
        async with self.engine.begin() as conn:
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
            result = await conn.execute(insert(TICKETS).values(**fields)
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
            await self._write(update(TICKETS).where(TICKETS.c.id == ticket_id).values(**fields))

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
                               .values(channel_deleted=True, subject=None, description=None))
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

    async def tickets_since(self, guild_id: int, since: float) -> list[dict]:
        return await self._all(select(TICKETS).where(TICKETS.c.guild_id == guild_id,
                                                     TICKETS.c.opened_at >= since))

    async def purge_closed_before(self, before: float) -> int:
        return await self._write(delete(TICKETS).where(
            TICKETS.c.status == "closed", TICKETS.c.channel_deleted.is_(True),
            TICKETS.c.closed_at < before))

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
        await self._write(insert(NOTES).values(ticket_id=ticket_id, author_id=author_id,
                                               text=text, created_at=created_at))

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

    async def get_command(self, command_id: int) -> dict | None:
        return await self._one(select(COMMANDS).where(COMMANDS.c.id == command_id))

    async def reset_running_commands(self) -> int:
        """At startup: commands left running by a crash are tried again."""
        return await self._write(update(COMMANDS).where(COMMANDS.c.status == "running")
                                 .values(status="pending"))

    async def purge_finished_commands(self, before: float) -> int:
        return await self._write(delete(COMMANDS).where(
            COMMANDS.c.status.in_(("done", "failed")), COMMANDS.c.finished_at < before))
