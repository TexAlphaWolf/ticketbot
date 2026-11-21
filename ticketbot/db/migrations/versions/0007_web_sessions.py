"""Logins to the web dashboard.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("global_name", sa.Text()),
        sa.Column("avatar", sa.Text()),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("token_expires_at", sa.Double(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("ip", sa.Text()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("last_seen_at", sa.Double(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_sessions")),
    )
    op.create_index("ix_web_sessions_user", "web_sessions", ["user_id"])
    op.create_index("ix_web_sessions_expires", "web_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("web_sessions")
