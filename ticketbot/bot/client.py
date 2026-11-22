"""The Discord client: startup, events and background tasks."""

import asyncio
import logging
import math
import sqlite3
import time

import aiohttp
import discord
from discord.ext import tasks

from .. import __version__
from ..core import config, crypto
from ..core.logic import (
    activity_changes,
    auto_escalation_level,
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
from ..db.encryption import encrypt_pending
from ..db.engine import create_engine
from ..db.legacy import migrate_legacy_config
from ..db.migrate import prepare
from ..integrations.telegram import TelegramError, TelegramNotifier
from . import telegram_bridge
from .commands import all_commands
from .common import (
    channel_url,
    esc,
    is_staff,
    priority_label,
    staff_mentions,
    telegram_notify,
    ticket_channel,
    translator,
)
from .report import send_weekly_reports
from .tickets import (
    ClosedControls,
    RatingButton,
    TicketControls,
    TicketPanel,
    close_ticket,
    escalate,
)
from .translator import CommandTranslator
from .web_commands import CommandError, delete_transcript_messages, run_web_command


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
        self.telegram_codes: dict[str, dict] = {}       # /telegram-account link codes
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
                self._telegram_poller = asyncio.create_task(notifier.poll_forever(
                    lambda message: telegram_bridge.handle_message(self, message),
                    lambda query: telegram_bridge.handle_button(self, query)))
                print(f"[telegram] connected as @{notifier.username}")

        retried = await self.db.reset_running_commands()
        if retried:
            print(f"[web] {retried} interrupted command(s) will be retried")
        self.started_at = time.time()
        self.maintenance.start()
        self.hourly_cleanup.start()
        self.web_commands.start()
        self.heartbeat.start()

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
                await self.db.delete_guild(guild_id, self.settings.legal_hold_days)
                await self.db.audit(None, None, "guild.removed", source="system",
                                    target=f"guild:{guild_id}")
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
        if cfg:
            await telegram_bridge.forward_user_message(self, message, ticket, cfg)

    async def on_guild_channel_delete(self, channel):
        ticket = await self.db.ticket_by_channel(channel.id)
        if ticket is None:
            return
        if ticket["status"] != config.STATUS_CLOSED:
            await self.db.update_ticket(ticket["id"], status=config.STATUS_CLOSED,
                                  closed_at=time.time(), close_reason="Channel deleted")
            await self.db.audit(ticket["guild_id"], None, "ticket.channel_deleted",
                                source="system", target=f"ticket:{ticket['id']}")
        await self.db.mark_channel_deleted(ticket["id"])

    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent):
        await self.on_guild_channel_delete(discord.Object(payload.thread_id))

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        await self.archive_messages_deleted(payload.guild_id, payload.channel_id,
                                            [payload.message_id])

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        await self.archive_messages_deleted(payload.guild_id, payload.channel_id,
                                            list(payload.message_ids))

    async def archive_messages_deleted(self, guild_id: int | None, channel_id: int,
                                       message_ids: list[int]) -> int:
        """A transcript deleted from the archive channel deletes its ticket everywhere:
        dashboard, statistics, the log copy (a hidden copy stays for LEGAL_HOLD_DAYS)."""
        cfg = await self.db.get_guild(guild_id) if guild_id else None
        if not cfg or cfg.get("archive_channel") != channel_id:
            return 0
        deleted = 0
        for message_id in message_ids:
            transcript = await self.db.transcript_by_archive_message(message_id)
            if transcript is None or transcript["ticket_id"] is None:
                continue
            ticket = await self.db.get_ticket(transcript["ticket_id"])
            telegram = await self.db.telegram_messages_of(transcript["ticket_id"])
            removed = await self.db.delete_ticket(transcript["ticket_id"],
                                                  self.settings.legal_hold_days)
            await self.db.audit(guild_id, None, "ticket.delete", source="discord",
                                target=f"ticket:{transcript['ticket_id']}",
                                details={"why": "transcript deleted from the archive"})
            channel_id = (ticket["channel_id"] if ticket and not ticket["channel_deleted"]
                          else None)
            await delete_transcript_messages(self, guild_id, removed, keep=message_id,
                                             channel_id=channel_id, telegram=telegram)
            deleted += 1
        return deleted

    async def on_guild_remove(self, guild: discord.Guild):
        # The bot was removed from a server: delete all the data stored for it
        if await self.db.delete_guild(guild.id, self.settings.legal_hold_days):
            await self.db.audit(None, None, "guild.removed", source="system",
                                target=f"guild:{guild.id}")
            print(f"Removed from {guild.name}: server data deleted")
        self.pending_links.pop(guild.id, None)

    # ---------------------------------------------------- background tasks ---

    @tasks.loop(minutes=5)
    async def maintenance(self):
        now = time.time()

        try:
            await send_weekly_reports(self, now)
        except Exception as e:                     # never stop the other checks
            print(f"[report] {e}")

        # Inactivity: warn, then close tickets waiting on the user
        for ticket in await self.db.active_tickets():
            guild = self.get_guild(ticket["guild_id"])
            if guild is None:
                continue
            try:
                channel = await ticket_channel(guild, ticket)
            except discord.HTTPException:
                continue  # Discord unreachable: try again later, don't close anything
            if channel is None:
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
                else:
                    levels = await self.db.escalation_levels(guild.id) if cfg else []
                    target = auto_escalation_level(ticket, levels, now)
                    escalated = target is not None and await escalate(
                        self, guild, channel, ticket, cfg, target, None, None)
                    if not escalated and cfg and cfg.get("staff_reminders", 1) and \
                            staff_reminder_due(ticket, now):
                        await self.remind_staff(channel, ticket, cfg, now)
            except discord.HTTPException as e:
                print(f"Inactivity check failed for #{channel}: {e}")

        # Closed tickets are deleted after the reopen window
        due = await self.db.closed_channels_due(now - config.CLOSED_CHANNEL_HOURS * 3600)
        for ticket in due:
            guild = self.get_guild(ticket["guild_id"])
            try:
                channel = await ticket_channel(guild, ticket) if guild else None
            except discord.HTTPException:
                continue
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
        else:
            target = staff_mentions(
                cfg, await self.db.type_roles(ticket["guild_id"], ticket["type_key"]))
        await channel.send(
            _("reminder.channel", target=target, waited=waited, priority=priority,
              hours=staff_reply_hours(ticket.get("priority"))).strip(),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=True, users=True),
        )
        await telegram_notify(self, cfg, _(
            "tg.reminder", guild=esc(channel.guild.name), channel=esc(channel.name),
            priority=priority, waited=waited, url=channel_url(channel.guild.id, channel.id),
        ), ticket_id=ticket["id"])

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
        await self.db.purge_audit_before(now - config.AUDIT_KEEP_DAYS * 86400)
        await self.db.purge_faq_results_before(now - config.STATS_KEEP_DAYS * 86400)
        await self.db.purge_web_sessions(now)
        await self.db.purge_telegram_messages_before(telegram_bridge.purge_before(now))
        await self.db.purge_finished_commands(now - config.COMMANDS_KEEP_DAYS * 86400)
        await self.db.purge_held_transcripts(now)
        purged = await self.db.purge_closed_before(now - config.STATS_KEEP_DAYS * 86400,
                                                   self.settings.legal_hold_days)
        if purged:
            print(f"Purged {purged} old closed ticket(s)")

    # ------------------------------------------------- commands from the web ---

    @tasks.loop(seconds=config.HEARTBEAT_SECONDS)
    async def heartbeat(self):
        """Tell the web server (dashboard, Prometheus metrics) that the bot is alive."""
        latency = self.latency if math.isfinite(self.latency) else None
        try:
            await self.db.save_bot_status(
                version=__version__, started_at=getattr(self, "started_at", time.time()),
                heartbeat_at=time.time(), guilds=len(self.guilds), latency=latency)
        except Exception as e:                       # e.g. the database is restarting
            print(f"[heartbeat] {e}")

    @tasks.loop(seconds=config.WEB_COMMAND_POLL_SECONDS)
    async def web_commands(self):
        for command in await self.db.take_commands():
            try:
                result = await self.run_web_command(command)
            except CommandError as e:
                await self.db.finish_command(command["id"], False, str(e))
            except Exception as e:  # noqa: BLE001 - one failed command must not stop the loop
                logging.getLogger(__name__).exception("Web command %s failed",
                                                      command["kind"])
                await self.db.finish_command(command["id"], False, f"{type(e).__name__}: {e}")
            else:
                await self.db.finish_command(command["id"], True, result)

    async def run_web_command(self, command: dict) -> str:
        """Carry out an action asked from the web dashboard. Returns a short result."""
        return await run_web_command(self, command)

    @maintenance.before_loop
    @hourly_cleanup.before_loop
    @web_commands.before_loop
    async def before_loops(self):
        await self.wait_until_ready()


async def open_store(settings: Settings) -> Store:
    """Connect to the database, bring it to the latest schema, import a v1 config.json."""
    crypto.configure(settings.keyring())
    engine = create_engine(settings.db_url)
    try:
        status = await prepare(engine, settings.backups_path)
        encrypted = await encrypt_pending(engine)
    except Exception:
        await engine.dispose()
        raise
    print(f"[database] {status}")
    if encrypted:
        print(f"[database] encrypted the sensitive data of {encrypted} row(s)")
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
    settings.keyring()  # fail before connecting when ENCRYPTION_KEY is missing
    setup_logging()
    try:
        asyncio.run(run_bot(settings, token))
    except KeyboardInterrupt:
        print("Stopped.")
