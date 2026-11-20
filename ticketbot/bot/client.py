"""The Discord client: startup, events and background tasks."""

import asyncio
import logging
import sqlite3
import time

import aiohttp
import discord
from discord.ext import tasks

from .. import __version__
from ..core import config
from ..core.logic import (
    activity_changes,
    autoclose_action,
    expired_refs,
    format_duration,
    staff_reminder_due,
    staff_reply_hours,
    waiting_for_staff_since,
)
from ..core.settings import Settings, get_settings
from ..db import Store
from ..db.backup import backup_due, create_backup, prune_backups
from ..db.engine import create_engine
from ..db.legacy import migrate_legacy_config
from ..db.migrate import prepare
from ..integrations.telegram import TelegramError, TelegramNotifier
from .commands import all_commands
from .common import channel_url, esc, is_staff, priority_label, telegram_notify, translator
from .tickets import ClosedControls, RatingButton, TicketControls, TicketPanel, close_ticket
from .translator import CommandTranslator


class TicketBot(discord.Client):
    def __init__(self, db: Store, settings: Settings | None = None):
        intents = discord.Intents.default()
        intents.message_content = True  # required for transcripts
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.db = db
        # Without settings (tests, scripts) the .env file is not read
        self.settings = settings or Settings(_env_file=None)
        self.http_session: aiohttp.ClientSession | None = None
        self.telegram: TelegramNotifier | None = None
        self.pending_links: dict[int, dict] = {}
        self._telegram_poller: asyncio.Task | None = None

    async def setup_hook(self):
        # Persistent buttons keep working after a restart
        self.add_view(TicketPanel())
        self.add_view(TicketControls())
        self.add_view(ClosedControls())
        self.add_dynamic_items(RatingButton)

        for command in all_commands():
            self.tree.add_command(command)
        await self.tree.set_translator(CommandTranslator())
        await self.tree.sync()

        self.http_session = aiohttp.ClientSession()
        if self.settings.telegram_bot_token:
            notifier = TelegramNotifier(self.settings.telegram_bot_token.get_secret_value(),
                                        self.http_session)
            try:
                await notifier.get_me()
            except TelegramError as e:
                print(f"[telegram] disabled, invalid TELEGRAM_BOT_TOKEN: {e}")
            else:
                self.telegram = notifier
                self._telegram_poller = asyncio.create_task(notifier.poll_forever())
                print(f"[telegram] connected as @{notifier.username}")

        self.maintenance.start()
        self.hourly_cleanup.start()

    async def close(self):
        if self._telegram_poller is not None:
            self._telegram_poller.cancel()
        if self.http_session is not None:
            await self.http_session.close()
        await super().close()
        await self.db.close()

    async def on_ready(self):
        # Servers the bot was removed from while it was offline: delete their data
        current = {g.id for g in self.guilds}
        for guild_id in await self.db.guild_ids():
            if guild_id not in current:
                await self.db.delete_guild(guild_id)
                self.pending_links.pop(guild_id, None)
                print(f"Not in server {guild_id} anymore: server data deleted")
        print(f"TicketBot {__version__} online as {self.user} in {len(self.guilds)} server(s)")

    # ------------------------------------------------------------ events ---

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        ticket = await self.db.ticket_by_channel(message.channel.id)
        if ticket is None or ticket["status"] == config.STATUS_CLOSED:
            return
        cfg = await self.db.get_guild(message.guild.id)
        from_staff = message.author.id != ticket["owner_id"] and is_staff(message.author, cfg)
        changes = activity_changes(ticket, time.time(), from_staff)
        await self.db.update_ticket(ticket["id"], **changes)

    async def on_guild_channel_delete(self, channel):
        ticket = await self.db.ticket_by_channel(channel.id)
        if ticket is None:
            return
        if ticket["status"] != config.STATUS_CLOSED:
            await self.db.update_ticket(ticket["id"], status=config.STATUS_CLOSED,
                                  closed_at=time.time(), close_reason="Channel deleted")
        await self.db.mark_channel_deleted(ticket["id"])

    async def on_guild_remove(self, guild: discord.Guild):
        # The bot was removed from a server: delete all the data stored for it
        if await self.db.delete_guild(guild.id):
            print(f"Removed from {guild.name}: server data deleted")
        self.pending_links.pop(guild.id, None)

    # ---------------------------------------------------- background tasks ---

    @tasks.loop(minutes=5)
    async def maintenance(self):
        now = time.time()

        # Inactivity: warn, then close tickets waiting on the user
        for ticket in await self.db.active_tickets():
            guild = self.get_guild(ticket["guild_id"])
            channel = guild.get_channel(ticket["channel_id"]) if guild else None
            if channel is None:
                if guild is not None:
                    await self.on_guild_channel_delete(discord.Object(ticket["channel_id"]))
                continue
            cfg = await self.db.get_guild(guild.id)
            _ = translator(cfg)
            try:
                action = autoclose_action(ticket, now)
                if action == "warn":
                    await self.db.update_ticket(ticket["id"], warned=True)
                    await channel.send(_("auto.warning", user=f"<@{ticket['owner_id']}>",
                                         hours=config.WARNING_HOURS_BEFORE))
                elif action == "close":
                    reason = _("auto.reason", hours=config.AUTO_CLOSE_HOURS)
                    await channel.send(f"🔒 {reason}")
                    await close_ticket(self, channel, ticket, self.user, reason)
                elif cfg and cfg.get("staff_reminders", 1) and staff_reminder_due(ticket, now):
                    await self.remind_staff(channel, ticket, cfg, now)
            except discord.HTTPException as e:
                print(f"Inactivity check failed for #{channel}: {e}")

        # Closed tickets are deleted after the reopen window
        due = await self.db.closed_channels_due(now - config.CLOSED_CHANNEL_HOURS * 3600)
        for ticket in due:
            guild = self.get_guild(ticket["guild_id"])
            channel = guild.get_channel(ticket["channel_id"]) if guild else None
            await self.db.mark_channel_deleted(ticket["id"])
            if channel is not None:
                try:
                    await channel.delete(reason="Closed ticket expired")
                except discord.HTTPException as e:
                    print(f"Could not delete #{channel}: {e}")

    async def remind_staff(self, channel: discord.TextChannel, ticket: dict, cfg: dict,
                           now: float) -> None:
        """Remind the staff that a ticket has waited too long for a reply."""
        _ = translator(cfg)
        await self.db.update_ticket(ticket["id"], staff_reminded_at=now)
        waited = format_duration(now - waiting_for_staff_since(ticket))
        priority = priority_label(_, ticket.get("priority"))
        if ticket.get("claimed_by") or ticket.get("assigned_to"):
            target = f"<@{ticket.get('claimed_by') or ticket['assigned_to']}>"
        elif cfg.get("staff_role"):
            target = f"<@&{cfg['staff_role']}>"
        else:
            target = ""
        await channel.send(
            _("reminder.channel", target=target, waited=waited, priority=priority,
              hours=staff_reply_hours(ticket.get("priority"))).strip(),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=True, users=True),
        )
        await telegram_notify(self, cfg, _(
            "tg.reminder", guild=esc(channel.guild.name), channel=esc(channel.name),
            priority=priority, waited=waited, url=channel_url(channel.guild.id, channel.id),
        ))

    async def run_backup_if_due(self) -> None:
        """Back up the database every BACKUP_INTERVAL_HOURS, keeping the last BACKUP_KEEP.
        Only for SQLite: PostgreSQL is backed up with its own tools (pg_dump)."""
        settings = self.settings
        file = self.db.sqlite_file
        if settings.backup_keep <= 0 or file is None:
            return
        if not backup_due(settings.backups_path, settings.backup_interval_hours):
            return

        def copy():
            source = sqlite3.connect(file)
            try:
                return create_backup(source, settings.backups_path)
            finally:
                source.close()

        try:
            path = await asyncio.to_thread(copy)   # don't block the bot while copying
        except (OSError, RuntimeError, sqlite3.Error) as e:
            print(f"[backup] failed: {e}")
            return
        removed = prune_backups(settings.backups_path, settings.backup_keep)
        print(f"[backup] saved {path.name}" + (f", removed {len(removed)} old" if removed else ""))

    @tasks.loop(hours=1)
    async def hourly_cleanup(self):
        now = time.time()
        await self.run_backup_if_due()
        # Low/Medium transcripts in the log channel
        for guild_id in await self.db.guild_ids():
            guild = self.get_guild(guild_id)
            cfg = await self.db.get_guild(guild_id)
            if guild is None or cfg is None:
                continue
            for ref in expired_refs(await self.db.transcript_refs(guild_id), now,
                                    cfg["retention_days"]):
                channel = guild.get_channel(ref["channel_id"])
                if channel is not None:
                    try:
                        await channel.get_partial_message(ref["message_id"]).delete()
                    except discord.NotFound:
                        pass  # already deleted by hand
                    except discord.HTTPException as e:
                        print(f"Could not delete transcript {ref['message_id']}: {e}")
                        continue  # try again next hour
                await self.db.delete_transcript_ref(ref["channel_id"], ref["message_id"])
        # Old closed tickets used only for /stats
        await self.db.purge_expired_blocks(now)
        purged = await self.db.purge_closed_before(now - config.STATS_KEEP_DAYS * 86400)
        if purged:
            print(f"Purged {purged} old closed ticket(s)")

    @maintenance.before_loop
    @hourly_cleanup.before_loop
    async def before_loops(self):
        await self.wait_until_ready()


async def open_store(settings: Settings) -> Store:
    """Connect to the database, bring it to the latest schema, import a v1 config.json."""
    engine = create_engine(settings.db_url)
    try:
        status = await prepare(engine, settings.backups_path)
    except Exception:
        await engine.dispose()
        raise
    print(f"[database] {status}")
    store = Store(engine)
    migrated = await migrate_legacy_config(store, settings.legacy_config)
    if migrated:
        print(f"Migrated {migrated} server(s) from {settings.legacy_config}")
    return store


async def run_bot(settings: Settings, token: str) -> None:
    store = await open_store(settings)
    async with TicketBot(store, settings) as bot:   # closes the bot and the database
        await bot.start(token)


class _NoVoiceWarnings(logging.Filter):
    """The bot never joins voice channels: PyNaCl/davey are not needed."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()


def setup_logging() -> None:
    discord.utils.setup_logging()
    logging.getLogger("alembic").setLevel(logging.WARNING)  # the [database] line says it all
    logging.getLogger("discord.client").addFilter(_NoVoiceWarnings())


def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    token = settings.require_discord_token()
    setup_logging()
    try:
        asyncio.run(run_bot(settings, token))
    except KeyboardInterrupt:
        print("Stopped.")
