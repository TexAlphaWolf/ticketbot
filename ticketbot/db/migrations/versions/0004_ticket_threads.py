"""Tickets as private threads.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN (no table rebuild): SQLite keeps AUTOINCREMENT on tickets
    op.add_column("guilds", sa.Column("ticket_mode", sa.Text(),
                                      server_default=sa.text("'channel'"), nullable=False))
    op.add_column("tickets", sa.Column("is_thread", sa.Boolean(), server_default=sa.false(),
                                       nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("tickets", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("is_thread")
    with op.batch_alter_table("guilds") as batch:
        batch.drop_column("ticket_mode")
