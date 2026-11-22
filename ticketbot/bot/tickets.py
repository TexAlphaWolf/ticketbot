"""Ticket panel, opening, claiming, priorities, transfers, closing, reopening and ratings."""

import io
import time
from datetime import UTC, datetime

import discord

from ..core import config
from ..core.logic import (
    answers_text,
    assignment_order,
    attachment_problem,
    cooldown_left,
    format_duration,
    is_kept,
    stars,
    ticket_channel_name,
)
from ..core.transcripts import dump_transcript, render_html, render_txt
from .collect import collect_messages
from .common import (
    COLOR,
    Translate,
    audit,
    channel_url,
    esc,
    grant_thread_access,
    is_staff,
    is_ticket_staff,
    priority_label,
    respond,
    telegram_notify,
    translator,
    type_label,
    user_name,
)

# ----------------------------------------------------------------- panel ---

def panel_embed(types: list[dict], _: Translate) -> discord.Embed:
    lines = "\n".join(
        f"{t['emoji']} **{t['label']}**" + (f": {t['description']}" if t["description"] else "")
        for t in types
    )
    description = _("panel.description") + (f"\n\n{lines}" if lines else "")
    return discord.Embed(title=_("panel.title"), description=description, color=COLOR)


async def open_problem(db, cfg: dict, member: discord.abc.User, _: Translate) -> str | None:
    """Why a member can't open a ticket right now (None = they can)."""
    guild_id = cfg["guild_id"]
    existing = await db.open_ticket_of_owner(guild_id, member.id)
    if existing:
        return _("open.already", channel=f"<#{existing['channel_id']}>")
    if is_staff(member, cfg):
        return None
    now = time.time()
    block = await db.get_block(guild_id, member.id, now)
    if block:
        text = _("open.blocked")
        if block.get("reason"):
            text += "\n" + _("open.blocked_reason", reason=block["reason"])
        if block.get("until"):
            text += "\n" + _("open.blocked_until", time=f"<t:{int(block['until'])}:R>")
        return text
    wait = cooldown_left(await db.last_ticket_of_owner(guild_id, member.id),
                         cfg.get("ticket_cooldown") or 0, now)
    if wait:
        return _("open.cooldown", time=f"<t:{int(now + wait) + 1}:R>")
    return None


async def pick_assignee(db, guild: discord.Guild, cfg: dict, owner_id: int,
                        type_roles: list[int] | None = None) -> discord.Member | None:
    """Next available staff member for a new ticket (None = ping the staff role).
    With roles for the ticket's type, only members with one of them are picked."""
    if not cfg.get("auto_assign"):
        return None
    available = await db.available_staff(guild.id)
    for user_id in assignment_order(available, await db.open_tickets_per_staff(guild.id)):
        if user_id == owner_id:
            continue
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                member = None
            except discord.HTTPException:
                continue
        if member is None or member.bot or not is_staff(member, cfg) and not (
                type_roles and is_ticket_staff(member, cfg, type_roles)):
            await db.set_available(guild.id, user_id, False)  # left the server or the staff
            continue
        if type_roles and not is_ticket_staff(member, cfg, type_roles):
            continue  # staff, but not for this type
        return member
    return None


class TicketPanel(discord.ui.View):
    """Panel with the button to open tickets (persistent)."""

    def __init__(self, _: Translate | None = None):
        super().__init__(timeout=None)
        if _:
            self.open_btn.label = _("btn.open")

    @discord.ui.button(label="Open ticket", emoji="📩",
                       style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        db = interaction.client.db
        cfg = await db.get_guild(interaction.guild.id)
        _ = translator(cfg)
        if cfg is None or not cfg.get("category"):
            await interaction.response.send_message(_("error.not_setup"), ephemeral=True)
            return
        if not cfg.get("panel_message") and interaction.message is not None:
            # A server set up with TicketBot 1 never saved its panel: learn it now, so
            # changes of types and language update it (and thread mode knows the channel)
            cfg = await db.save_guild(interaction.guild.id,
                                      panel_channel=interaction.channel.id,
                                      panel_message=interaction.message.id)
            await refresh_panel(interaction.client, interaction.guild, cfg)
        problem = await open_problem(db, cfg, interaction.user, _)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        types = await db.list_types(interaction.guild.id)
        if not types:
            await interaction.response.send_message(_("error.no_types"), ephemeral=True)
            return
        await interaction.response.send_message(
            _("panel.choose_prompt"), view=TypeView(types, _), ephemeral=True
        )


async def refresh_panel(client, guild: discord.Guild, cfg: dict) -> str | None:
    """Update the panel message after a change of language or ticket types. Returns
    what went wrong, or None."""
    if not cfg.get("panel_message"):
        return "unknown panel"
    channel = guild.get_channel(cfg.get("panel_channel") or 0)
    if channel is None:
        return "panel channel deleted"
    _ = translator(cfg)
    try:
        await channel.get_partial_message(cfg["panel_message"]).edit(
            embed=panel_embed(await client.db.list_types(guild.id), _), view=TicketPanel(_)
        )
    except discord.HTTPException as e:
        return f"HTTP {e.status}: {e.text or e}"
    return None


class TypeSelect(discord.ui.Select):
    def __init__(self, types: list[dict], _: Translate):
        options = [
            discord.SelectOption(
                label=t["label"][:100], value=t["key"], emoji=t["emoji"] or None,
                description=(t["description"][:100] or None),
            )
            for t in types[:config.MAX_TICKET_TYPES]
        ]
        super().__init__(placeholder=_("panel.choose_type"), options=options)

    async def callback(self, interaction: discord.Interaction):
        db = interaction.client.db
        cfg = await db.get_guild(interaction.guild.id)
        _ = translator(cfg)
        ticket_type = await db.get_type(interaction.guild.id, self.values[0])
        if ticket_type is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        faq = await db.faq_for_type(interaction.guild.id, ticket_type["key"], config.FAQ_SHOWN)
        if faq:
            await interaction.response.edit_message(
                content=None, embed=faq_embed(ticket_type, faq, _),
                view=FaqView(ticket_type["key"], _))
            return
        questions = await db.list_questions(interaction.guild.id, ticket_type["key"])
        await interaction.response.send_modal(TicketModal(ticket_type, _, questions))


def faq_embed(ticket_type: dict, entries: list[dict], _: Translate) -> discord.Embed:
    embed = discord.Embed(title=_("faq.title", type=f"{ticket_type['emoji']} "
                                                   f"{ticket_type['label']}")[:256],
                          description=_("faq.intro"), color=COLOR)
    for entry in entries:
        embed.add_field(name=entry["question"][:256], value=entry["answer"][:1024],
                        inline=False)
    return embed


class FaqView(discord.ui.View):
    """Shown before the form when the type has FAQ: solved alone, or open the ticket."""

    def __init__(self, type_key: str, _: Translate):
        super().__init__(timeout=600)
        self.type_key = type_key
        self.solved_btn.label = _("btn.faq_solved")
        self.open_btn.label = _("btn.faq_open")

    @discord.ui.button(label="It's solved", emoji="✅", style=discord.ButtonStyle.success)
    async def solved_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        db = interaction.client.db
        _ = translator(await db.get_guild(interaction.guild.id))
        await db.record_faq_result(interaction.guild.id, self.type_key, solved=True)
        self.stop()
        await interaction.response.edit_message(content=_("faq.glad"), embed=None, view=None)

    @discord.ui.button(label="Open a ticket anyway", emoji="📩",
                       style=discord.ButtonStyle.secondary)
    async def open_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        db = interaction.client.db
        cfg = await db.get_guild(interaction.guild.id)
        _ = translator(cfg)
        ticket_type = await db.get_type(interaction.guild.id, self.type_key)
        if cfg is None or ticket_type is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        problem = await open_problem(db, cfg, interaction.user, _)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        await db.record_faq_result(interaction.guild.id, self.type_key, solved=False)
        questions = await db.list_questions(interaction.guild.id, self.type_key)
        await interaction.response.send_modal(TicketModal(ticket_type, _, questions))


class TypeView(discord.ui.View):
    def __init__(self, types: list[dict], _: Translate):
        super().__init__(timeout=300)
        self.add_item(TypeSelect(types, _))


# ------------------------------------------------------------- opening ---

class TicketModal(discord.ui.Modal):
    """Subject + description, or subject + the custom questions of the ticket type."""

    def __init__(self, ticket_type: dict, _: Translate, questions: list[dict] | None = None):
        super().__init__(title=_("modal.title", type=ticket_type["label"])[:45])
        self.ticket_type = ticket_type
        self.subject = discord.ui.TextInput(max_length=100)
        self.add_item(discord.ui.Label(text=_("modal.subject"), component=self.subject))
        self.answers: list[tuple[str, discord.ui.TextInput]] = []
        for q in (questions or [])[:config.MAX_TYPE_QUESTIONS]:
            field = discord.ui.TextInput(
                style=discord.TextStyle.paragraph if q["long"] else discord.TextStyle.short,
                max_length=(config.LONG_ANSWER_LENGTH if q["long"]
                            else config.SHORT_ANSWER_LENGTH),
                required=bool(q["required"]),
                placeholder=q["placeholder"][:100] or None,
            )
            self.add_item(discord.ui.Label(text=q["label"][:45], component=field))
            self.answers.append((q["label"], field))
        self.description = None
        if not self.answers:
            self.description = discord.ui.TextInput(style=discord.TextStyle.paragraph,
                                                    max_length=1000)
            self.add_item(discord.ui.Label(text=_("modal.description"),
                                           component=self.description))
        self.upload = discord.ui.FileUpload(required=False,
                                            max_values=config.MAX_FORM_ATTACHMENTS)
        self.add_item(discord.ui.Label(text=_("modal.attachments"),
                                       description=_("modal.attachments_hint",
                                                     max=config.MAX_FORM_ATTACHMENTS),
                                       component=self.upload))

    def description_text(self) -> str:
        if self.description is not None:
            return self.description.value
        return answers_text([(label, field.value) for label, field in self.answers])

    async def on_submit(self, interaction: discord.Interaction):
        await open_ticket(interaction, self.ticket_type, self.subject.value,
                          self.description_text(), list(self.upload.values))


async def forward_attachments(channel: discord.TextChannel, user: discord.abc.User,
                              attachments: list[discord.Attachment], _: Translate) -> None:
    """
    Files uploaded in a form are only kept by Discord for a while: send them again into the
    ticket so that they stay in the channel and in the transcripts. Files that can run code,
    or that are too big for the server, are skipped and listed.
    """
    max_bytes = channel.guild.filesize_limit
    files, skipped = [], []
    for attachment in attachments:
        problem = attachment_problem(attachment.filename, attachment.size, max_bytes)
        if problem:
            reason = (_("attachments.blocked") if problem == "blocked"
                      else _("attachments.too_big", mb=max_bytes // (1024 * 1024)))
            skipped.append(f"`{attachment.filename}` ({reason})")
            continue
        try:
            data = await attachment.read()
        except discord.HTTPException:
            skipped.append(f"`{attachment.filename}` ({_('attachments.failed')})")
            continue
        files.append(discord.File(io.BytesIO(data), filename=attachment.filename))
    if files:
        try:
            await channel.send(_("attachments.from", user=user.mention), files=files,
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            skipped += [f"`{f.filename}` ({_('attachments.failed')})" for f in files]
    if skipped:
        await channel.send(_("attachments.skipped", files=", ".join(skipped)))


class OpenError(Exception):
    """The ticket can't be opened; the message is for the member (translated)."""


async def open_ticket(interaction: discord.Interaction, ticket_type: dict,
                      subject: str, description: str,
                      attachments: list[discord.Attachment] | None = None) -> None:
    """The ticket form on Discord was sent."""
    cfg = await interaction.client.db.get_guild(interaction.guild.id)
    _ = translator(cfg)
    try:      # checked again: the form may stay open a while
        await check_can_open(interaction.client, interaction.guild, cfg, interaction.user)
    except OpenError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        channel, queue = await create_ticket(
            interaction.client, interaction.guild, interaction.user, ticket_type, subject,
            description, attachments=attachments)
    except OpenError as e:
        await interaction.followup.send(str(e), ephemeral=True)
        return
    await interaction.followup.send(
        _("open.created", channel=channel.mention) + "\n📊 " + queue, ephemeral=True)


async def check_can_open(client, guild: discord.Guild, cfg: dict | None,
                         user: discord.Member) -> None:
    """Raises OpenError if the server isn't set up or the member can't open a ticket."""
    _ = translator(cfg)
    if cfg is None or guild.get_channel(cfg.get("category") or 0) is None or \
            guild.get_role(cfg.get("staff_role") or 0) is None:
        raise OpenError(_("error.bad_setup"))
    problem = await open_problem(client.db, cfg, user, _)
    if problem:
        raise OpenError(problem)


async def create_ticket(client, guild: discord.Guild, user: discord.Member,
                        ticket_type: dict, subject: str, description: str, *,
                        attachments: list[discord.Attachment] | None = None,
                        source: str = "discord") -> tuple[discord.abc.GuildChannel, str]:
    """Open a ticket for `user` (from the Discord form or the web form). Returns the
    channel or thread and the queue line; raises OpenError."""
    db = client.db
    cfg = await db.get_guild(guild.id)
    _ = translator(cfg)
    await check_can_open(client, guild, cfg, user)
    category = guild.get_channel(cfg.get("category") or 0)
    staff_role = guild.get_role(cfg.get("staff_role") or 0)
    # Roles of this type (e.g. Bug -> @Dev) see and handle the ticket instead of the staff
    type_role_ids = await db.type_roles(guild.id, ticket_type["key"])
    handlers = [r for r in (guild.get_role(i) for i in type_role_ids) if r is not None]
    if not handlers:
        handlers, type_role_ids = [staff_role], []

    thread_mode = cfg.get("ticket_mode") == "thread"
    parent = guild.get_channel(cfg.get("panel_channel") or 0) if thread_mode else None
    if thread_mode and parent is None:
        raise OpenError(_("error.bad_setup"))

    waiting, in_progress = await db.queue_counts(guild.id)
    number = await db.next_ticket_number(guild.id)
    user_number = await db.next_user_number(guild.id, user.id)
    channel_name = ticket_channel_name(ticket_type["key"], user.name, user.id, user_number)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True, read_message_history=True
        ),
        **{role: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            read_message_history=True, manage_messages=True,
        ) for role in handlers},
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True,
            read_message_history=True, attach_files=True,
        ),
    }
    if thread_mode:
        # A private thread in the panel channel: only the people added to it (and those
        # who can manage threads there, i.e. the staff) see it
        channel = await parent.create_thread(
            name=channel_name, type=discord.ChannelType.private_thread, invitable=False,
            auto_archive_duration=10080, reason=f"Ticket of {user}")
        await channel.add_user(user)
    else:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"{config.TOPIC_PREFIX}{user.id}",
        )

    now = time.time()
    assignee = await pick_assignee(db, guild, cfg, user.id, type_role_ids)
    if assignee:
        await db.mark_assigned(guild.id, assignee.id, now)
    ticket_id = await db.create_ticket(
        guild_id=guild.id, channel_id=channel.id, number=number, user_number=user_number,
        name=channel.name, owner_id=user.id,
        type_key=ticket_type["key"], type_label=ticket_type["label"],
        type_emoji=ticket_type["emoji"], subject=subject, description=description,
        status=config.STATUS_WAITING, opened_at=now, last_activity=now,
        awaiting_staff_since=now, assigned_to=assignee.id if assignee else None,
        is_thread=thread_mode,
    )
    await db.audit(guild.id, user.id, "ticket.open", source=source,
                   target=f"ticket:{ticket_id}", details={
                       "type": ticket_type["key"],
                       **({"assigned_to": assignee.id} if assignee else {})})

    queue = (_("queue.line", waiting=waiting, in_progress=in_progress)
             if waiting or in_progress else _("queue.first"))
    embed = discord.Embed(title=f"🎫 {subject}", description=description,
                          color=COLOR, timestamp=datetime.now(UTC))
    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
    embed.add_field(name=_("field.type"), value=f"{ticket_type['emoji']} {ticket_type['label']}")
    embed.add_field(name=_("field.queue"), value=queue)
    if assignee:
        embed.add_field(name=_("field.assigned"), value=assignee.mention)
    if source == "web":
        embed.add_field(name=_("field.source"), value=_("open.from_web"))
    embed.set_footer(text=_("open.footer", hours=config.AUTO_CLOSE_HOURS))

    ping = assignee.mention if assignee else " ".join(r.mention for r in handlers)
    control = await channel.send(content=f"{user.mention} {ping}",
                                 embed=embed, view=TicketControls(_))
    await db.update_ticket(ticket_id, control_message=control.id)
    if attachments:
        await forward_attachments(channel, user, attachments, _)

    if thread_mode:
        # Role mentions don't reach people outside a private thread: tell the staff in
        # the log channel (an assigned member was mentioned in the thread, so is in it)
        log = guild.get_channel(cfg.get("log_channel") or 0)
        if log is not None:
            try:
                await log.send(
                    _("open.thread_log", thread=channel.mention, user=user.mention,
                      type=f"{ticket_type['emoji']} {ticket_type['label']}", staff=ping),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True))
            except discord.HTTPException as e:
                print(f"Could not announce the ticket in the log channel: {e}")

    await telegram_notify(client, cfg, _(
        "tg.new",
        guild=esc(guild.name), type=esc(f"{ticket_type['emoji']} {ticket_type['label']}"),
        user=esc(user), subject=esc(subject), description=esc(description[:500]),
        waiting=waiting, in_progress=in_progress, url=channel_url(guild.id, channel.id),
    ), ticket_id=ticket_id)
    return channel, queue


# ------------------------------------------------------- ticket controls ---

async def escalate(client, guild: discord.Guild, channel, ticket: dict, cfg: dict,
                   level: int, actor: discord.abc.User | None, reason: str | None,
                   source: str = "discord") -> bool:
    """Bring a ticket to an escalation level: its role gets access and is pinged.
    `actor` None = automatic (the ticket waited too long). Returns False if the level's
    role doesn't exist anymore."""
    db = client.db
    _ = translator(cfg)
    found = [lv for lv in await db.escalation_levels(guild.id) if lv["level"] == level]
    role = guild.get_role(found[0]["role_id"]) if found else None
    if role is None:
        return False

    if isinstance(channel, discord.Thread):
        panel = guild.get_channel(cfg.get("panel_channel") or 0)
        if panel is not None:
            await grant_thread_access(panel, [role])
    else:
        await channel.set_permissions(
            role, view_channel=True, send_messages=True, attach_files=True,
            read_message_history=True, manage_messages=True,
            reason=f"Ticket escalated to level {level}")
    await db.update_ticket(ticket["id"], escalation_level=level, escalated_at=time.time())
    ticket.update(escalation_level=level)

    text = _("escalation.done", level=level, role=role.mention)
    if reason:
        text += "\n" + _("escalation.reason", reason=reason)
    text += "\n" + (_("escalation.by", user=actor.mention) if actor
                    else _("escalation.automatic"))
    mentions = discord.AllowedMentions(roles=[role], users=False)
    await channel.send(text, allowed_mentions=mentions)
    if isinstance(channel, discord.Thread):     # role mentions don't reach a private thread
        log = guild.get_channel(cfg.get("log_channel") or 0)
        if log is not None:
            await log.send(_("escalation.log", level=level, role=role.mention,
                             thread=channel.mention), allowed_mentions=mentions)
    await db.audit(guild.id, actor.id if actor else None, "ticket.escalate",
                   source=source if actor else "system", target=f"ticket:{ticket['id']}",
                   details={"level": level, "reason": reason})
    await telegram_notify(client, cfg, _(
        "tg.escalated", guild=esc(guild.name), channel=esc(ticket_label(ticket)),
        level=level, role=esc(role.name), url=channel_url(guild.id, channel.id)),
        ticket_id=ticket["id"])
    return True


class TicketControls(discord.ui.View):
    """Buttons inside each open ticket (persistent)."""

    def __init__(self, _: Translate | None = None, claimed_by: str | None = None):
        super().__init__(timeout=None)
        if _:
            self.claim_btn.label = _("btn.claim")
            self.close_btn.label = _("btn.close")
            if claimed_by:
                self.claim_btn.disabled = True
                self.claim_btn.label = _("btn.claimed_by", name=claimed_by)[:80]

    @discord.ui.button(label="Claim", emoji="✋",
                       style=discord.ButtonStyle.secondary, custom_id="ticket:claim")
    async def claim_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await start_claim(interaction)

    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await request_close(interaction, None)


async def ticket_roles(db, ticket: dict) -> tuple[list[int], list[int]]:
    """(roles of the ticket's type, roles of the escalation levels it has reached)."""
    type_roles = await db.type_roles(ticket["guild_id"], ticket["type_key"])
    reached = ticket.get("escalation_level") or 0
    levels = await db.escalation_levels(ticket["guild_id"]) if reached else []
    return type_roles, [lv["role_id"] for lv in levels if lv["level"] <= reached]


async def get_context(interaction: discord.Interaction, *, staff: bool = False,
                      allow_closed: bool = False):
    """Return (cfg, _, ticket) for a ticket channel, or None after answering with an error."""
    db = interaction.client.db
    cfg = await db.get_guild(interaction.guild.id) if interaction.guild else None
    _ = translator(cfg)
    ticket = await db.ticket_by_channel(interaction.channel.id) if cfg else None
    if ticket is None:
        await respond(interaction, _("error.not_ticket"), ephemeral=True)
        return None
    if ticket["status"] == config.STATUS_CLOSED and not allow_closed:
        await respond(interaction, _("error.ticket_closed"), ephemeral=True)
        return None
    if staff and not is_ticket_staff(interaction.user, cfg, *await ticket_roles(db, ticket)):
        await respond(interaction, _("error.staff_only"), ephemeral=True)
        return None
    return cfg, _, ticket


async def refresh_controls(channel: discord.TextChannel, ticket: dict, _: Translate,
                           name: str | None = None) -> None:
    """Update the button that says who claimed the ticket. `name`: the claimer's name
    when the caller has it (members aren't always in the bot's cache)."""
    if not ticket.get("control_message"):
        return
    if name is None and ticket.get("claimed_by"):
        claimer = channel.guild.get_member(ticket["claimed_by"])
        name = claimer.display_name if claimer else str(ticket["claimed_by"])
    try:
        await channel.get_partial_message(ticket["control_message"]).edit(
            view=TicketControls(_, claimed_by=name)
        )
    except discord.HTTPException:
        pass


async def start_claim(interaction: discord.Interaction) -> None:
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    if ticket.get("claimed_by"):
        await interaction.response.send_message(
            _("claim.already", user=f"<@{ticket['claimed_by']}>"), ephemeral=True
        )
        return
    if not ticket.get("control_message") and interaction.message is not None:
        await interaction.client.db.update_ticket(ticket["id"],
                                                  control_message=interaction.message.id)
    await interaction.response.send_message(
        _("claim.choose_priority"), view=PriorityView(_, claim=True), ephemeral=True
    )


class PrioritySelect(discord.ui.Select):
    def __init__(self, _: Translate, claim: bool):
        options = [
            discord.SelectOption(label=_("priority." + p), value=p,
                                 emoji=config.PRIORITY_EMOJI[p],
                                 description=_("claim.option",
                                               target=_("priority.target." + p))[:100])
            for p in config.PRIORITIES
        ]
        super().__init__(placeholder=_("claim.placeholder"), options=options)
        self.claim = claim

    async def callback(self, interaction: discord.Interaction):
        await apply_priority(interaction, self.values[0], claim=self.claim)


class PriorityView(discord.ui.View):
    def __init__(self, _: Translate, claim: bool):
        super().__init__(timeout=300)
        self.add_item(PrioritySelect(_, claim))


async def apply_priority(interaction: discord.Interaction, level: str, claim: bool) -> None:
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    if claim and ticket.get("claimed_by"):
        await interaction.response.edit_message(
            content=_("claim.already", user=f"<@{ticket['claimed_by']}>"), view=None
        )
        return
    if claim:
        async def answer():
            await interaction.response.edit_message(
                content=_("claim.done", priority=priority_label(_, level)), view=None)
        await claim_ticket(interaction.client, interaction.channel, ticket, cfg,
                           interaction.user, level, respond=answer)
    else:
        await change_priority(interaction.client, interaction.channel, ticket, cfg,
                              interaction.user, level,
                              respond=lambda text: interaction.response.send_message(text))


async def claim_ticket(client, channel, ticket: dict, cfg: dict, member: discord.Member,
                       level: str, *, source: str = "discord", respond=None) -> None:
    """`member` takes the ticket with a priority. `respond` (Discord) answers the
    interaction right after the database is updated, before the slower calls."""
    _ = translator(cfg)
    changes = {"priority": level, "claimed_by": member.id,
               "status": config.STATUS_IN_PROGRESS}
    if not ticket.get("first_response_at"):
        changes["first_response_at"] = time.time()
    previous = ticket.get("priority")
    await client.db.update_ticket(ticket["id"], **changes)
    ticket.update(changes)
    await client.db.audit(channel.guild.id, member.id, "ticket.claim", source=source,
                          target=f"ticket:{ticket['id']}", details={"priority": level})
    if respond is not None:
        await respond()
    await refresh_controls(channel, ticket, _, member.display_name)
    await channel.send(_("claim.public", user=member.mention,
                         priority=priority_label(_, level)))
    await notify_high_priority(client, cfg, channel, ticket, member, level, previous)


async def change_priority(client, channel, ticket: dict, cfg: dict, member: discord.Member,
                          level: str, *, source: str = "discord", respond=None) -> None:
    """`respond(text)` sends the announcement as the interaction's answer; without it,
    the bot posts it in the ticket."""
    _ = translator(cfg)
    previous = ticket.get("priority")
    await client.db.update_ticket(ticket["id"], priority=level)
    ticket["priority"] = level
    await client.db.audit(channel.guild.id, member.id, "ticket.priority", source=source,
                          target=f"ticket:{ticket['id']}",
                          details={"priority": level, **({"previous": previous}
                                                         if previous else {})})
    text = _("priority.changed", old=priority_label(_, previous),
             new=priority_label(_, level), user=member.mention)
    await (respond(text) if respond is not None else channel.send(text))
    await notify_high_priority(client, cfg, channel, ticket, member, level, previous)


async def notify_high_priority(client, cfg: dict, channel, ticket: dict, member, level: str,
                               previous: str | None) -> None:
    if is_kept(level) and not is_kept(previous):
        _ = translator(cfg)
        await telegram_notify(client, cfg, _(
            "tg.high", guild=esc(channel.guild.name), channel=esc(channel.name),
            type=esc(type_label(ticket)), subject=esc(ticket.get("subject") or "-"),
            user=esc(member), url=channel_url(channel.guild.id, channel.id),
        ), ticket_id=ticket["id"])


async def transfer_ticket(interaction: discord.Interaction, member: discord.Member) -> None:
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    if member.bot or not is_ticket_staff(member, cfg,
                                         *await ticket_roles(interaction.client.db, ticket)):
        await interaction.response.send_message(_("transfer.not_staff", user=member.mention),
                                                ephemeral=True)
        return
    if ticket.get("claimed_by") == member.id:
        await interaction.response.send_message(_("transfer.same", user=member.mention),
                                                ephemeral=True)
        return
    await move_ticket(interaction.client, interaction.channel, ticket, cfg, member,
                      interaction.user,
                      respond=lambda text: interaction.response.send_message(text))


async def move_ticket(client, channel, ticket: dict, cfg: dict, member: discord.Member,
                      by: discord.abc.User, *, source: str = "discord",
                      respond=None) -> None:
    """Give the ticket to another staff member (checked by the caller)."""
    _ = translator(cfg)
    changes = {"claimed_by": member.id}
    if ticket["status"] == config.STATUS_WAITING:
        changes["status"] = config.STATUS_IN_PROGRESS
    await client.db.update_ticket(ticket["id"], **changes)
    ticket.update(changes)
    await client.db.audit(channel.guild.id, by.id, "ticket.transfer", source=source,
                          target=f"ticket:{ticket['id']}", details={"to": member.id})
    text = _("transfer.done", user=member.mention, by=by.mention)
    await (respond(text) if respond is not None else channel.send(text))
    await refresh_controls(channel, ticket, _, member.display_name)


# --------------------------------------------------------------- closing ---

async def request_close(interaction: discord.Interaction, reason: str | None) -> None:
    ctx = await get_context(interaction)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    staff = is_staff(interaction.user, cfg)
    is_owner = interaction.user.id == ticket["owner_id"]
    if not (staff or is_owner):
        await interaction.response.send_message(_("close.not_allowed"), ephemeral=True)
        return
    if not reason:
        reason = _("close.reason_user") if is_owner else _("close.reason_staff")
    await interaction.response.send_message(_("close.closing"))
    await close_ticket(interaction.client, interaction.channel, ticket, interaction.user, reason)


def ticket_meta(client, guild: discord.Guild, channel: discord.TextChannel, ticket: dict,
                _: Translate, closed_by: discord.abc.User | None, reason: str | None) -> dict:
    def ts(value):
        if not value:
            return "-"
        return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M UTC")

    fields = [
        (_("field.type"), type_label(ticket)),
        (_("field.priority"), priority_label(_, ticket.get("priority"))),
        (_("field.subject"), ticket.get("subject") or "-"),
        (_("field.opened_by"), user_name(guild, ticket["owner_id"], client)),
        (_("field.opened_at"), ts(ticket["opened_at"])),
        (_("field.claimed_by"), user_name(guild, ticket.get("claimed_by"), client)),
    ]
    if closed_by is not None:
        fields += [
            (_("field.closed_by"), str(closed_by)),
            (_("field.closed_at"), ts(time.time())),
            (_("field.reason"), reason or "-"),
        ]
    return {"guild": guild.name, "channel": channel.name, "fields": fields}


async def set_members_can_write(channel: discord.TextChannel, can_write: bool) -> None:
    """Lock or unlock the ticket for its owner and the members added with /add."""
    if isinstance(channel, discord.Thread):
        try:  # a locked thread: only who can manage threads (the staff) can write
            await channel.edit(locked=not can_write, archived=False)
        except discord.HTTPException as e:
            print(f"Could not lock the thread {channel}: {e}")
        return
    for target, overwrite in list(channel.overwrites.items()):
        is_member = isinstance(target, discord.Member) or (
            isinstance(target, discord.Object) and getattr(target, "type", None) is discord.Member
        )
        if not is_member or target.id == channel.guild.me.id:
            continue
        overwrite.view_channel = True
        overwrite.send_messages = can_write
        try:
            await channel.set_permissions(target, overwrite=overwrite)
        except discord.HTTPException as e:
            print(f"Could not update permissions in #{channel}: {e}")


async def close_ticket(client, channel: discord.TextChannel, ticket: dict,
                       closed_by: discord.abc.User, reason: str,
                       source: str | None = None) -> None:
    """Close a ticket; `source` is discord/web/system (by default: system if the bot
    closes it, e.g. for inactivity, else discord)."""
    db = client.db
    guild = channel.guild
    cfg = await db.get_guild(guild.id)
    _ = translator(cfg)
    now = time.time()

    messages = await collect_messages(channel)
    notes = [dict(n, author=user_name(guild, n["author_id"], client))
             for n in await db.list_notes(ticket["id"])]
    meta = ticket_meta(client, guild, channel, ticket, _, closed_by, reason)
    staff_html = render_html(meta, messages, notes, _)
    staff_txt = render_txt(meta, messages, notes, _)
    user_html = render_html(meta, messages, [], _)

    await db.update_ticket(ticket["id"], status=config.STATUS_CLOSED, closed_at=now,
                     closed_by=closed_by.id, close_reason=reason, warned=False)
    by_bot = client.user is not None and closed_by.id == client.user.id
    await db.audit(guild.id, None if by_bot else closed_by.id, "ticket.close",
                   source=source or ("system" if by_bot else "discord"),
                   target=f"ticket:{ticket['id']}", details={"reason": reason})
    priority = ticket.get("priority")

    embed = discord.Embed(title=_("close.log_title", channel=channel.name),
                          color=discord.Color.red(), timestamp=datetime.now(UTC))
    embed.add_field(name=_("field.type"), value=type_label(ticket))
    embed.add_field(name=_("field.priority"), value=priority_label(_, priority))
    embed.add_field(name=_("field.opened_by"), value=f"<@{ticket['owner_id']}>")
    embed.add_field(name=_("field.claimed_by"),
                    value=f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "-")
    embed.add_field(name=_("field.closed_by"), value=closed_by.mention)
    embed.add_field(name=_("field.duration"), value=format_duration(now - ticket["opened_at"]))
    embed.add_field(name=_("field.reason"), value=reason[:1024], inline=False)
    if notes:
        embed.add_field(name=_("field.notes"), value=str(len(notes)))

    # Archive keeps everything; the log copy of Low/Medium tickets expires.
    log_id, archive_id = cfg.get("log_channel"), cfg.get("archive_channel")
    targets: dict[int, bool] = {}
    if archive_id:
        targets[archive_id] = False
    if log_id and log_id not in targets:
        targets[log_id] = not is_kept(priority)
    posted: dict[int, int] = {}
    for cid, auto_delete in targets.items():
        target = guild.get_channel(cid)
        if target is None:
            continue
        copy = embed.copy()
        if auto_delete:
            copy.set_footer(text=_("footer.auto_delete", days=cfg["retention_days"]))
        elif cid == archive_id:
            copy.set_footer(text=_("footer.archived"))
        else:
            copy.set_footer(text=_("footer.kept"))
        try:
            sent = await target.send(embed=copy, files=[
                discord.File(_bytes(staff_html), filename=f"{channel.name}.html"),
                discord.File(_bytes(staff_txt), filename=f"{channel.name}.txt"),
            ])
        except discord.HTTPException as e:
            print(f"Could not send the transcript to #{target}: {e}")
            continue
        posted[cid] = sent.id
        if auto_delete:
            await db.add_transcript_ref(guild.id, target.id, sent.id, priority, now)

    # The dashboard shows it; deleting the archive message deletes the ticket everywhere
    await db.save_transcript(
        guild_id=guild.id, ticket_id=ticket["id"], channel_name=channel.name,
        content=dump_transcript(meta, messages, notes), created_at=now,
        archive_channel_id=archive_id if archive_id in posted else None,
        archive_message_id=posted.get(archive_id) if archive_id else None,
        log_channel_id=log_id if log_id in posted and log_id != archive_id else None,
        log_message_id=posted.get(log_id) if log_id and log_id != archive_id else None)

    await telegram_notify(
        client, cfg,
        _("tg.closed", guild=esc(guild.name), channel=esc(channel.name),
          type=esc(type_label(ticket)), priority=priority_label(_, priority),
          user=esc(closed_by), reason=esc(reason)),
        document=staff_html, filename=f"{channel.name}.html",
        ticket_id=ticket["id"], answerable=False,
    )

    await set_members_can_write(channel, False)
    await channel.send(
        _("close.channel_message", user=closed_by.mention, reason=reason,
          hours=config.CLOSED_CHANNEL_HOURS),
        view=ClosedControls(_),
    )

    # Transcript + rating request for the user (DM, or in the channel if DMs are closed)
    owner = guild.get_member(ticket["owner_id"])
    ask_rating = not ticket.get("rating")
    delivered = False
    if owner is not None:
        try:
            await owner.send(
                _("close.dm", channel=channel.name, guild=guild.name, reason=reason)
                + ("\n\n" + _("rating.ask") if ask_rating else ""),
                file=discord.File(_bytes(user_html), filename=f"{channel.name}.html"),
                view=rating_view(ticket["id"]) if ask_rating else None,
            )
            delivered = True
        except discord.HTTPException:
            pass
    if ask_rating and not delivered:
        await channel.send(f"<@{ticket['owner_id']}> " + _("rating.ask"),
                           view=rating_view(ticket["id"]))


def _bytes(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


class ClosedControls(discord.ui.View):
    """Buttons shown in a closed ticket (persistent)."""

    def __init__(self, _: Translate | None = None):
        super().__init__(timeout=None)
        if _:
            self.reopen_btn.label = _("btn.reopen")
            self.delete_btn.label = _("btn.delete")

    @discord.ui.button(label="Reopen", emoji="🔓",
                       style=discord.ButtonStyle.success, custom_id="ticket:reopen")
    async def reopen_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await reopen_ticket(interaction)

    @discord.ui.button(label="Delete now", emoji="🗑️",
                       style=discord.ButtonStyle.danger, custom_id="ticket:delete")
    async def delete_btn(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await delete_ticket_now(interaction)


async def reopen_ticket(interaction: discord.Interaction) -> None:
    ctx = await get_context(interaction, staff=True, allow_closed=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    if ticket["status"] != config.STATUS_CLOSED:
        await interaction.response.send_message(_("reopen.not_closed"), ephemeral=True)
        return
    status = config.STATUS_IN_PROGRESS if ticket.get("claimed_by") else config.STATUS_WAITING
    await interaction.client.db.update_ticket(
        ticket["id"], status=status, closed_at=None, closed_by=None, close_reason=None,
        last_actor=None, last_activity=time.time(), warned=False,
        awaiting_staff_since=time.time(), staff_reminded_at=None,
    )
    await audit(interaction, "ticket.reopen", f"ticket:{ticket['id']}")
    await interaction.response.send_message(_("reopen.done", user=interaction.user.mention))
    if interaction.type == discord.InteractionType.component and interaction.message:
        try:
            await interaction.message.edit(view=None)
        except discord.HTTPException:
            pass
    await set_members_can_write(interaction.channel, True)


async def delete_ticket_now(interaction: discord.Interaction) -> None:
    ctx = await get_context(interaction, staff=True, allow_closed=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    if ticket["status"] != config.STATUS_CLOSED:
        await interaction.response.send_message(_("delete.not_closed"), ephemeral=True)
        return
    await interaction.response.send_message(_("delete.deleting"))
    await interaction.client.db.mark_channel_deleted(ticket["id"])
    await audit(interaction, "ticket.delete", f"ticket:{ticket['id']}")
    await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user}")


# --------------------------------------------------------------- ratings ---

class RatingButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"rate:(?P<tid>[0-9]+):(?P<stars>[1-5])"):
    """One of the five rating buttons; works in DMs and after a restart."""

    def __init__(self, ticket_id: int, value: int):
        super().__init__(discord.ui.Button(
            label=str(value), emoji="⭐", style=discord.ButtonStyle.secondary,
            custom_id=f"rate:{ticket_id}:{value}",
        ))
        self.ticket_id = ticket_id
        self.value = value

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["tid"]), int(match["stars"]))

    async def callback(self, interaction: discord.Interaction):
        db = interaction.client.db
        ticket = await db.get_ticket(self.ticket_id)
        _ = translator(await db.get_guild(ticket["guild_id"]) if ticket else None)
        if ticket is None:
            await interaction.response.send_message(_("rating.unavailable"), ephemeral=True)
        elif interaction.user.id != ticket["owner_id"]:
            await interaction.response.send_message(_("rating.not_owner"), ephemeral=True)
        elif ticket.get("rating"):
            await interaction.response.send_message(_("rating.already"), ephemeral=True)
        else:
            await interaction.response.send_modal(RatingModal(ticket, self.value, _))


def ticket_label(ticket: dict) -> str:
    if ticket.get("name"):
        return f"#{ticket['name']}"
    return f"#{ticket['number']}" if ticket.get("number") else "-"


def rating_view(ticket_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for value in range(1, 6):
        view.add_item(RatingButton(ticket_id, value))
    return view


class RatingModal(discord.ui.Modal):
    def __init__(self, ticket: dict, value: int, _: Translate):
        super().__init__(title=_("rating.modal_title", stars=stars(value))[:45])
        self.ticket_id = ticket["id"]
        self.value = value
        self._ = _
        self.comment = discord.ui.TextInput(style=discord.TextStyle.paragraph,
                                            required=False, max_length=500)
        self.add_item(discord.ui.Label(text=_("rating.comment"), component=self.comment))

    async def on_submit(self, interaction: discord.Interaction):
        _ = self._
        client = interaction.client
        db = client.db
        ticket = await db.get_ticket(self.ticket_id)
        if ticket is None or ticket.get("rating"):
            await interaction.response.send_message(_("rating.already"), ephemeral=True)
            return
        comment = self.comment.value.strip() or None
        await db.update_ticket(ticket["id"], rating=self.value, rating_comment=comment,
                         rated_at=time.time())
        await db.audit(ticket["guild_id"], interaction.user.id, "ticket.rate",
                       target=f"ticket:{ticket['id']}", details={"rating": self.value})

        original = interaction.message.content if interaction.message else ""
        await interaction.response.edit_message(
            content=(original + "\n\n" if original else "")
            + _("rating.thanks", stars=stars(self.value)),
            view=None,
        )

        cfg = await db.get_guild(ticket["guild_id"])
        guild = client.get_guild(ticket["guild_id"])
        if cfg is None or guild is None:
            return
        embed = discord.Embed(
            title=_("rating.log_title", ticket=ticket_label(ticket)),
            description=f"{stars(self.value)}" + (f"\n> {comment}" if comment else ""),
            color=discord.Color.gold(), timestamp=datetime.now(UTC),
        )
        embed.add_field(name=_("field.type"), value=type_label(ticket))
        embed.add_field(name=_("field.opened_by"), value=f"<@{ticket['owner_id']}>")
        embed.add_field(name=_("field.claimed_by"),
                        value=f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "-")
        log = guild.get_channel(cfg.get("log_channel") or 0)
        if log is not None:
            try:
                await log.send(embed=embed)
            except discord.HTTPException:
                pass
        await telegram_notify(client, cfg, _(
            "tg.rating", guild=esc(guild.name), ticket=esc(ticket_label(ticket)),
            stars=stars(self.value), comment=esc(comment or "-"),
            staff=esc(user_name(guild, ticket.get("claimed_by"), client)),
        ), ticket_id=ticket["id"], answerable=False)


# ------------------------------------------------------------ guidelines ---

def guidelines_embed(cfg: dict, _: Translate) -> discord.Embed:
    embed = discord.Embed(title=_("guidelines.title"),
                          description=_("guidelines.intro"), color=COLOR)
    for p in config.PRIORITIES:
        embed.add_field(
            name=priority_label(_, p),
            value=_("guidelines.priority." + p) + "\n" + _("guidelines.first_reply",
                                                           target=_("priority.target." + p)),
            inline=False,
        )
    kept = ", ".join(priority_label(_, p) for p in config.PRIORITIES if is_kept(p))
    embed.add_field(name=_("guidelines.transcripts_title"),
                    value=_("guidelines.transcripts", kept=kept, days=cfg["retention_days"]),
                    inline=False)
    if cfg.get("staff_reminders", 1):
        hours = config.STAFF_REPLY_HOURS
        embed.add_field(name=_("guidelines.reminders_title"),
                        value=_("guidelines.reminders", high=hours["high"],
                                medium=hours["medium"], low=hours["low"], none=hours[None]),
                        inline=False)
    return embed


async def refresh_guidelines(guild: discord.Guild, cfg: dict) -> None:
    channel = guild.get_channel(cfg.get("guidelines_channel") or 0)
    if channel is None or not cfg.get("guidelines_message"):
        return
    try:
        await channel.get_partial_message(cfg["guidelines_message"]).edit(
            embed=guidelines_embed(cfg, translator(cfg))
        )
    except discord.HTTPException:
        pass
