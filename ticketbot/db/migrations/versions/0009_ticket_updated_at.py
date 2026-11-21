"""When a ticket last changed, so the dashboard can update itself.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("updated_at", sa.Double()))
    op.create_index("ix_tickets_guild_updated", "tickets", ["guild_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_tickets_guild_updated", "tickets")
    with op.batch_alter_table("tickets", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("updated_at")
