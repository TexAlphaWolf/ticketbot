"""
TicketBot - A ticket bot for Discord.

Users choose a ticket type and open a ticket: the bot creates a private
channel visible only to the user and the staff team. Staff can claim the
ticket; when it is closed, a transcript is saved to the log and archive
channels. Tickets waiting on the user are closed automatically after 24 hours
without a reply, and each server can receive notifications on its own
Telegram chat.
"""

import asyncio
import html
import io
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from telegram_notifier import TelegramError, TelegramNotifier

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CONFIG_FILE = "config.json"
TOPIC_PREFIX = "ticket-owner:"
COLOR = discord.Color.blurple()

AUTO_CLOSE_HOURS = 24          # close after this many hours without a user reply
WARNING_HOURS_BEFORE = 4       # warn the user this many hours before closing
VERIFY_CODE_TTL = 10 * 60      # Telegram verification code lifetime (seconds)
VERIFY_MAX_ATTEMPTS = 5

TICKET_TYPES = {
    "support": ("Support", "🛠️", "General help or questions"),
    "bug": ("Bug report", "🐞", "Something is broken or not working"),
    "report": ("User report", "🚨", "Report a member or a rule violation"),
    "other": ("Other", "💬", "Anything else"),
}

STATUS_WAITING = "waiting"          # nobody from the staff has picked it up yet
STATUS_IN_PROGRESS = "in_progress"  # claimed or answered by the staff


# ---------------------------------------------------------------- config ---

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_config() -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


config = load_config()


def guild_cfg(guild: discord.Guild | None) -> dict | None:
    if guild is None:
        return None
    return config.get(str(guild.id))


def is_staff(member: discord.abc.User, cfg: dict) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.id == cfg["staff_role"] for role in member.roles)


def type_label(type_key: str) -> str:
    label, emoji, _ = TICKET_TYPES.get(type_key, TICKET_TYPES["other"])
    return f"{emoji} {label}"


# ---------------------------------------------------------- ticket state ---

def new_ticket_state(owner_id: int, type_key: str, subject: str, now: float) -> dict:
    return {
        "owner": owner_id,
        "type": type_key,
        "subject": subject,
        "status": STATUS_WAITING,
        "claimed_by": None,
        "opened_at": now,
        "last_actor": None,      # "user" or "staff": who wrote the last message
        "last_activity": now,
        "warned": False,
    }


def owner_from_topic(channel) -> int | None:
    """Fallback for tickets opened before v1.1 (owner stored in the topic)."""
    topic = getattr(channel, "topic", None) or ""
    if topic.startswith(TOPIC_PREFIX):
        try:
            return int(topic[len(TOPIC_PREFIX):].split()[0])
        except (ValueError, IndexError):
            return None
    return None


def get_ticket(cfg: dict | None, channel) -> dict | None:
    if cfg is None or channel is None:
        return None
    tickets = cfg.setdefault("tickets", {})
    ticket = tickets.get(str(channel.id))
    if ticket is None:
        owner = owner_from_topic(channel)
        if owner is None:
            return None
        ticket = new_ticket_state(owner, "other", "", time.time())
        tickets[str(channel.id)] = ticket
        save_config()
    return ticket


def queue_counts(cfg: dict) -> tuple[int, int]:
    """Return (waiting, in_progress) for the open tickets of a server."""
    waiting = in_progress = 0
    for ticket in cfg.get("tickets", {}).values():
        if ticket.get("status") == STATUS_IN_PROGRESS:
            in_progress += 1
        else:
            waiting += 1
    return waiting, in_progress


def autoclose_action(ticket: dict, now: float) -> str | None:
    """
    Decide what to do with an idle ticket.

    The timer only runs while the ticket is waiting on the USER (the last
    message came from the staff). A ticket waiting on the staff is never
    closed automatically.
    """
    if ticket.get("last_actor") != "staff":
        return None
    idle = now - ticket.get("last_activity", now)
    if idle >= AUTO_CLOSE_HOURS * 3600:
        return "close"
    if (idle >= (AUTO_CLOSE_HOURS - WARNING_HOURS_BEFORE) * 3600
            and not ticket.get("warned")):
        return "warn"
    return None


# ------------------------------------------------------------- telegram ---

async def telegram_notify(guild: discord.Guild, text: str,
                          document: bytes | None = None,
                          filename: str | None = None) -> None:
    """Send a notification to the Telegram chat linked to this server only."""
    tg = bot.telegram
    link = (guild_cfg(guild) or {}).get("telegram") or {}
    if tg is None or not link.get("verified") or not link.get("chat_id"):
        return
    try:
        if document is not None:
            await tg.send_document(link["chat_id"], document, filename or "transcript.txt",
                                   caption=text)
        else:
            await tg.send_message(link["chat_id"], text)
    except TelegramError as e:
        print(f"[telegram] could not notify {guild.name}: {e}")


def channel_url(channel: discord.abc.GuildChannel) -> str:
    return f"https://discord.com/channels/{channel.guild.id}/{channel.id}"


# --------------------------------------------------------------- tickets ---

async def build_transcript(channel: discord.TextChannel, ticket: dict,
                           closed_by: str, reason: str) -> bytes:
    opened = datetime.fromtimestamp(ticket.get("opened_at", time.time()), timezone.utc)
    lines = [
        f"Transcript of #{channel.name}",
        f"Type:      {type_label(ticket.get('type', 'other'))}",
        f"Subject:   {ticket.get('subject') or '-'}",
        f"Opened by: {ticket.get('owner')}",
        f"Opened at: {opened:%Y-%m-%d %H:%M} UTC",
        f"Closed by: {closed_by}",
        f"Reason:    {reason}",
        "=" * 40,
    ]
    async for msg in channel.history(limit=None, oldest_first=True):
        stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
        text = msg.content
        for embed in msg.embeds:
            text += f" [embed: {embed.title or ''} {embed.description or ''}]"
        for att in msg.attachments:
            text += f" [attachment: {att.url}]"
        lines.append(f"[{stamp}] {msg.author}: {text}")
    return "\n".join(lines).encode("utf-8")


def transcript_file(data: bytes, name: str) -> discord.File:
    # A discord.File can only be sent once: create a new one for every send
    return discord.File(io.BytesIO(data), filename=f"{name}.txt")


class TicketModal(discord.ui.Modal):
    subject = discord.ui.TextInput(label="Subject", max_length=100)
    description = discord.ui.TextInput(
        label="Describe your issue",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, type_key: str):
        label, _, _ = TICKET_TYPES[type_key]
        super().__init__(title=f"{label} ticket")
        self.type_key = type_key

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = guild_cfg(guild)
        user = interaction.user
        category = guild.get_channel(cfg["category"])
        staff_role = guild.get_role(cfg["staff_role"])

        if category is None or staff_role is None:
            await interaction.response.send_message(
                "The ticket system is not configured correctly. Please contact an admin.",
                ephemeral=True,
            )
            return

        # Only one open ticket per user
        tickets = cfg.setdefault("tickets", {})
        for cid, ticket in tickets.items():
            if ticket.get("owner") == user.id:
                await interaction.response.send_message(
                    f"You already have an open ticket: <#{cid}>", ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        waiting, in_progress = queue_counts(cfg)
        cfg["counter"] = cfg.get("counter", 0) + 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                attach_files=True, read_message_history=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True,
                read_message_history=True, manage_messages=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                manage_channels=True, read_message_history=True,
            ),
        }

        channel = await guild.create_text_channel(
            name=f"{self.type_key}-{cfg['counter']:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"{TOPIC_PREFIX}{user.id}",
        )
        tickets[str(channel.id)] = new_ticket_state(
            user.id, self.type_key, self.subject.value, time.time()
        )
        save_config()

        queue_text = (f"**{waiting}** waiting · **{in_progress}** in progress"
                      if waiting or in_progress else "none, you're first in line!")

        embed = discord.Embed(
            title=f"🎫 {self.subject.value}",
            description=self.description.value,
            color=COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Type", value=type_label(self.type_key))
        embed.add_field(name="Other open tickets", value=queue_text)
        embed.set_footer(text=(
            "The staff team will reply here as soon as possible. "
            f"If the staff asks you something, please reply within {AUTO_CLOSE_HOURS} "
            "hours or the ticket will be closed automatically."
        ))

        await channel.send(
            content=f"{user.mention} {staff_role.mention}",
            embed=embed,
            view=TicketControls(),
        )
        await interaction.followup.send(
            f"Ticket created: {channel.mention}\n📊 Other open tickets: {queue_text}",
            ephemeral=True,
        )

        await telegram_notify(guild, (
            f"🎫 <b>New ticket</b> on <b>{html.escape(guild.name)}</b>\n\n"
            f"<b>Type:</b> {type_label(self.type_key)}\n"
            f"<b>From:</b> {html.escape(str(user))}\n"
            f"<b>Subject:</b> {html.escape(self.subject.value)}\n\n"
            f"{html.escape(self.description.value[:500])}\n\n"
            f"📊 Other open tickets: {waiting} waiting · {in_progress} in progress\n"
            f"<a href=\"{channel_url(channel)}\">Open in Discord</a>"
        ))


class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji, description=desc)
            for key, (label, emoji, desc) in TICKET_TYPES.items()
        ]
        super().__init__(placeholder="Choose the ticket type...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketModal(self.values[0]))


class TicketTypeView(discord.ui.View):
    """Ephemeral menu shown after clicking 'Open ticket'."""

    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(TicketTypeSelect())


class TicketPanel(discord.ui.View):
    """Panel with the button to open tickets (persistent)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open ticket", emoji="📩",
                       style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        if guild_cfg(interaction.guild) is None:
            await interaction.response.send_message(
                "The ticket system has not been set up yet.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "What do you need help with?", view=TicketTypeView(), ephemeral=True
        )


class TicketControls(discord.ui.View):
    """Buttons inside each ticket (persistent)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", emoji="✋",
                       style=discord.ButtonStyle.secondary, custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_cfg(interaction.guild)
        if cfg is None or not is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "Only staff members can claim a ticket.", ephemeral=True
            )
            return
        ticket = get_ticket(cfg, interaction.channel)
        if ticket is not None:
            ticket["status"] = STATUS_IN_PROGRESS
            ticket["claimed_by"] = interaction.user.id
            save_config()
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            f"✋ {interaction.user.mention} has claimed this ticket."
        )

    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, _):
        await handle_close_request(interaction, None)


async def handle_close_request(interaction: discord.Interaction, reason: str | None):
    cfg = guild_cfg(interaction.guild)
    ticket = get_ticket(cfg, interaction.channel)
    if ticket is None:
        await interaction.response.send_message(
            "This command only works inside a ticket.", ephemeral=True
        )
        return
    staff = is_staff(interaction.user, cfg)
    is_owner = interaction.user.id == ticket.get("owner")
    if not (staff or is_owner):
        await interaction.response.send_message(
            "You can't close this ticket.", ephemeral=True
        )
        return
    if not reason:
        reason = "Closed by the user" if is_owner else "Closed by the staff"
    await interaction.response.send_message("🔒 Closing the ticket...")
    await close_ticket(interaction.channel, cfg, interaction.user, reason)


async def close_ticket(channel: discord.TextChannel, cfg: dict,
                       closed_by: discord.abc.User, reason: str) -> None:
    ticket = get_ticket(cfg, channel) or {}
    owner_id = ticket.get("owner")
    data = await build_transcript(channel, ticket, str(closed_by), reason)

    embed = discord.Embed(
        title=f"Ticket closed: #{channel.name}",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Type", value=type_label(ticket.get("type", "other")))
    embed.add_field(name="Opened by",
                    value=f"<@{owner_id}>" if owner_id else "unknown")
    embed.add_field(name="Closed by", value=closed_by.mention)
    embed.add_field(name="Reason", value=reason, inline=False)

    # Log channel + archive channel (no duplicates if they are the same)
    target_ids = []
    for key in ("log_channel", "archive_channel"):
        cid = cfg.get(key)
        if cid and cid not in target_ids:
            target_ids.append(cid)
    for cid in target_ids:
        target = channel.guild.get_channel(cid)
        if target is not None:
            try:
                await target.send(embed=embed, file=transcript_file(data, channel.name))
            except discord.HTTPException as e:
                print(f"Could not send the transcript to {target}: {e}")

    if owner_id:
        owner = channel.guild.get_member(owner_id)
        if owner is not None:
            try:
                await owner.send(
                    f"Your ticket **#{channel.name}** on **{channel.guild.name}** "
                    f"has been closed.\n**Reason:** {reason}",
                    file=transcript_file(data, channel.name),
                )
            except discord.Forbidden:
                pass  # DMs disabled

    await telegram_notify(
        channel.guild,
        (f"🔒 <b>Ticket closed</b> on <b>{html.escape(channel.guild.name)}</b>\n"
         f"#{html.escape(channel.name)} · {type_label(ticket.get('type', 'other'))}\n"
         f"<b>Closed by:</b> {html.escape(str(closed_by))}\n"
         f"<b>Reason:</b> {html.escape(reason)}"),
        document=data,
        filename=f"{channel.name}.txt",
    )

    cfg.get("tickets", {}).pop(str(channel.id), None)
    save_config()
    await channel.delete(reason=f"Ticket closed by {closed_by}: {reason}")


# ------------------------------------------------------------------- bot ---

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # required for transcripts
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.http_session: aiohttp.ClientSession | None = None
        self.telegram: TelegramNotifier | None = None
        self._telegram_poller: asyncio.Task | None = None

    async def setup_hook(self):
        # Buttons keep working after a restart
        self.add_view(TicketPanel())
        self.add_view(TicketControls())
        self.tree.add_command(telegram_group)
        await self.tree.sync()

        self.http_session = aiohttp.ClientSession()
        if TELEGRAM_TOKEN:
            notifier = TelegramNotifier(TELEGRAM_TOKEN, self.http_session)
            try:
                await notifier.get_me()
            except TelegramError as e:
                print(f"[telegram] disabled, invalid TELEGRAM_BOT_TOKEN: {e}")
            else:
                self.telegram = notifier
                self._telegram_poller = asyncio.create_task(notifier.poll_forever())
                print(f"[telegram] connected as @{notifier.username}")

        self.inactivity_check.start()

    async def close(self):
        if self._telegram_poller is not None:
            self._telegram_poller.cancel()
        if self.http_session is not None:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        print(f"TicketBot online as {self.user}")

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        cfg = guild_cfg(message.guild)
        ticket = get_ticket(cfg, message.channel)
        if ticket is None:
            return
        from_staff = (message.author.id != ticket.get("owner")
                      and is_staff(message.author, cfg))
        ticket["last_actor"] = "staff" if from_staff else "user"
        ticket["last_activity"] = time.time()
        ticket["warned"] = False
        if from_staff and ticket.get("status") == STATUS_WAITING:
            ticket["status"] = STATUS_IN_PROGRESS
        save_config()

    async def on_guild_channel_delete(self, channel):
        cfg = guild_cfg(channel.guild)
        if cfg and cfg.get("tickets", {}).pop(str(channel.id), None) is not None:
            save_config()

    @tasks.loop(minutes=5)
    async def inactivity_check(self):
        now = time.time()
        for guild_id, cfg in list(config.items()):
            guild = self.get_guild(int(guild_id))
            if guild is None:
                continue
            for channel_id, ticket in list(cfg.get("tickets", {}).items()):
                channel = guild.get_channel(int(channel_id))
                if channel is None:
                    cfg["tickets"].pop(channel_id, None)
                    save_config()
                    continue
                try:
                    action = autoclose_action(ticket, now)
                    if action == "warn":
                        ticket["warned"] = True
                        save_config()
                        await channel.send(
                            f"⏰ <@{ticket['owner']}> the staff is waiting for your reply. "
                            f"This ticket will be closed automatically in "
                            f"{WARNING_HOURS_BEFORE} hours if there is no response."
                        )
                    elif action == "close":
                        await channel.send(
                            "🔒 Closing this ticket: no response from the user "
                            f"within {AUTO_CLOSE_HOURS} hours."
                        )
                        await close_ticket(
                            channel, cfg, self.user,
                            f"No response from the user within {AUTO_CLOSE_HOURS} hours",
                        )
                except discord.HTTPException as e:
                    print(f"Inactivity check failed for #{channel}: {e}")

    @inactivity_check.before_loop
    async def before_inactivity_check(self):
        await self.wait_until_ready()


bot = TicketBot()


# -------------------------------------------------------------- commands ---

@bot.tree.command(name="setup", description="Set up the ticket system and post the panel")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
@app_commands.describe(
    staff_role="Role of the moderators who handle tickets",
    category="Category where ticket channels are created",
    log_channel="Channel where transcripts are logged",
    panel_channel="Channel where the 'Open ticket' button is posted",
    archive_channel="(Optional) Archive channel that also receives transcripts",
)
async def setup(interaction: discord.Interaction, staff_role: discord.Role,
                category: discord.CategoryChannel, log_channel: discord.TextChannel,
                panel_channel: discord.TextChannel,
                archive_channel: discord.TextChannel | None = None):
    cfg = config.setdefault(str(interaction.guild.id), {})
    cfg.update(staff_role=staff_role.id, category=category.id, log_channel=log_channel.id)
    if archive_channel is not None:
        cfg["archive_channel"] = archive_channel.id
    cfg.setdefault("counter", 0)
    cfg.setdefault("tickets", {})
    save_config()

    types = "\n".join(f"{emoji} **{label}**: {desc}"
                      for label, emoji, desc in TICKET_TYPES.values())
    embed = discord.Embed(
        title="🎫 Support",
        description=(
            "Having an issue, found a bug or need to report something?\n"
            "Click the button below, choose the ticket type and a private "
            "channel with the staff team will be opened.\n\n" + types
        ),
        color=COLOR,
    )
    await panel_channel.send(embed=embed, view=TicketPanel())
    await interaction.response.send_message(
        f"Ticket system configured. Panel posted in {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="archive",
                  description="Set or remove the transcript archive channel")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
@app_commands.describe(channel="Archive channel (leave empty to disable it)")
async def archive(interaction: discord.Interaction,
                  channel: discord.TextChannel | None = None):
    cfg = guild_cfg(interaction.guild)
    if cfg is None:
        await interaction.response.send_message(
            "Set up the ticket system with /setup first.", ephemeral=True
        )
        return
    cfg["archive_channel"] = channel.id if channel else None
    save_config()
    msg = (f"📁 Transcripts will also be saved in {channel.mention}."
           if channel else "📁 Archive channel disabled.")
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="queue", description="Show how many tickets are open right now")
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild)
    if cfg is None:
        await interaction.response.send_message(
            "The ticket system has not been set up yet.", ephemeral=True
        )
        return
    waiting, in_progress = queue_counts(cfg)
    await interaction.response.send_message(
        f"📊 Open tickets: **{waiting}** waiting · **{in_progress}** in progress",
        ephemeral=True,
    )


async def require_staff_in_ticket(interaction: discord.Interaction) -> bool:
    cfg = guild_cfg(interaction.guild)
    if get_ticket(cfg, interaction.channel) is None:
        await interaction.response.send_message(
            "This command only works inside a ticket.", ephemeral=True
        )
        return False
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(
            "Only staff members can use this command.", ephemeral=True
        )
        return False
    return True


@bot.tree.command(name="add", description="Add a user to the ticket")
@app_commands.guild_only()
async def add(interaction: discord.Interaction, user: discord.Member):
    if not await require_staff_in_ticket(interaction):
        return
    await interaction.channel.set_permissions(
        user, view_channel=True, send_messages=True,
        attach_files=True, read_message_history=True,
    )
    await interaction.response.send_message(f"➕ {user.mention} has been added to the ticket.")


@bot.tree.command(name="remove", description="Remove a user from the ticket")
@app_commands.guild_only()
async def remove(interaction: discord.Interaction, user: discord.Member):
    if not await require_staff_in_ticket(interaction):
        return
    ticket = get_ticket(guild_cfg(interaction.guild), interaction.channel)
    if user.id == ticket.get("owner"):
        await interaction.response.send_message(
            "You can't remove the user who opened the ticket.", ephemeral=True
        )
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"➖ {user.mention} has been removed from the ticket.")


@bot.tree.command(name="close", description="Close the current ticket")
@app_commands.guild_only()
@app_commands.describe(reason="(Optional) Reason for closing the ticket")
async def close_cmd(interaction: discord.Interaction, reason: str | None = None):
    await handle_close_request(interaction, reason)


# ------------------------------------------------------ telegram commands ---

telegram_group = app_commands.Group(
    name="telegram",
    description="Ticket notifications on Telegram",
    default_permissions=discord.Permissions(administrator=True),
    guild_only=True,
)

# guild_id -> {"chat_id", "code", "expires", "attempts"}
pending_links: dict[int, dict] = {}


async def telegram_ready(interaction: discord.Interaction) -> bool:
    if bot.telegram is None:
        await interaction.response.send_message(
            "Telegram notifications are not enabled on this bot "
            "(TELEGRAM_BOT_TOKEN is missing).", ephemeral=True
        )
        return False
    if guild_cfg(interaction.guild) is None:
        await interaction.response.send_message(
            "Set up the ticket system with /setup first.", ephemeral=True
        )
        return False
    return True


@telegram_group.command(name="link", description="Link a Telegram chat to this server")
@app_commands.describe(chat_id="Telegram chat ID (send /start to the Telegram bot to get it)")
async def telegram_link(interaction: discord.Interaction, chat_id: str):
    if not await telegram_ready(interaction):
        return
    chat_id = chat_id.strip()
    if not re.fullmatch(r"-?\d{1,20}", chat_id):
        await interaction.response.send_message(
            "That doesn't look like a valid chat ID (it should be a number).",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        await bot.telegram.send_message(chat_id, (
            f"🔐 Verification code for <b>{html.escape(interaction.guild.name)}</b>: "
            f"<code>{code}</code>\n\n"
            "Run <code>/telegram verify</code> in Discord with this code. "
            f"It expires in {VERIFY_CODE_TTL // 60} minutes.\n"
            "If you didn't request this, just ignore this message."
        ))
    except TelegramError:
        await interaction.followup.send(
            "I couldn't send a message to that chat. Open "
            f"**@{bot.telegram.username}** on Telegram and press **Start** "
            "(for a group, add the bot to the group first), then try again.",
            ephemeral=True,
        )
        return

    pending_links[interaction.guild.id] = {
        "chat_id": chat_id,
        "code": code,
        "expires": time.time() + VERIFY_CODE_TTL,
        "attempts": 0,
    }
    await interaction.followup.send(
        "📨 I sent a verification code to that Telegram chat. "
        "Run `/telegram verify code:<code>` to complete the link.",
        ephemeral=True,
    )


@telegram_group.command(name="verify", description="Confirm the Telegram link with the code")
@app_commands.describe(code="The 6-digit code you received on Telegram")
async def telegram_verify(interaction: discord.Interaction, code: str):
    if not await telegram_ready(interaction):
        return
    pending = pending_links.get(interaction.guild.id)
    if pending is None or time.time() > pending["expires"]:
        pending_links.pop(interaction.guild.id, None)
        await interaction.response.send_message(
            "No valid code to verify. Run `/telegram link` again.", ephemeral=True
        )
        return
    pending["attempts"] += 1
    if not secrets.compare_digest(code.strip(), pending["code"]):
        if pending["attempts"] >= VERIFY_MAX_ATTEMPTS:
            pending_links.pop(interaction.guild.id, None)
            msg = "Wrong code. Too many attempts: run `/telegram link` again."
        else:
            left = VERIFY_MAX_ATTEMPTS - pending["attempts"]
            msg = f"Wrong code. {left} attempts left."
        await interaction.response.send_message(msg, ephemeral=True)
        return

    cfg = guild_cfg(interaction.guild)
    cfg["telegram"] = {"chat_id": pending["chat_id"], "verified": True}
    save_config()
    pending_links.pop(interaction.guild.id, None)
    await interaction.response.send_message(
        "✅ Telegram linked! New and closed tickets of this server will be "
        "notified to that chat only.", ephemeral=True
    )
    await telegram_notify(
        interaction.guild,
        f"✅ This chat is now linked to <b>{html.escape(interaction.guild.name)}</b>.",
    )


@telegram_group.command(name="status", description="Show the Telegram link of this server")
async def telegram_status(interaction: discord.Interaction):
    if not await telegram_ready(interaction):
        return
    link = guild_cfg(interaction.guild).get("telegram") or {}
    if link.get("verified"):
        msg = f"✅ Linked to Telegram chat `{link['chat_id']}`."
    else:
        msg = ("❌ No Telegram chat linked. Send /start to "
               f"**@{bot.telegram.username}** on Telegram, then use `/telegram link`.")
    await interaction.response.send_message(msg, ephemeral=True)


@telegram_group.command(name="test", description="Send a test notification to Telegram")
async def telegram_test(interaction: discord.Interaction):
    if not await telegram_ready(interaction):
        return
    if not (guild_cfg(interaction.guild).get("telegram") or {}).get("verified"):
        await interaction.response.send_message(
            "No Telegram chat linked yet. Use `/telegram link` first.", ephemeral=True
        )
        return
    await telegram_notify(
        interaction.guild,
        f"🔔 Test notification from <b>{html.escape(interaction.guild.name)}</b>.",
    )
    await interaction.response.send_message("🔔 Test notification sent.", ephemeral=True)


@telegram_group.command(name="unlink", description="Stop sending notifications to Telegram")
async def telegram_unlink(interaction: discord.Interaction):
    if not await telegram_ready(interaction):
        return
    guild_cfg(interaction.guild).pop("telegram", None)
    pending_links.pop(interaction.guild.id, None)
    save_config()
    await interaction.response.send_message("🔕 Telegram notifications disabled.",
                                            ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing: create a .env file (see .env.example).")
    bot.run(TOKEN)
