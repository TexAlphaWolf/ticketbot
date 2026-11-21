"""FAQ shown before the ticket form.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faq_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(),
                  sa.ForeignKey("guilds.guild_id", ondelete="CASCADE"), nullable=False),
        sa.Column("type_key", sa.Text()),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["guild_id", "type_key"],
                                ["ticket_types.guild_id", "ticket_types.key"],
                                name=op.f("fk_faq_entries_guild_id_ticket_types"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_entries")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_faq_entries_guild", "faq_entries", ["guild_id"])
    op.create_table(
        "faq_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(),
                  sa.ForeignKey("guilds.guild_id", ondelete="CASCADE"), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=False),
        sa.Column("solved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_results")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_faq_results_guild_created", "faq_results", ["guild_id", "created_at"])


def downgrade() -> None:
    op.drop_table("faq_results")
    op.drop_table("faq_entries")
