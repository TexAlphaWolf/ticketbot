"""The bot's heartbeat, for the web server and the Prometheus metrics.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_status",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Double(), nullable=False),
        sa.Column("heartbeat_at", sa.Double(), nullable=False),
        sa.Column("guilds", sa.Integer(), nullable=False),
        sa.Column("latency", sa.Double()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_status")),
    )


def downgrade() -> None:
    op.drop_table("bot_status")
