"""Two-way Telegram: linked accounts, the notifications that can be answered, and the
option to send the users' messages to Telegram.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guilds", sa.Column("telegram_messages", sa.Boolean(),
                                      server_default=sa.true(), nullable=False))
    op.create_table(
        "telegram_accounts",
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("telegram_user_id", name=op.f("pk_telegram_accounts")),
        sa.UniqueConstraint("discord_user_id",
                            name=op.f("uq_telegram_accounts_discord_user_id")),
    )
    op.create_table(
        "telegram_messages",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("message_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("guild_id", sa.BigInteger(),
                  sa.ForeignKey("guilds.guild_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("chat_id", "message_id", name=op.f("pk_telegram_messages")),
    )
    op.create_index("ix_telegram_messages_created", "telegram_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("telegram_messages")
    op.drop_table("telegram_accounts")
    with op.batch_alter_table("guilds") as batch:
        batch.drop_column("telegram_messages")
