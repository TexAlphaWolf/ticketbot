"""The web process opens the database but never migrates it: the bot does that at start,
with a backup first. Two processes applying migrations together could clash."""

from ..core import crypto
from ..core.settings import Settings, SettingsError
from ..db import Store, migrate
from ..db.engine import create_engine, safe_url

START_BOT_FIRST = ("Start the bot first (`python -m ticketbot`): it backs up and updates "
                   "the database, then start the web dashboard.")


async def open_web_store(settings: Settings) -> Store:
    crypto.configure(settings.keyring())
    sqlite = settings.sqlite_path
    if sqlite is not None and not sqlite.exists():     # don't create an empty file
        raise SettingsError(f"{sqlite}: no TicketBot database. {START_BOT_FIRST}")
    engine = create_engine(settings.db_url)
    try:
        current = await migrate.current_revision(engine)
    except Exception:
        await engine.dispose()
        raise
    head = migrate.head_revision()
    if current != head:
        await engine.dispose()
        found = f"schema {current}" if current else "no TicketBot database"
        raise SettingsError(
            f"{safe_url(settings.db_url)}: {found}, this version needs schema {head}. "
            + START_BOT_FIRST)
    return Store(engine)
