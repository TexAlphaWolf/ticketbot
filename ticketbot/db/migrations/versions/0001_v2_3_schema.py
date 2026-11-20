"""The v2.3 schema: the starting point of the V3 migrations.

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _guild_fk() -> sa.ForeignKey:
    return sa.ForeignKey("guilds.guild_id", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("language", sa.Text(), server_default=sa.text("'en'"), nullable=False),
        sa.Column("staff_role", sa.BigInteger()),
        sa.Column("category", sa.BigInteger()),
        sa.Column("log_channel", sa.BigInteger()),
        sa.Column("archive_channel", sa.BigInteger()),
        sa.Column("panel_channel", sa.BigInteger()),
        sa.Column("panel_message", sa.BigInteger()),
        sa.Column("guidelines_channel", sa.BigInteger()),
        sa.Column("guidelines_message", sa.BigInteger()),
        sa.Column("counter", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("retention_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("telegram_chat_id", sa.Text()),
        sa.Column("staff_reminders", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("ticket_cooldown", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("auto_assign", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", name=op.f("pk_guilds")),
    )
    op.create_table(
        "ticket_types",
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "key", name=op.f("pk_ticket_types")),
    )
    op.create_table(
        "type_questions",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("placeholder", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("long", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["guild_id", "type_key"],
                                ["ticket_types.guild_id", "ticket_types.key"],
                                name=op.f("fk_type_questions_guild_id_ticket_types"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "type_key", "position",
                                name=op.f("pk_type_questions")),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("number", sa.Integer()),
        sa.Column("user_number", sa.Integer()),
        sa.Column("name", sa.Text()),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=False),
        sa.Column("type_label", sa.Text(), nullable=False),
        sa.Column("type_emoji", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.Text(), server_default=sa.text("'waiting'"), nullable=False),
        sa.Column("priority", sa.Text()),
        sa.Column("claimed_by", sa.BigInteger()),
        sa.Column("assigned_to", sa.BigInteger()),
        sa.Column("control_message", sa.BigInteger()),
        sa.Column("opened_at", sa.Double(), nullable=False),
        sa.Column("first_response_at", sa.Double()),
        sa.Column("last_actor", sa.Text()),
        sa.Column("last_activity", sa.Double(), nullable=False),
        sa.Column("warned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("awaiting_staff_since", sa.Double()),
        sa.Column("staff_reminded_at", sa.Double()),
        sa.Column("closed_at", sa.Double()),
        sa.Column("closed_by", sa.BigInteger()),
        sa.Column("close_reason", sa.Text()),
        sa.Column("channel_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("rating_comment", sa.Text()),
        sa.Column("rated_at", sa.Double()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.UniqueConstraint("channel_id", name=op.f("uq_tickets_channel_id")),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_tickets_guild_status", "tickets", ["guild_id", "status"])
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "replies",
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "name", name=op.f("pk_replies")),
    )
    op.create_table(
        "staff_availability",
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("last_assigned_at", sa.Double()),
        sa.PrimaryKeyConstraint("guild_id", "user_id", name=op.f("pk_staff_availability")),
    )
    op.create_table(
        "blocked_users",
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("blocked_by", sa.BigInteger(), nullable=False),
        sa.Column("blocked_at", sa.Double(), nullable=False),
        sa.Column("until", sa.Double()),
        sa.PrimaryKeyConstraint("guild_id", "user_id", name=op.f("pk_blocked_users")),
    )
    op.create_table(
        "transcript_refs",
        sa.Column("guild_id", sa.BigInteger(), _guild_fk(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("message_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("priority", sa.Text()),
        sa.Column("closed_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("channel_id", "message_id", name=op.f("pk_transcript_refs")),
    )


def downgrade() -> None:
    for table in ("transcript_refs", "blocked_users", "staff_availability", "replies",
                  "notes", "tickets", "type_questions", "ticket_types", "guilds"):
        op.drop_table(table)
