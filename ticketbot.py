"""
TicketBot - A ticket bot for Discord.

Users open a ticket with a button: the bot creates a private channel visible
only to the user and the staff team. Staff can claim the ticket; when it is
closed, a transcript is saved to the log channel and the archive channel.
"""

import io
import json
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
TOPIC_PREFIX = "ticket-owner:"
COLOR = discord.Color.blurple()


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


def guild_cfg(guild: discord.Guild) -> dict | None:
    return config.get(str(guild.id))


def is_staff(member: discord.Member, cfg: dict) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id == cfg["staff_role"] for role in member.roles)


def ticket_owner_id(channel: discord.abc.GuildChannel) -> int | None:
    topic = getattr(channel, "topic", None) or ""
    if topic.startswith(TOPIC_PREFIX):
        try:
            return int(topic[len(TOPIC_PREFIX):].split()[0])
        except ValueError:
            return None
    return None


# --------------------------------------------------------------- tickets ---

async def build_transcript(channel: discord.TextChannel) -> bytes:
    lines = [f"Transcript of #{channel.name}", "=" * 40]
    async for msg in channel.history(limit=None, oldest_first=True):
        time = msg.created_at.strftime("%Y-%m-%d %H:%M")
        text = msg.content
        for embed in msg.embeds:
            text += f" [embed: {embed.title or ''} {embed.description or ''}]"
        for att in msg.attachments:
            text += f" [attachment: {att.url}]"
        lines.append(f"[{time}] {msg.author}: {text}")
    return "\n".join(lines).encode("utf-8")


def transcript_file(data: bytes, name: str) -> discord.File:
    # A discord.File can only be sent once: create a new one for every send
    return discord.File(io.BytesIO(data), filename=f"{name}.txt")


class TicketModal(discord.ui.Modal, title="Open a ticket"):
    subject = discord.ui.TextInput(label="Subject", max_length=100)
    description = discord.ui.TextInput(
        label="Describe your issue",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

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
        for ch in category.text_channels:
            if ticket_owner_id(ch) == user.id:
                await interaction.response.send_message(
                    f"You already have an open ticket: {ch.mention}", ephemeral=True
                )
                return

        cfg["counter"] = cfg.get("counter", 0) + 1
        save_config()

        member_perms = discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            attach_files=True, read_message_history=True,
        )
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: member_perms,
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
            name=f"ticket-{cfg['counter']:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"{TOPIC_PREFIX}{user.id}",
        )

        embed = discord.Embed(
            title=f"🎫 {self.subject.value}",
            description=self.description.value,
            color=COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.set_footer(text="The staff team will reply here as soon as possible.")

        await channel.send(
            content=f"{user.mention} {staff_role.mention}",
            embed=embed,
            view=TicketControls(),
        )
        await interaction.response.send_message(
            f"Ticket created: {channel.mention}", ephemeral=True
        )


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
        await interaction.response.send_modal(TicketModal())


class TicketControls(discord.ui.View):
    """Buttons inside each ticket (persistent)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", emoji="✋",
                       style=discord.ButtonStyle.secondary, custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_cfg(interaction.guild)
        if not is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "Only staff members can claim a ticket.", ephemeral=True
            )
            return
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            f"✋ {interaction.user.mention} has claimed this ticket."
        )

    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, _):
        cfg = guild_cfg(interaction.guild)
        owner_id = ticket_owner_id(interaction.channel)
        if not (is_staff(interaction.user, cfg) or interaction.user.id == owner_id):
            await interaction.response.send_message(
                "You can't close this ticket.", ephemeral=True
            )
            return
        await interaction.response.send_message("🔒 Closing the ticket...")
        await close_ticket(interaction.channel, interaction.user, cfg, owner_id)


async def close_ticket(channel: discord.TextChannel, closed_by: discord.Member,
                       cfg: dict, owner_id: int | None) -> None:
    data = await build_transcript(channel)

    embed = discord.Embed(
        title=f"Ticket closed: #{channel.name}",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Opened by",
                    value=f"<@{owner_id}>" if owner_id else "unknown")
    embed.add_field(name="Closed by", value=closed_by.mention)

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
                    "has been closed.",
                    file=transcript_file(data, channel.name),
                )
            except discord.Forbidden:
                pass  # DMs disabled

    await channel.delete(reason=f"Ticket closed by {closed_by}")


# ------------------------------------------------------------------- bot ---

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # required for transcripts
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self):
        # Buttons keep working after a restart
        self.add_view(TicketPanel())
        self.add_view(TicketControls())
        await self.tree.sync()

    async def on_ready(self):
        print(f"TicketBot online as {self.user}")


bot = TicketBot()


@bot.tree.command(name="setup", description="Set up the ticket system and post the panel")
@app_commands.default_permissions(administrator=True)
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
    old = guild_cfg(interaction.guild) or {}
    config[str(interaction.guild.id)] = {
        "staff_role": staff_role.id,
        "category": category.id,
        "log_channel": log_channel.id,
        "archive_channel": archive_channel.id if archive_channel
                           else old.get("archive_channel"),
        "counter": old.get("counter", 0),
    }
    save_config()

    embed = discord.Embed(
        title="🎫 Support",
        description=(
            "Having an issue, found a bug or need to report something?\n"
            "Click the button below to open a private channel with the staff team."
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


async def require_staff_in_ticket(interaction: discord.Interaction) -> bool:
    cfg = guild_cfg(interaction.guild)
    if cfg is None or ticket_owner_id(interaction.channel) is None:
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
async def add(interaction: discord.Interaction, user: discord.Member):
    if not await require_staff_in_ticket(interaction):
        return
    await interaction.channel.set_permissions(
        user, view_channel=True, send_messages=True,
        attach_files=True, read_message_history=True,
    )
    await interaction.response.send_message(f"➕ {user.mention} has been added to the ticket.")


@bot.tree.command(name="remove", description="Remove a user from the ticket")
async def remove(interaction: discord.Interaction, user: discord.Member):
    if not await require_staff_in_ticket(interaction):
        return
    if user.id == ticket_owner_id(interaction.channel):
        await interaction.response.send_message(
            "You can't remove the user who opened the ticket.", ephemeral=True
        )
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"➖ {user.mention} has been removed from the ticket.")


@bot.tree.command(name="close", description="Close the current ticket")
async def close_cmd(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild)
    owner_id = ticket_owner_id(interaction.channel)
    if cfg is None or owner_id is None:
        await interaction.response.send_message(
            "This command only works inside a ticket.", ephemeral=True
        )
        return
    if not (is_staff(interaction.user, cfg) or interaction.user.id == owner_id):
        await interaction.response.send_message(
            "You can't close this ticket.", ephemeral=True
        )
        return
    await interaction.response.send_message("🔒 Closing the ticket...")
    await close_ticket(interaction.channel, interaction.user, cfg, owner_id)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing: create a .env file (see .env.example).")
    bot.run(TOKEN)
