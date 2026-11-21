"""
Database tables as SQLAlchemy models (V3).

The first version mirrors the v2.3 SQLite schema table by table, so an existing v2.3
database can be adopted by the migrations without copying anything. Every later change
is a numbered Alembic migration in db/migrations/versions.

Types: Discord IDs are BigInteger (64 bit; Postgres INTEGER is only 32), on/off flags
are Boolean, times are Unix timestamps in seconds (Double), like in v2. Text written by
users or staff about a ticket (subject, description and form answers, notes, close
reason, rating comment, block reason) is EncryptedText: AES-256-GCM in the database.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .types import EncryptedText

# Predictable constraint names, so migrations can refer to them on every database
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def guild_fk() -> ForeignKey:
    return ForeignKey("guilds.guild_id", ondelete="CASCADE")


class Guild(Base):
    __tablename__ = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    language: Mapped[str] = mapped_column(Text, server_default=text("'en'"))
    staff_role: Mapped[int | None] = mapped_column(BigInteger)
    category: Mapped[int | None] = mapped_column(BigInteger)
    log_channel: Mapped[int | None] = mapped_column(BigInteger)
    archive_channel: Mapped[int | None] = mapped_column(BigInteger)
    panel_channel: Mapped[int | None] = mapped_column(BigInteger)
    panel_message: Mapped[int | None] = mapped_column(BigInteger)
    guidelines_channel: Mapped[int | None] = mapped_column(BigInteger)
    guidelines_message: Mapped[int | None] = mapped_column(BigInteger)
    counter: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    retention_days: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    telegram_chat_id: Mapped[str | None] = mapped_column(Text)
    staff_reminders: Mapped[bool] = mapped_column(Boolean, server_default=true())
    ticket_cooldown: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    auto_assign: Mapped[bool] = mapped_column(Boolean, server_default=false())
    ticket_mode: Mapped[str] = mapped_column(Text, server_default=text("'channel'"))


class TicketType(Base):
    __tablename__ = "ticket_types"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk(), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    emoji: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class TypeQuestion(Base):
    __tablename__ = "type_questions"
    __table_args__ = (
        ForeignKeyConstraint(["guild_id", "type_key"],
                             ["ticket_types.guild_id", "ticket_types.key"],
                             ondelete="CASCADE"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type_key: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(Text)
    placeholder: Mapped[str] = mapped_column(Text, server_default=text("''"))
    long: Mapped[bool] = mapped_column(Boolean, server_default=false())
    required: Mapped[bool] = mapped_column(Boolean, server_default=true())


class TypeStaffRole(Base):
    """Roles that handle the tickets of one type (instead of the main staff role)."""

    __tablename__ = "type_staff_roles"
    __table_args__ = (
        ForeignKeyConstraint(["guild_id", "type_key"],
                             ["ticket_types.guild_id", "ticket_types.key"],
                             ondelete="CASCADE"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type_key: Mapped[str] = mapped_column(Text, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)


class EscalationLevel(Base):
    """Level 1, 2... above the normal staff: a role and, optionally, after how many hours
    without a staff reply a ticket climbs to it by itself."""

    __tablename__ = "escalation_levels"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk(), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    role_id: Mapped[int] = mapped_column(BigInteger)
    after_hours: Mapped[float | None] = mapped_column(Double)


class FaqEntry(Base):
    """A question and its answer, shown before the ticket form so a member may solve the
    problem alone. type_key None = shown for every ticket type."""

    __tablename__ = "faq_entries"
    __table_args__ = (
        ForeignKeyConstraint(["guild_id", "type_key"],
                             ["ticket_types.guild_id", "ticket_types.key"],
                             ondelete="CASCADE"),
        Index("ix_faq_entries_guild", "guild_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk())
    type_key: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Double)


class FaqResult(Base):
    """What a member did after reading the FAQ: solved alone or opened a ticket anyway.
    Who it was is not recorded: only the server, the type and when."""

    __tablename__ = "faq_results"
    __table_args__ = (
        Index("ix_faq_results_guild_created", "guild_id", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk())
    type_key: Mapped[str] = mapped_column(Text)
    solved: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[float] = mapped_column(Double)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("idx_tickets_guild_status", "guild_id", "status"),
        {"sqlite_autoincrement": True},   # never reuse the id of a deleted ticket
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk())
    channel_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    number: Mapped[int | None] = mapped_column(Integer)
    user_number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    type_key: Mapped[str] = mapped_column(Text)
    type_label: Mapped[str] = mapped_column(Text)
    type_emoji: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(EncryptedText("tickets.subject"))
    description: Mapped[str | None] = mapped_column(EncryptedText("tickets.description"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'waiting'"))
    priority: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[int | None] = mapped_column(BigInteger)
    assigned_to: Mapped[int | None] = mapped_column(BigInteger)
    control_message: Mapped[int | None] = mapped_column(BigInteger)
    opened_at: Mapped[float] = mapped_column(Double)
    first_response_at: Mapped[float | None] = mapped_column(Double)
    last_actor: Mapped[str | None] = mapped_column(Text)
    last_activity: Mapped[float] = mapped_column(Double)
    warned: Mapped[bool] = mapped_column(Boolean, server_default=false())
    awaiting_staff_since: Mapped[float | None] = mapped_column(Double)
    staff_reminded_at: Mapped[float | None] = mapped_column(Double)
    closed_at: Mapped[float | None] = mapped_column(Double)
    closed_by: Mapped[int | None] = mapped_column(BigInteger)
    close_reason: Mapped[str | None] = mapped_column(EncryptedText("tickets.close_reason"))
    channel_deleted: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_thread: Mapped[bool] = mapped_column(Boolean, server_default=false())
    escalation_level: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    escalated_at: Mapped[float | None] = mapped_column(Double)
    rating: Mapped[int | None] = mapped_column(Integer)
    rating_comment: Mapped[str | None] = mapped_column(EncryptedText("tickets.rating_comment"))
    rated_at: Mapped[float | None] = mapped_column(Double)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(EncryptedText("notes.text"))
    created_at: Mapped[float] = mapped_column(Double)


class Reply(Base):
    __tablename__ = "replies"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text)


class StaffAvailability(Base):
    __tablename__ = "staff_availability"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    last_assigned_at: Mapped[float | None] = mapped_column(Double)


class BlockedUser(Base):
    __tablename__ = "blocked_users"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    reason: Mapped[str | None] = mapped_column(EncryptedText("blocked_users.reason"))
    blocked_by: Mapped[int] = mapped_column(BigInteger)
    blocked_at: Mapped[float] = mapped_column(Double)
    until: Mapped[float | None] = mapped_column(Double)


class TranscriptRef(Base):
    __tablename__ = "transcript_refs"

    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk())
    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    priority: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[float] = mapped_column(Double)


class AuditEntry(Base):
    """Who did what, when and from where. Details and IP are encrypted (personal data)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_guild_created", "guild_id", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int | None] = mapped_column(BigInteger)   # None = not about one server
    actor_id: Mapped[int | None] = mapped_column(BigInteger)   # None = the bot itself
    source: Mapped[str] = mapped_column(Text)                  # discord, web, system, cli
    action: Mapped[str] = mapped_column(Text)                  # e.g. ticket.close
    target: Mapped[str | None] = mapped_column(Text)           # e.g. ticket:12, user:123
    details: Mapped[str | None] = mapped_column(EncryptedText("audit_log.details"))
    ip: Mapped[str | None] = mapped_column(EncryptedText("audit_log.ip"))
    created_at: Mapped[float] = mapped_column(Double)


class WebSession(Base):
    """A login to the web dashboard. The id is the SHA-256 of the cookie's value, so the
    database alone can't be used to log in. Discord tokens and the CSRF token are
    encrypted."""

    __tablename__ = "web_sessions"
    __table_args__ = (Index("ix_web_sessions_user", "user_id"),
                      Index("ix_web_sessions_expires", "expires_at"))

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(Text)
    global_name: Mapped[str | None] = mapped_column(Text)
    avatar: Mapped[str | None] = mapped_column(Text)
    access_token: Mapped[str] = mapped_column(EncryptedText("web_sessions.access_token"))
    refresh_token: Mapped[str | None] = mapped_column(
        EncryptedText("web_sessions.refresh_token"))
    token_expires_at: Mapped[float] = mapped_column(Double)
    csrf_token: Mapped[str] = mapped_column(EncryptedText("web_sessions.csrf_token"))
    ip: Mapped[str | None] = mapped_column(EncryptedText("web_sessions.ip"))
    user_agent: Mapped[str | None] = mapped_column(EncryptedText("web_sessions.user_agent"))
    created_at: Mapped[float] = mapped_column(Double)
    last_seen_at: Mapped[float] = mapped_column(Double)
    expires_at: Mapped[float] = mapped_column(Double)


class BotCommand(Base):
    """An action asked by the web dashboard and carried out by the bot on Discord."""

    __tablename__ = "bot_commands"
    __table_args__ = (
        Index("ix_bot_commands_status", "status", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, guild_fk())
    kind: Mapped[str] = mapped_column(Text)                    # e.g. ticket.close
    payload: Mapped[str | None] = mapped_column(EncryptedText("bot_commands.payload"))
    requested_by: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double)
