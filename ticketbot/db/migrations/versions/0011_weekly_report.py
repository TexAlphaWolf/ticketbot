"""Weekly report: on or off, its channel, when it was last sent.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guilds", sa.Column("weekly_report", sa.Boolean(),
                                      server_default=sa.true(), nullable=False))
    op.add_column("guilds", sa.Column("report_channel", sa.BigInteger()))
    op.add_column("guilds", sa.Column("last_report_at", sa.Double()))


def downgrade() -> None:
    with op.batch_alter_table("guilds") as batch:
        batch.drop_column("last_report_at")
        batch.drop_column("report_channel")
        batch.drop_column("weekly_report")
