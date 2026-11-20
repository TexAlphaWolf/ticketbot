"""Alembic environment: runs the migrations on the connection given by db/migrate.py."""

from alembic import context

from ticketbot.db.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run the migrations through ticketbot.db.migrate, "
                       "which gives them a database connection.")

context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=connection.dialect.name == "sqlite",  # SQLite can't ALTER most things
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
