"""The Discord client: startup, events and background tasks."""

import asyncio
import sqlite3
import time

import aiohttp
import discord
from discord.ext import tasks

from . import __version__, config
from .backup import backup_due, create_backup, prune_backups
from .commands import all_commands
from .common import channel_url, esc, is_staff, priority_label, telegram_notify, translator
from .db import Database
from .i18n import CommandTranslator
from .logic import (
    activity_changes,
    autoclose_action,
    expired_refs,
    format_duration,
    staff_reminder_due,
    staff_reply_hours,
    waiting_for_staff_since,
)
from .migrate import migrate_legacy_config
from .telegram_notifier import TelegramError, TelegramNotifier
from .tickets import ClosedControls, RatingButton, TicketControls, TicketPanel, close_ticket


class TicketBot(discord.Client):
    def __init__(self, db: Database):
        intents = discord.Intents.default()
        intents.message_content = True  # required for transcripts
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.db = db
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
        if config.TELEGRAM_TOKEN:
            notifier = TelegramNotifier(config.TELEGRAM_TOKEN, self.http_session)
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
        self.db.close()

    async def on_ready(self):
        # Servers the bot was removed from while it was offline: delete their data
        current = {g.id for g in self.guilds}
        for guild_id in self.db.guild_ids():
            if guild_id not in current:
                self.db.delete_guild(guild_id)
                self.pending_links.pop(guild_id, None)
                print(f"Not in server {guild_id} anymore: server data deleted")
        print(f"TicketBot {__version__} online as {self.user} in {len(self.guilds)} server(s)")

    # ------------------------------------------------------------ events ---

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        ticket = self.db.ticket_by_channel(message.channel.id)
        if ticket is None or ticket["status"] == config.STATUS_CLOSED:
            return
        cfg = self.db.get_guild(message.guild.id)
        from_staff = message.author.id != ticket["owner_id"] and is_staff(message.author, cfg)
        self.db.update_ticket(ticket["id"], **activity_changes(ticket, time.time(), from_staff))

    async def on_guild_channel_delete(self, channel):
        ticket = self.db.ticket_by_channel(channel.id)
        if ticket is None:
            return
        if ticket["status"] != config.STATUS_CLOSED:
            self.db.update_ticket(ticket["id"], status=config.STATUS_CLOSED,
                                  closed_at=time.time(), close_reason="Channel deleted")
        self.db.mark_channel_deleted(ticket["id"])

    async def on_guild_remove(self, guild: discord.Guild):
        # The bot was removed from a server: delete all the data stored for it
        if self.db.delete_guild(guild.id):
            print(f"Removed from {guild.name}: server data deleted")
        self.pending_links.pop(guild.id, None)

    # ---------------------------------------------------- background tasks ---

    @tasks.loop(minutes=5)
    async def maintenance(self):
        now = time.time()

        # Inactivity: warn, then close tickets waiting on the user
        for ticket in self.db.active_tickets():
            guild = self.get_guild(ticket["guild_id"])
            channel = guild.get_channel(ticket["channel_id"]) if guild else None
            if channel is None:
                if guild is not None:
                    await self.on_guild_channel_delete(discord.Object(ticket["channel_id"]))
                continue
            cfg = self.db.get_guild(guild.id)
            _ = translator(cfg)
            try:
                action = autoclose_action(ticket, now)
                if action == "warn":
                    self.db.update_ticket(ticket["id"], warned=1)
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
        due = self.db.closed_channels_due(now - config.CLOSED_CHANNEL_HOURS * 3600)
        for ticket in due:
            guild = self.get_guild(ticket["guild_id"])
            channel = guild.get_channel(ticket["channel_id"]) if guild else None
            self.db.mark_channel_deleted(ticket["id"])
            if channel is not None:
                try:
                    await channel.delete(reason="Closed ticket expired")
                except discord.HTTPException as e:
                    print(f"Could not delete #{channel}: {e}")

    async def remind_staff(self, channel: discord.TextChannel, ticket: dict, cfg: dict,
                           now: float) -> None:
        """Remind the staff that a ticket has waited too long for a reply."""
        _ = translator(cfg)
        self.db.update_ticket(ticket["id"], staff_reminded_at=now)
        waited = format_duration(now - waiting_for_staff_since(ticket))
        priority = priority_label(_, ticket.get("priority"))
        if ticket.get("claimed_by"):
            target = f"<@{ticket['claimed_by']}>"
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

    def run_backup_if_due(self) -> None:
        """Back up the database every BACKUP_INTERVAL_HOURS, keeping the last BACKUP_KEEP."""
        if config.BACKUP_KEEP <= 0:
            return
        if not backup_due(config.BACKUP_DIR, config.BACKUP_INTERVAL_HOURS):
            return
        try:
            path = create_backup(self.db.conn, config.BACKUP_DIR)
        except (OSError, RuntimeError, sqlite3.Error) as e:
            print(f"[backup] failed: {e}")
            return
        removed = prune_backups(config.BACKUP_DIR, config.BACKUP_KEEP)
        print(f"[backup] saved {path.name}" + (f", removed {len(removed)} old" if removed else ""))

    @tasks.loop(hours=1)
    async def hourly_cleanup(self):
        now = time.time()
        self.run_backup_if_due()
        # Low/Medium transcripts in the log channel
        for guild_id in self.db.guild_ids():
            guild = self.get_guild(guild_id)
            cfg = self.db.get_guild(guild_id)
            if guild is None or cfg is None:
                continue
            for ref in expired_refs(self.db.transcript_refs(guild_id), now,
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
                self.db.delete_transcript_ref(ref["channel_id"], ref["message_id"])
        # Old closed tickets used only for /stats
        self.db.purge_expired_blocks(now)
        purged = self.db.purge_closed_before(now - config.STATS_KEEP_DAYS * 86400)
        if purged:
            print(f"Purged {purged} old closed ticket(s)")

    @maintenance.before_loop
    @hourly_cleanup.before_loop
    async def before_loops(self):
        await self.wait_until_ready()


def main() -> None:
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing: create a .env file (see .env.example).")
    db = Database(config.DB_PATH)
    migrated = migrate_legacy_config(db, config.LEGACY_CONFIG)
    if migrated:
        print(f"Migrated {migrated} server(s) from {config.LEGACY_CONFIG}")
    TicketBot(db).run(config.DISCORD_TOKEN)
