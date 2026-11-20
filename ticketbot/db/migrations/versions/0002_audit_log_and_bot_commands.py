"""Audit log and the queue of actions from the web dashboard.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger()),
        sa.Column("actor_id", sa.BigInteger()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text()),
        sa.Column("details", sa.Text()),      # encrypted by the application
        sa.Column("ip", sa.Text()),           # encrypted by the application
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_audit_log_guild_created", "audit_log", ["guild_id", "created_at"])
    op.create_table(
        "bot_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(),
                  sa.ForeignKey("guilds.guild_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text()),      # encrypted by the application
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("result", sa.Text()),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("finished_at", sa.Double()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_commands")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_bot_commands_status", "bot_commands", ["status", "id"])


def downgrade() -> None:
    op.drop_index("ix_bot_commands_status", table_name="bot_commands")
    op.drop_table("bot_commands")
    op.drop_index("ix_audit_log_guild_created", table_name="audit_log")
    op.drop_table("audit_log")
