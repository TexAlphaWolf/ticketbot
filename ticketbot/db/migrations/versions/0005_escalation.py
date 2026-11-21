"""Escalation levels.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "escalation_levels",
        sa.Column("guild_id", sa.BigInteger(),
                  sa.ForeignKey("guilds.guild_id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("after_hours", sa.Double()),
        sa.PrimaryKeyConstraint("guild_id", "level", name=op.f("pk_escalation_levels")),
    )
    # Plain ADD COLUMN (no table rebuild): SQLite keeps AUTOINCREMENT on tickets
    op.add_column("tickets", sa.Column("escalation_level", sa.Integer(),
                                       server_default=sa.text("0"), nullable=False))
    op.add_column("tickets", sa.Column("escalated_at", sa.Double()))


def downgrade() -> None:
    with op.batch_alter_table("tickets", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("escalated_at")
        batch.drop_column("escalation_level")
    op.drop_table("escalation_levels")
