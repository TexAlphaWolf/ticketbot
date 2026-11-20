"""Slash commands."""

import re
import secrets
import time

import discord
from discord import app_commands

from . import config
from .common import esc, is_staff, priority_label, respond, telegram_notify, translator
from .i18n import DEFAULT_TYPES, LANGUAGES
from .logic import (
    PROFILE_IMAGE_MAX_MB,
    activity_changes,
    compute_stats,
    fill_reply,
    format_duration,
    reply_name,
    slugify,
    stars,
    valid_emoji,
    valid_profile_image,
)
from .telegram_notifier import TelegramError
from .tickets import (
    TicketPanel,
    apply_priority,
    get_context,
    guidelines_embed,
    panel_embed,
    refresh_guidelines,
    refresh_panel,
    reopen_ticket,
    request_close,
    ticket_label,
    transfer_ticket,
)

admin_only = app_commands.default_permissions(administrator=True)


def detect_language(guild: discord.Guild) -> str:
    locale = str(guild.preferred_locale or "")
    for lang in LANGUAGES:
        if locale.startswith(lang):
            return lang
    return config.DEFAULT_LANGUAGE


async def require_setup(interaction: discord.Interaction):
    cfg = interaction.client.db.get_guild(interaction.guild.id)
    _ = translator(cfg)
    if cfg is None or not cfg.get("category"):
        await respond(interaction, _("error.not_setup"), ephemeral=True)
        return None
    return cfg, _


# ------------------------------------------------------------------ setup ---

@app_commands.command(name="setup", description="Set up the ticket system and post the panel")
@app_commands.guild_only()
@admin_only
@app_commands.describe(
    staff_role="Role of the moderators who handle tickets",
    category="Category where ticket channels are created",
    log_channel="Channel where transcripts are logged",
    panel_channel="Channel where the 'Open ticket' button is posted",
    archive_channel="(Optional) Archive channel that keeps every transcript",
)
async def setup(interaction: discord.Interaction, staff_role: discord.Role,
                category: discord.CategoryChannel, log_channel: discord.TextChannel,
                panel_channel: discord.TextChannel,
                archive_channel: discord.TextChannel | None = None):
    db = interaction.client.db
    guild = interaction.guild
    existing = db.get_guild(guild.id)
    lang = existing["language"] if existing else detect_language(guild)
    fields = dict(staff_role=staff_role.id, category=category.id,
                  log_channel=log_channel.id, language=lang)
    if archive_channel is not None:
        fields["archive_channel"] = archive_channel.id
    cfg = db.save_guild(guild.id, **fields)
    db.ensure_default_types(guild.id, DEFAULT_TYPES[lang])
    _ = translator(cfg)

    try:
        message = await panel_channel.send(embed=panel_embed(db.list_types(guild.id), _),
                                           view=TicketPanel(_))
    except discord.HTTPException:
        await interaction.response.send_message(
            _("setup.panel_failed", channel=panel_channel.mention), ephemeral=True
        )
        return
    db.save_guild(guild.id, panel_channel=panel_channel.id, panel_message=message.id)
    await interaction.response.send_message(
        _("setup.done", channel=panel_channel.mention, language=LANGUAGES[lang]), ephemeral=True
    )


@app_commands.command(name="guidelines",
                      description="Post and pin the priority guidelines in the log channel")
@app_commands.guild_only()
@admin_only
async def guidelines(interaction: discord.Interaction):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    guild = interaction.guild
    channel = guild.get_channel(cfg.get("log_channel") or 0)
    if channel is None:
        await interaction.response.send_message(_("error.no_log_channel"), ephemeral=True)
        return

    old_channel = guild.get_channel(cfg.get("guidelines_channel") or 0)
    if old_channel is not None and cfg.get("guidelines_message"):
        try:
            await old_channel.get_partial_message(cfg["guidelines_message"]).delete()
        except discord.HTTPException:
            pass

    message = await channel.send(embed=guidelines_embed(cfg, _))
    interaction.client.db.save_guild(guild.id, guidelines_channel=channel.id,
                                     guidelines_message=message.id)
    try:
        await message.pin(reason="Ticket priority guidelines")
        text = _("guidelines.posted", channel=channel.mention)
    except discord.HTTPException:
        text = _("guidelines.posted_not_pinned", channel=channel.mention)
    await interaction.response.send_message(text, ephemeral=True)


def ticket_history_embed(tickets: list[dict], title: str, _) -> discord.Embed:
    """Open tickets first, then the latest closed ones."""
    open_lines, closed_lines = [], []
    for t in tickets:
        kind = f"{t['type_emoji']} {t['type_label']}"
        if t["status"] != config.STATUS_CLOSED:
            status = _("mytickets.status." + t["status"])
            where = f"<#{t['channel_id']}>" if not t["channel_deleted"] else ticket_label(t)
            open_lines.append(f"{status} · {where} · {kind} · <t:{int(t['opened_at'])}:R>")
        else:
            line = (f"✅ **{ticket_label(t)}** · {kind} · <t:{int(t['opened_at'])}:d>"
                    f" → <t:{int(t['closed_at'] or t['opened_at'])}:d>")
            if t.get("rating"):
                line += f" · {stars(t['rating'])}"
            if t.get("close_reason"):
                line += f"\n-# {t['close_reason'][:90]}"
            closed_lines.append(line)

    embed = discord.Embed(title=title, color=config.COLOR)
    if open_lines:
        embed.add_field(name=_("mytickets.open", count=len(open_lines)),
                        value="\n".join(open_lines)[:1024], inline=False)
    if closed_lines:
        shown = closed_lines[:config.MYTICKETS_CLOSED_SHOWN]
        value = ""
        for line in shown:  # keep whole lines within Discord's 1024 characters
            if len(value) + len(line) + 1 > 1024:
                break
            value += line + "\n"
        embed.add_field(name=_("mytickets.closed", shown=len(shown), total=len(closed_lines)),
                        value=value.strip(), inline=False)
    if not tickets:
        embed.description = _("mytickets.none")
    return embed


@app_commands.command(name="mytickets", description="Show your tickets in this server")
@app_commands.guild_only()
@app_commands.describe(member="(Staff only) Show the tickets of another member")
async def mytickets(interaction: discord.Interaction, member: discord.Member | None = None):
    db = interaction.client.db
    cfg = db.get_guild(interaction.guild.id)
    _ = translator(cfg)
    target = member or interaction.user
    if target.id != interaction.user.id and not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("mytickets.staff_only"), ephemeral=True)
        return
    tickets = db.tickets_of_user(interaction.guild.id, target.id)
    title = (_("mytickets.title_member", user=target.display_name) if member
             else _("mytickets.title"))
    await interaction.response.send_message(embed=ticket_history_embed(tickets, title, _),
                                            ephemeral=True)


@app_commands.command(name="queue", description="Show how many tickets are open right now")
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    _ = ctx[1]
    waiting, in_progress = interaction.client.db.queue_counts(interaction.guild.id)
    await interaction.response.send_message(
        "📊 " + _("queue.line", waiting=waiting, in_progress=in_progress), ephemeral=True
    )


# ------------------------------------------------------ inside a ticket ---

@app_commands.command(name="add", description="Add a member to this ticket")
@app_commands.guild_only()
@app_commands.describe(user="Member to add")
async def add(interaction: discord.Interaction, user: discord.Member):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    _ = ctx[1]
    await interaction.channel.set_permissions(
        user, view_channel=True, send_messages=True, attach_files=True,
        read_message_history=True,
    )
    await interaction.response.send_message(_("member.added", user=user.mention))


@app_commands.command(name="remove", description="Remove a member from this ticket")
@app_commands.guild_only()
@app_commands.describe(user="Member to remove")
async def remove(interaction: discord.Interaction, user: discord.Member):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    _, ticket = ctx[1], ctx[2]
    if user.id == ticket["owner_id"]:
        await interaction.response.send_message(_("member.cant_remove_owner"), ephemeral=True)
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(_("member.removed", user=user.mention))


@app_commands.command(name="close", description="Close this ticket")
@app_commands.guild_only()
@app_commands.describe(reason="(Optional) Reason for closing the ticket")
async def close(interaction: discord.Interaction,
                reason: app_commands.Range[str, 1, 500] | None = None):
    await request_close(interaction, reason)


@app_commands.command(name="reopen", description="Reopen this closed ticket")
@app_commands.guild_only()
async def reopen(interaction: discord.Interaction):
    await reopen_ticket(interaction)


@app_commands.command(name="priority", description="Change the priority of this ticket")
@app_commands.guild_only()
@app_commands.describe(level="New priority")
@app_commands.choices(level=[
    app_commands.Choice(name="Low", value="low"),
    app_commands.Choice(name="Medium", value="medium"),
    app_commands.Choice(name="High", value="high"),
])
async def priority(interaction: discord.Interaction, level: app_commands.Choice[str]):
    await apply_priority(interaction, level.value, claim=False)


@app_commands.command(name="transfer", description="Assign this ticket to another staff member")
@app_commands.guild_only()
@app_commands.describe(member="Staff member who will handle the ticket")
async def transfer(interaction: discord.Interaction, member: discord.Member):
    await transfer_ticket(interaction, member)


class NoteGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="note", description="Private staff notes on this ticket",
                         guild_only=True)

    @app_commands.command(name="add", description="Add a private note visible only to the staff")
    @app_commands.describe(text="Text of the note")
    async def note_add(self, interaction: discord.Interaction,
                       text: app_commands.Range[str, 1, 1000]):
        ctx = await get_context(interaction, staff=True)
        if ctx is None:
            return
        _, ticket = ctx[1], ctx[2]
        interaction.client.db.add_note(ticket["id"], interaction.user.id, text, time.time())
        await interaction.response.send_message(_("note.added"), ephemeral=True)

    @app_commands.command(name="list", description="Show the private notes of this ticket")
    async def note_list(self, interaction: discord.Interaction):
        ctx = await get_context(interaction, staff=True, allow_closed=True)
        if ctx is None:
            return
        _, ticket = ctx[1], ctx[2]
        notes = interaction.client.db.list_notes(ticket["id"])
        if not notes:
            await interaction.response.send_message(_("note.none"), ephemeral=True)
            return
        embed = discord.Embed(title=_("note.title"), color=discord.Color.gold())
        for n in notes[-25:]:
            embed.add_field(name=f"<t:{int(n['created_at'])}:f>",
                            value=f"<@{n['author_id']}>: {n['text']}"[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------------------------------------------ stats ---

PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}


@app_commands.command(name="stats", description="Show ticket statistics")
@app_commands.guild_only()
@app_commands.describe(period="Time period", member="Show the statistics of one staff member")
@app_commands.choices(period=[
    app_commands.Choice(name="Last 7 days", value="7"),
    app_commands.Choice(name="Last 30 days", value="30"),
    app_commands.Choice(name="Last 90 days", value="90"),
    app_commands.Choice(name="All time", value="all"),
])
async def stats(interaction: discord.Interaction,
                period: app_commands.Choice[str] | None = None,
                member: discord.Member | None = None):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("error.staff_only"), ephemeral=True)
        return

    key = period.value if period else "30"
    days = PERIODS[key]
    since = time.time() - days * 86400 if days else 0
    rows = interaction.client.db.tickets_since(interaction.guild.id, since)
    s = compute_stats(rows, member.id if member else None)

    period_label = _("stats.period." + key)
    title = (_("stats.title_member", member=member.display_name, period=period_label)
             if member else _("stats.title", period=period_label))
    embed = discord.Embed(title=title, color=config.COLOR)
    embed.add_field(name=_("stats.tickets"),
                    value=_("stats.tickets_value", opened=s["opened"], closed=s["closed"],
                            open=s["open"]), inline=False)
    embed.add_field(name=_("stats.first_response"), value=format_duration(s["avg_first_response"]))
    embed.add_field(name=_("stats.resolution"), value=format_duration(s["avg_resolution"]))
    embed.add_field(
        name=_("stats.rating"),
        value=f"{s['avg_rating']:.1f} ⭐ ({s['ratings']})" if s["ratings"] else "-",
    )
    if s["by_type"]:
        embed.add_field(name=_("stats.by_type"), value="\n".join(
            f"{label}: **{n}**" for label, n in s["by_type"].most_common(10)))
    if s["opened"]:
        embed.add_field(name=_("stats.by_priority"), value="\n".join(
            f"{priority_label(_, p)}: **{s['by_priority'].get(p, 0)}**"
            for p in (*config.PRIORITIES, None)))
    if not member and s["leaderboard"]:
        lines = []
        for i, row in enumerate(s["leaderboard"][:10], 1):
            rating = f"{row['avg_rating']:.1f}⭐" if row["avg_rating"] else "-"
            lines.append(_("stats.staff_line", rank=i, user=f"<@{row['staff_id']}>",
                           handled=row["handled"], rating=rating,
                           response=format_duration(row["avg_first_response"])))
        embed.add_field(name=_("stats.staff"), value="\n".join(lines)[:1024], inline=False)
    if not s["opened"]:
        embed.description = _("stats.empty")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --------------------------------------------------------------- settings ---

class SettingsGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="settings", description="Ticket system settings",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="show", description="Show the current settings")
    async def show(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx

        def ch(cid):
            return f"<#{cid}>" if cid else "-"

        embed = discord.Embed(title=_("settings.title"), color=config.COLOR)
        embed.add_field(name=_("settings.language"), value=LANGUAGES[cfg["language"]])
        embed.add_field(name=_("settings.staff_role"),
                        value=f"<@&{cfg['staff_role']}>" if cfg.get("staff_role") else "-")
        embed.add_field(name=_("settings.category"), value=ch(cfg.get("category")))
        embed.add_field(name=_("settings.log"), value=ch(cfg.get("log_channel")))
        embed.add_field(name=_("settings.archive"), value=ch(cfg.get("archive_channel")))
        embed.add_field(name=_("settings.panel"), value=ch(cfg.get("panel_channel")))
        embed.add_field(name=_("settings.retention"),
                        value=_("settings.days", days=cfg["retention_days"]))
        embed.add_field(name=_("settings.telegram"),
                        value=f"`{cfg['telegram_chat_id']}`" if cfg.get("telegram_chat_id")
                        else "-")
        embed.add_field(name=_("settings.reminders"),
                        value=_("settings.on") if cfg.get("staff_reminders", 1)
                        else _("settings.off"))
        embed.add_field(name=_("settings.types"),
                        value=str(len(interaction.client.db.list_types(interaction.guild.id))))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="language", description="Change the language of the bot")
    @app_commands.describe(language="Language used by the bot in this server")
    @app_commands.choices(language=[
        app_commands.Choice(name=name, value=code) for code, name in LANGUAGES.items()
    ])
    async def language(self, interaction: discord.Interaction,
                       language: app_commands.Choice[str]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = interaction.client.db.save_guild(interaction.guild.id, language=language.value)
        _ = translator(cfg)
        await interaction.response.send_message(
            _("settings.language_set", language=language.name), ephemeral=True
        )
        await refresh_panel(interaction.client, interaction.guild, cfg)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(
        name="retention",
        description="Days after which Low/Medium transcripts are deleted from the log",
    )
    @app_commands.describe(days="Number of days (1-365)")
    async def retention(self, interaction: discord.Interaction,
                        days: app_commands.Range[int, 1, 365]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = interaction.client.db.save_guild(interaction.guild.id, retention_days=days)
        _ = translator(cfg)
        await interaction.response.send_message(_("settings.retention_set", days=days),
                                                ephemeral=True)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(name="reminders", description="Turn the staff reminders on or off")
    @app_commands.describe(
        enabled="Remind the staff when a ticket waits too long for a reply")
    async def reminders(self, interaction: discord.Interaction, enabled: bool):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = interaction.client.db.save_guild(interaction.guild.id,
                                               staff_reminders=int(enabled))
        _ = translator(cfg)
        await interaction.response.send_message(
            _("settings.reminders_on") if enabled else _("settings.reminders_off"),
            ephemeral=True)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(name="archive", description="Set or remove the archive channel")
    @app_commands.describe(channel="Archive channel (leave empty to disable it)")
    async def archive(self, interaction: discord.Interaction,
                      channel: discord.TextChannel | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        interaction.client.db.save_guild(interaction.guild.id,
                                         archive_channel=channel.id if channel else None)
        await interaction.response.send_message(
            _("settings.archive_set", channel=channel.mention) if channel
            else _("settings.archive_off"), ephemeral=True
        )


# ------------------------------------------------------------ ticket types ---

async def type_autocomplete(interaction: discord.Interaction, current: str):
    types = interaction.client.db.list_types(interaction.guild.id)
    current = current.lower()
    return [
        app_commands.Choice(name=f"{t['emoji']} {t['label']}"[:100], value=t["key"])
        for t in types if current in t["label"].lower() or current in t["key"]
    ][:25]


class QuestionsGroup(app_commands.Group):
    """/types questions ...: the custom form of each ticket type."""

    def __init__(self):
        super().__init__(name="questions", description="Custom questions of the ticket form")

    async def _type(self, interaction: discord.Interaction, key: str):
        db = interaction.client.db
        _ = translator(db.get_guild(interaction.guild.id))
        ticket_type = db.get_type(interaction.guild.id, key)
        if ticket_type is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
        return ticket_type, _

    @app_commands.command(name="list", description="Show the questions of a ticket type")
    @app_commands.describe(type="Ticket type")
    @app_commands.autocomplete(type=type_autocomplete)
    async def list_questions(self, interaction: discord.Interaction, type: str):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        questions = interaction.client.db.list_questions(interaction.guild.id, type)
        name = f"{ticket_type['emoji']} {ticket_type['label']}"
        if not questions:
            text = _("questions.none")
        else:
            lines = []
            for q in questions:
                kind = _("questions.long") if q["long"] else _("questions.short")
                need = _("questions.required") if q["required"] else _("questions.optional")
                example = f"\n   -# {q['placeholder']}" if q["placeholder"] else ""
                lines.append(f"**{q['position']}.** {q['label']} ({kind}, {need}){example}")
            text = "\n".join(lines)
        embed = discord.Embed(title=_("questions.title", type=name,
                                      count=len(questions), max=config.MAX_TYPE_QUESTIONS),
                              description=text, color=config.COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a question to the form of a ticket type")
    @app_commands.describe(
        type="Ticket type",
        question="Question shown to the user (max 45 characters)",
        length="Answer length",
        required="Whether the answer is required",
        example="(Optional) Example shown inside the field",
    )
    @app_commands.autocomplete(type=type_autocomplete)
    @app_commands.choices(length=[
        app_commands.Choice(name="Short", value="short"),
        app_commands.Choice(name="Long", value="long"),
    ])
    async def add_question(self, interaction: discord.Interaction, type: str,
                           question: app_commands.Range[str, 1, 45],
                           length: app_commands.Choice[str] | None = None,
                           required: bool = True,
                           example: app_commands.Range[str, 1, 100] | None = None):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        db = interaction.client.db
        if len(db.list_questions(interaction.guild.id, type)) >= config.MAX_TYPE_QUESTIONS:
            await interaction.response.send_message(
                _("questions.too_many", max=config.MAX_TYPE_QUESTIONS), ephemeral=True)
            return
        position = db.add_question(interaction.guild.id, type, question.strip(),
                                   (example or "").strip(),
                                   long=bool(length and length.value == "long"),
                                   required=required)
        await interaction.response.send_message(
            _("questions.added", number=position, question=question.strip(),
              type=f"{ticket_type['emoji']} {ticket_type['label']}"), ephemeral=True)

    @app_commands.command(name="remove", description="Remove a question from the form")
    @app_commands.describe(type="Ticket type",
                           number="Number of the question (see /types questions list)")
    @app_commands.autocomplete(type=type_autocomplete)
    async def remove_question(self, interaction: discord.Interaction, type: str,
                              number: app_commands.Range[int, 1, 10]):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        if interaction.client.db.remove_question(interaction.guild.id, type, number):
            text = _("questions.removed", number=number,
                     type=f"{ticket_type['emoji']} {ticket_type['label']}")
        else:
            text = _("questions.bad_number", number=number)
        await interaction.response.send_message(text, ephemeral=True)


class TypesGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="types", description="Manage the ticket types of this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))
        self.add_command(QuestionsGroup())

    @app_commands.command(name="list", description="Show the ticket types")
    async def list_types(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        types = interaction.client.db.list_types(interaction.guild.id)
        lines = [f"{t['emoji']} **{t['label']}** (`{t['key']}`)"
                 + (f" – {t['description']}" if t["description"] else "") for t in types]
        embed = discord.Embed(title=_("types.title", count=len(types),
                                      max=config.MAX_TICKET_TYPES),
                              description="\n".join(lines) or "-", color=config.COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a ticket type")
    @app_commands.describe(name="Name of the type", emoji="Emoji shown next to the name",
                           description="(Optional) Short description shown in the menu")
    async def add_type(self, interaction: discord.Interaction,
                       name: app_commands.Range[str, 1, 80], emoji: str,
                       description: app_commands.Range[str, 1, 100] | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        types = db.list_types(interaction.guild.id)
        if len(types) >= config.MAX_TICKET_TYPES:
            await interaction.response.send_message(
                _("types.too_many", max=config.MAX_TICKET_TYPES), ephemeral=True)
            return
        if not valid_emoji(emoji):
            await interaction.response.send_message(_("types.bad_emoji"), ephemeral=True)
            return
        base = slugify(name) or "type"
        key, n = base, 2
        existing = {t["key"] for t in types}
        while key in existing:
            key = f"{base[:17]}-{n}"
            n += 1
        db.add_type(interaction.guild.id, key, name.strip(), emoji.strip(),
                    (description or "").strip())
        await interaction.response.send_message(
            _("types.added", type=f"{emoji} {name}", key=key), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)

    @app_commands.command(name="edit", description="Edit a ticket type")
    @app_commands.describe(type="Type to edit", name="New name", emoji="New emoji",
                           description="New description")
    @app_commands.autocomplete(type=type_autocomplete)
    async def edit_type(self, interaction: discord.Interaction, type: str,
                        name: app_commands.Range[str, 1, 80] | None = None,
                        emoji: str | None = None,
                        description: app_commands.Range[str, 1, 100] | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        current = db.get_type(interaction.guild.id, type)
        if current is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        changes = {}
        if name:
            changes["label"] = name.strip()
        if emoji:
            if not valid_emoji(emoji):
                await interaction.response.send_message(_("types.bad_emoji"), ephemeral=True)
                return
            changes["emoji"] = emoji.strip()
        if description:
            changes["description"] = description.strip()
        if not changes:
            await interaction.response.send_message(_("types.nothing"), ephemeral=True)
            return
        db.update_type(interaction.guild.id, type, **changes)
        updated = db.get_type(interaction.guild.id, type)
        await interaction.response.send_message(
            _("types.edited", type=f"{updated['emoji']} {updated['label']}"), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)

    @app_commands.command(name="remove", description="Remove a ticket type")
    @app_commands.describe(type="Type to remove")
    @app_commands.autocomplete(type=type_autocomplete)
    async def remove_type(self, interaction: discord.Interaction, type: str):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        types = db.list_types(interaction.guild.id)
        target = next((t for t in types if t["key"] == type), None)
        if target is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        if len(types) <= 1:
            await interaction.response.send_message(_("types.last"), ephemeral=True)
            return
        db.remove_type(interaction.guild.id, type)
        await interaction.response.send_message(
            _("types.removed", type=f"{target['emoji']} {target['label']}"), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)


# --------------------------------------------------------------- telegram ---

class TelegramGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="telegram", description="Ticket notifications on Telegram",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    async def ready(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return None
        cfg, _ = ctx
        if interaction.client.telegram is None:
            await interaction.response.send_message(_("tg.disabled"), ephemeral=True)
            return None
        return cfg, _

    @app_commands.command(name="link", description="Link a Telegram chat to this server")
    @app_commands.describe(chat_id="Telegram chat ID (send /start to the Telegram bot to get it)")
    async def link(self, interaction: discord.Interaction, chat_id: str):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        client = interaction.client
        chat_id = chat_id.strip()
        if not re.fullmatch(r"-?\d{1,20}", chat_id):
            await interaction.response.send_message(_("tg.bad_id"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            await client.telegram.send_message(chat_id, _(
                "tg.code", guild=esc(interaction.guild.name), code=code,
                minutes=config.VERIFY_CODE_TTL // 60,
            ))
        except TelegramError:
            await interaction.followup.send(
                _("tg.unreachable", bot=client.telegram.username), ephemeral=True)
            return
        client.pending_links[interaction.guild.id] = {
            "chat_id": chat_id, "code": code,
            "expires": time.time() + config.VERIFY_CODE_TTL, "attempts": 0,
        }
        await interaction.followup.send(_("tg.code_sent"), ephemeral=True)

    @app_commands.command(name="verify", description="Confirm the Telegram link with the code")
    @app_commands.describe(code="The 6-digit code you received on Telegram")
    async def verify(self, interaction: discord.Interaction, code: str):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        client = interaction.client
        pending = client.pending_links.get(interaction.guild.id)
        if pending is None or time.time() > pending["expires"]:
            client.pending_links.pop(interaction.guild.id, None)
            await interaction.response.send_message(_("tg.no_code"), ephemeral=True)
            return
        pending["attempts"] += 1
        if not secrets.compare_digest(code.strip(), pending["code"]):
            left = config.VERIFY_MAX_ATTEMPTS - pending["attempts"]
            if left <= 0:
                client.pending_links.pop(interaction.guild.id, None)
                await interaction.response.send_message(_("tg.too_many"), ephemeral=True)
            else:
                await interaction.response.send_message(_("tg.wrong_code", left=left),
                                                        ephemeral=True)
            return
        cfg = client.db.save_guild(interaction.guild.id, telegram_chat_id=pending["chat_id"])
        client.pending_links.pop(interaction.guild.id, None)
        await interaction.response.send_message(_("tg.linked"), ephemeral=True)
        await telegram_notify(client, cfg, _("tg.linked_chat",
                                             guild=esc(interaction.guild.name)))

    @app_commands.command(name="status", description="Show the Telegram link of this server")
    async def status(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        if cfg.get("telegram_chat_id"):
            text = _("tg.status_linked", chat=cfg["telegram_chat_id"])
        else:
            text = _("tg.status_none", bot=interaction.client.telegram.username)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="test", description="Send a test notification to Telegram")
    async def test(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        if not cfg.get("telegram_chat_id"):
            await interaction.response.send_message(_("tg.not_linked"), ephemeral=True)
            return
        await telegram_notify(interaction.client, cfg,
                              _("tg.test", guild=esc(interaction.guild.name)))
        await interaction.response.send_message(_("tg.test_sent"), ephemeral=True)

    @app_commands.command(name="unlink", description="Stop sending notifications to Telegram")
    async def unlink(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        interaction.client.db.save_guild(interaction.guild.id, telegram_chat_id=None)
        interaction.client.pending_links.pop(interaction.guild.id, None)
        await interaction.response.send_message(_("tg.unlinked"), ephemeral=True)


# ---------------------------------------------------------- quick replies ---

async def reply_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    return [
        app_commands.Choice(name=f"{r['name']} – {r['content']}".replace("\n", " ")[:100],
                            value=r["name"])
        for r in interaction.client.db.list_replies(interaction.guild.id)
        if current in r["name"]
    ][:25]


@app_commands.command(name="reply", description="Send a quick reply in this ticket")
@app_commands.guild_only()
@app_commands.describe(name="Quick reply to send")
@app_commands.autocomplete(name=reply_autocomplete)
async def reply(interaction: discord.Interaction, name: str):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    db = interaction.client.db
    saved = db.get_reply(interaction.guild.id, name)
    if saved is None:
        await interaction.response.send_message(_("replies.unknown", name=name), ephemeral=True)
        return
    text = fill_reply(saved["content"], user=f"<@{ticket['owner_id']}>",
                      staff=interaction.user.mention, server=interaction.guild.name)
    await interaction.response.send_message(
        text + "\n-# " + _("replies.signature", staff=interaction.user.display_name),
        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
    )
    # A quick reply is a staff answer: it counts for stats and the auto-close timer
    db.update_ticket(ticket["id"], **activity_changes(ticket, time.time(), from_staff=True))


class ReplyModal(discord.ui.Modal):
    def __init__(self, name: str, _, content: str | None = None):
        super().__init__(title=_("replies.modal_title", name=name)[:45])
        self.name = name
        self._ = _
        self.content = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, max_length=config.MAX_REPLY_LENGTH,
            default=content,
        )
        self.add_item(discord.ui.Label(text=_("replies.modal_label"),
                                       description=_("replies.modal_hint"),
                                       component=self.content))

    async def on_submit(self, interaction: discord.Interaction):
        _ = self._
        db = interaction.client.db
        is_new = db.get_reply(interaction.guild.id, self.name) is None
        if is_new and len(db.list_replies(interaction.guild.id)) >= config.MAX_REPLIES:
            await interaction.response.send_message(
                _("replies.too_many", max=config.MAX_REPLIES), ephemeral=True)
            return
        db.save_reply(interaction.guild.id, self.name, self.content.value)
        preview = fill_reply(self.content.value, user="@User", staff="@Staff",
                             server=interaction.guild.name)
        await interaction.response.send_message(
            _("replies.saved", name=self.name, preview=preview)[:2000], ephemeral=True)


class RepliesGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="replies", description="Manage the quick replies of this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="list", description="Show the quick replies")
    async def list_replies(self, interaction: discord.Interaction):
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        replies = interaction.client.db.list_replies(interaction.guild.id)
        if not replies:
            await interaction.response.send_message(_("replies.none"), ephemeral=True)
            return
        lines = []
        for r in replies:
            preview = r["content"].replace("\n", " ")
            preview = preview[:80] + ("…" if len(preview) > 80 else "")
            lines.append(f"**`{r['name']}`** – {preview}")
        embed = discord.Embed(
            title=_("replies.title", count=len(replies), max=config.MAX_REPLIES),
            description="\n".join(lines)[:4096], color=config.COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a quick reply")
    @app_commands.describe(name="Name of the quick reply (e.g. logs)")
    async def add_reply(self, interaction: discord.Interaction,
                        name: app_commands.Range[str, 1, 32]):
        db = interaction.client.db
        _ = translator(db.get_guild(interaction.guild.id))
        key = reply_name(name)
        if not key:
            await interaction.response.send_message(_("replies.bad_name"), ephemeral=True)
            return
        if db.get_reply(interaction.guild.id, key):
            await interaction.response.send_message(_("replies.exists", name=key),
                                                    ephemeral=True)
            return
        if len(db.list_replies(interaction.guild.id)) >= config.MAX_REPLIES:
            await interaction.response.send_message(
                _("replies.too_many", max=config.MAX_REPLIES), ephemeral=True)
            return
        db.save_guild(interaction.guild.id)  # make sure the server row exists
        await interaction.response.send_modal(ReplyModal(key, _))

    @app_commands.command(name="edit", description="Edit a quick reply")
    @app_commands.describe(name="Quick reply to edit")
    @app_commands.autocomplete(name=reply_autocomplete)
    async def edit_reply(self, interaction: discord.Interaction, name: str):
        db = interaction.client.db
        _ = translator(db.get_guild(interaction.guild.id))
        saved = db.get_reply(interaction.guild.id, name)
        if saved is None:
            await interaction.response.send_message(_("replies.unknown", name=name),
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(ReplyModal(saved["name"], _, saved["content"]))

    @app_commands.command(name="remove", description="Remove a quick reply")
    @app_commands.describe(name="Quick reply to remove")
    @app_commands.autocomplete(name=reply_autocomplete)
    async def remove_reply(self, interaction: discord.Interaction, name: str):
        db = interaction.client.db
        _ = translator(db.get_guild(interaction.guild.id))
        if db.remove_reply(interaction.guild.id, name):
            await interaction.response.send_message(_("replies.removed", name=name.lower()),
                                                    ephemeral=True)
        else:
            await interaction.response.send_message(_("replies.unknown", name=name),
                                                    ephemeral=True)


# ---------------------------------------------------------------- profile ---

class ProfileGroup(app_commands.Group):
    """The bot's name, avatar, banner and bio in this server only."""

    def __init__(self):
        super().__init__(name="profile", description="Customize the bot's profile in this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    async def _apply(self, interaction: discord.Interaction, done: str, **changes) -> None:
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.guild.me.edit(**changes,
                                            reason=f"Profile changed by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(_("profile.forbidden"), ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(_("profile.failed", error=(e.text or str(e))[:300]),
                                            ephemeral=True)
        else:
            await interaction.followup.send(done, ephemeral=True)

    async def _image(self, interaction: discord.Interaction, image: discord.Attachment):
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        if not valid_profile_image(image.content_type, image.size):
            await interaction.response.send_message(
                _("profile.bad_image", mb=PROFILE_IMAGE_MAX_MB), ephemeral=True)
            return None
        await interaction.response.defer(ephemeral=True, thinking=True)
        return await image.read()

    @app_commands.command(name="name", description="Change the bot's name in this server")
    @app_commands.describe(name="New name (up to 32 characters)")
    async def set_name(self, interaction: discord.Interaction,
                   name: app_commands.Range[str, 1, 32]):
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.name_set", name=name.strip()),
                          nick=name.strip())

    @app_commands.command(name="avatar", description="Change the bot's avatar in this server")
    @app_commands.describe(image="Image (PNG, JPG, GIF or WEBP, max 8 MB)")
    async def set_avatar(self, interaction: discord.Interaction, image: discord.Attachment):
        data = await self._image(interaction, image)
        if data is not None:
            _ = translator(interaction.client.db.get_guild(interaction.guild.id))
            await self._apply(interaction, _("profile.avatar_set"), avatar=data)

    @app_commands.command(name="banner", description="Change the bot's banner in this server")
    @app_commands.describe(image="Image (PNG, JPG, GIF or WEBP, max 8 MB)")
    async def set_banner(self, interaction: discord.Interaction, image: discord.Attachment):
        data = await self._image(interaction, image)
        if data is not None:
            _ = translator(interaction.client.db.get_guild(interaction.guild.id))
            await self._apply(interaction, _("profile.banner_set"), banner=data)

    @app_commands.command(name="bio", description="Change the bot's bio in this server")
    @app_commands.describe(text="New bio (up to 190 characters)")
    async def set_bio(self, interaction: discord.Interaction,
                  text: app_commands.Range[str, 1, 190]):
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.bio_set"), bio=text.strip())

    @app_commands.command(name="reset",
                          description="Restore the bot's original profile in this server")
    async def reset_profile(self, interaction: discord.Interaction):
        _ = translator(interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.reset"),
                          nick=None, avatar=None, banner=None, bio=None)


def all_commands() -> list:
    return [setup, guidelines, queue, mytickets, add, remove, close, reopen, priority,
            transfer, stats, reply, NoteGroup(), SettingsGroup(), TypesGroup(), TelegramGroup(),
            ProfileGroup(), RepliesGroup()]
