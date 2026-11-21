"""Transcripts of closed tickets in the database (encrypted).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("tickets.id", name=op.f("fk_transcripts_ticket_id_tickets"),
                                ondelete="SET NULL")),
        sa.Column("channel_name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("archive_channel_id", sa.BigInteger()),
        sa.Column("archive_message_id", sa.BigInteger()),
        sa.Column("log_channel_id", sa.BigInteger()),
        sa.Column("log_message_id", sa.BigInteger()),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("held_until", sa.Double()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcripts")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_transcripts_ticket", "transcripts", ["ticket_id"])
    op.create_index("ix_transcripts_archive_message", "transcripts", ["archive_message_id"])


def downgrade() -> None:
    op.drop_table("transcripts")
