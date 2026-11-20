"""Staff roles per ticket type.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "type_staff_roles",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(["guild_id", "type_key"],
                                ["ticket_types.guild_id", "ticket_types.key"],
                                name=op.f("fk_type_staff_roles_guild_id_ticket_types"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "type_key", "role_id",
                                name=op.f("pk_type_staff_roles")),
    )


def downgrade() -> None:
    op.drop_table("type_staff_roles")
