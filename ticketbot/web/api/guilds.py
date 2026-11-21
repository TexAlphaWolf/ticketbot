"""Servers, tickets and statistics, read-only, for the admins and staff of each server."""

import asyncio
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel

from ...core import config
from ...core.i18n import t as translate
from ...core.logic import compute_stats
from ...core.transcripts import load_transcript, render_html
from ..discord_api import DiscordError, avatar_url, guild_icon_url
from ..permissions import Access, is_admin
from ..sessions import client_ip, current_session, discord_token

router = APIRouter(prefix="/guilds", tags=["servers"])

Session = Annotated[dict, Depends(current_session)]
GuildId = Annotated[int, Path(ge=1, le=2**63 - 1)]
PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}


# ------------------------------------------------------------ responses ---

class GuildSummary(BaseModel):
    id: str
    name: str
    icon_url: str | None
    role: Literal["admin", "staff"]


class TicketType(BaseModel):
    key: str
    label: str
    emoji: str
    description: str


class GuildDetail(GuildSummary):
    language: str
    ticket_mode: str
    types: list[TicketType]
    waiting: int
    in_progress: int
    can_see_stats: bool
    escalation_levels: int



class Person(BaseModel):
    name: str
    avatar_url: str


class StaffMember(Person):
    id: str


class TicketSummary(BaseModel):
    id: int
    number: int | None
    name: str | None
    type_key: str
    type_label: str
    type_emoji: str
    subject: str | None
    status: str
    priority: str | None
    owner_id: str
    claimed_by: str | None
    assigned_to: str | None
    escalation_level: int
    is_thread: bool
    channel_id: str | None
    opened_at: float
    last_activity: float
    closed_at: float | None


class TicketPage(BaseModel):
    tickets: list[TicketSummary]
    next_before: int | None        # pass as `before` for the next page
    people: dict[str, Person]      # names and avatars of the members in the list


class Note(BaseModel):
    author_id: str
    text: str
    created_at: float


class TicketDetail(TicketSummary):
    description: str | None
    first_response_at: float | None
    closed_by: str | None
    close_reason: str | None
    rating: int | None
    rating_comment: str | None
    escalated_at: float | None
    notes: list[Note]
    people: dict[str, Person]
    has_transcript: bool


class TranscriptAttachment(BaseModel):
    filename: str
    url: str
    image: bool


class TranscriptEmbed(BaseModel):
    title: str
    description: str
    fields: list[tuple[str, str]]


class TranscriptMessage(BaseModel):
    author: str
    author_id: str
    avatar: str
    bot: bool
    created_at: float
    content: str
    attachments: list[TranscriptAttachment]
    embeds: list[TranscriptEmbed]


class TranscriptNote(BaseModel):
    author: str
    author_id: str
    text: str
    created_at: float


class TranscriptOut(BaseModel):
    channel_name: str
    created_at: float
    messages: list[TranscriptMessage]
    notes: list[TranscriptNote]


class LeaderboardRow(BaseModel):
    staff_id: str
    handled: int
    avg_rating: float | None
    ratings: int
    avg_first_response: float | None


class Stats(BaseModel):
    period: str
    opened: int
    closed: int
    open: int
    unclaimed: int
    avg_first_response: float | None   # seconds
    avg_resolution: float | None       # seconds
    avg_rating: float | None
    ratings: int
    by_type: dict[str, int]
    by_priority: dict[str, int]        # "none" = no priority
    faq_solved: int
    faq_opened: int
    leaderboard: list[LeaderboardRow]
    people: dict[str, Person]


# ------------------------------------------------------------ access -----

async def oauth_guilds(request: Request, session: dict) -> dict[int, dict]:
    """The servers of the logged-in user (from Discord, cached for a minute)."""
    cache = request.app.state.guilds_cache
    found = cache.get(session["id"])
    if found is None:
        token = await discord_token(request, session)
        try:
            found = {int(g["id"]): g
                     for g in await request.app.state.discord.user_guilds(token)}
        except DiscordError as e:
            if e.status == 401:
                await request.app.state.store.delete_web_session(session["id"])
                raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                    "The Discord login expired: log in again") from None
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                "Discord can't be reached") from None
        cache.set(session["id"], found)
    return found


async def member(request: Request, guild_id: int, user_id: int) -> dict | None:
    cache = request.app.state.members_cache
    key = (guild_id, user_id)
    found = cache.get(key)
    if found is None:
        try:
            found = await request.app.state.discord.member(guild_id, user_id) or {}
        except DiscordError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                "Discord can't be reached") from None
        cache.set(key, found)
    return found or None


async def user_profile(request: Request, user_id: int) -> dict | None:
    """{"user": ...} like a member, for someone who isn't in the server."""
    cache = request.app.state.members_cache
    key = ("user", user_id)
    found = cache.get(key)
    if found is None:
        try:
            user = await request.app.state.discord.user(user_id)
        except DiscordError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                "Discord can't be reached") from None
        found = {"user": user} if user else {}
        cache.set(key, found)
    return found or None


async def load_access(request: Request, session: dict, guild_id: int,
                      oauth_guild: dict) -> Access:
    store = request.app.state.store
    cfg = await store.get_guild(guild_id) or {}
    admin = is_admin(oauth_guild)
    roles: frozenset[int] = frozenset()
    if not admin:
        found = await member(request, guild_id, session["user_id"])
        roles = frozenset(int(r) for r in (found or {}).get("roles", []))
    return Access(guild_id=guild_id, admin=admin, roles=roles, cfg=cfg,
                  type_roles=await store.all_type_roles(guild_id) if cfg else {},
                  levels=await store.escalation_levels(guild_id) if cfg else [])


async def guild_access(request: Request, session: Session, guild_id: GuildId) -> Access:
    """Dependency: the user's access to one server; 404 if they can't use it here (not
    in it, not staff, or the bot isn't set up there: the same answer, nothing leaks)."""
    oauth_guild = (await oauth_guilds(request, session)).get(guild_id)
    configured = await request.app.state.store.get_guild(guild_id)
    if oauth_guild is None or configured is None or not configured.get("staff_role"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    access = await load_access(request, session, guild_id, oauth_guild)
    if access.role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    request.state.oauth_guild = oauth_guild
    return access


GuildAccess = Annotated[Access, Depends(guild_access)]


async def people(request: Request, guild_id: int, ids: set[int]) -> dict[str, Person]:
    """Names and avatars of members, from Discord (cached); unknown ones are left out."""
    sem = asyncio.Semaphore(5)

    async def one(user_id: int):
        async with sem:
            try:
                found = await member(request, guild_id, user_id)
                # Not in the server anymore (e.g. left after the ticket): their profile
                return user_id, found or await user_profile(request, user_id)
            except HTTPException:
                return user_id, None

    found = {}
    for user_id, m in await asyncio.gather(*(one(i) for i in list(ids)[:50])):
        if m and m.get("user"):
            user = m["user"]
            found[str(user_id)] = Person(
                name=m.get("nick") or user.get("global_name") or user["username"],
                avatar_url=avatar_url(user_id, user.get("avatar")))
    return found


def _sid(value: int | None) -> str | None:
    return str(value) if value is not None else None


def summary(t: dict) -> TicketSummary:
    return TicketSummary(
        id=t["id"], number=t["number"], name=t["name"], type_key=t["type_key"],
        type_label=t["type_label"], type_emoji=t["type_emoji"], subject=t["subject"],
        status=t["status"], priority=t["priority"], owner_id=str(t["owner_id"]),
        claimed_by=_sid(t["claimed_by"]), assigned_to=_sid(t["assigned_to"]),
        escalation_level=t["escalation_level"] or 0, is_thread=bool(t["is_thread"]),
        channel_id=None if t["channel_deleted"] else _sid(t["channel_id"]),
        opened_at=t["opened_at"], last_activity=t["last_activity"],
        closed_at=t["closed_at"])


# ------------------------------------------------------------ routes -----

@router.get("", response_model=list[GuildSummary])
async def list_guilds(request: Request, session: Session) -> list[GuildSummary]:
    """The servers where you are admin or staff and TicketBot is set up."""
    store = request.app.state.store
    result = []
    for guild_id, g in (await oauth_guilds(request, session)).items():
        cfg = await store.get_guild(guild_id)
        if not cfg or not cfg.get("staff_role"):
            continue
        role = (await load_access(request, session, guild_id, g)).role
        if role:
            result.append(GuildSummary(id=str(guild_id), name=g["name"], role=role,
                                       icon_url=guild_icon_url(guild_id, g.get("icon"))))
    return sorted(result, key=lambda g: g.name.lower())


@router.get("/{guild_id}", response_model=GuildDetail)
async def get_guild(request: Request, access: GuildAccess) -> GuildDetail:
    store, g = request.app.state.store, request.state.oauth_guild
    waiting, in_progress = await store.queue_counts(access.guild_id)
    return GuildDetail(
        id=str(access.guild_id), name=g["name"], role=access.role,
        icon_url=guild_icon_url(access.guild_id, g.get("icon")),
        language=access.cfg.get("language") or "en",
        ticket_mode=access.cfg.get("ticket_mode") or "channel",
        types=[TicketType(key=t["key"], label=t["label"], emoji=t["emoji"],
                          description=t["description"] or "")
               for t in await store.list_types(access.guild_id)],
        waiting=waiting, in_progress=in_progress, can_see_stats=access.can_see_stats,
        escalation_levels=len(access.levels))


@router.get("/{guild_id}/staff", response_model=list[StaffMember])
async def list_staff(request: Request, access: GuildAccess) -> list[StaffMember]:
    """Staff members to transfer a ticket to: the auto-assign rotation and whoever
    handled a ticket in the last 90 days (Discord can't list a server's members without
    a privileged intent). The bot checks again that the chosen one is staff."""
    store = request.app.state.store
    ids = {s["user_id"] for s in await store.available_staff(access.guild_id)}
    recent = await store.tickets_since(access.guild_id, time.time() - 90 * 86400)
    ids |= {t["claimed_by"] for t in recent if t["claimed_by"]}
    found = await people(request, access.guild_id, ids)
    return sorted((StaffMember(id=i, **p.model_dump()) for i, p in found.items()),
                  key=lambda s: s.name.lower())


@router.get("/{guild_id}/tickets", response_model=TicketPage)
async def list_tickets(
        request: Request, access: GuildAccess,
        state: Literal["open", "closed", "all"] = Query("open", alias="status"),
        type: str | None = None,
        q: Annotated[str | None, Query(max_length=100, description=(
            "Text to find: a ticket number (12 or #12), a Discord ID, or words of the "
            "channel name, type, subject or form answers"))] = None,
        priority: Literal["low", "medium", "high", "none"] | None = None,
        person: Annotated[str | None, Query(pattern=r"^\d{1,20}$", description=(
            "Discord ID: tickets opened, claimed or assigned to them"))] = None,
        opened_from: Annotated[float | None, Query(alias="from", ge=0,
                                                   description="Unix time")] = None,
        opened_to: Annotated[float | None, Query(alias="to", ge=0,
                                                 description="Unix time")] = None,
        before: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50) -> TicketPage:
    """The tickets you can see, newest first, a page at a time, with filters and search."""
    rows, next_before = await request.app.state.store.list_tickets(
        access.guild_id, status=state, type_key=type, scope=access.scope(),
        before_id=before, limit=limit, priority=priority,
        person=int(person) if person else None, opened_from=opened_from,
        opened_to=opened_to, text=q)
    ids = {t[k] for t in rows for k in ("owner_id", "claimed_by", "assigned_to") if t[k]}
    return TicketPage(tickets=[summary(t) for t in rows], next_before=next_before,
                      people=await people(request, access.guild_id, ids))


@router.get("/{guild_id}/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(request: Request, session: Session, access: GuildAccess,
                     ticket_id: Annotated[int, Path(ge=1)]) -> TicketDetail:
    """One ticket with its form answers, notes, closing and rating."""
    store = request.app.state.store
    t = await store.get_ticket(ticket_id)
    if t is None or t["guild_id"] != access.guild_id or not access.can_see(t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    notes = await store.list_notes(ticket_id)
    ids = {t[k] for k in ("owner_id", "claimed_by", "assigned_to", "closed_by") if t[k]}
    ids |= {n["author_id"] for n in notes}
    if t["owner_id"] != session["user_id"]:
        await store.audit(access.guild_id, session["user_id"], "ticket.view", source="web",
                          target=f"ticket:{ticket_id}", ip=client_ip(request))
    return TicketDetail(
        **summary(t).model_dump(), description=t["description"],
        first_response_at=t["first_response_at"], closed_by=_sid(t["closed_by"]),
        close_reason=t["close_reason"], rating=t["rating"],
        rating_comment=t["rating_comment"], escalated_at=t["escalated_at"],
        notes=[Note(author_id=str(n["author_id"]), text=n["text"],
                    created_at=n["created_at"]) for n in notes],
        people=await people(request, access.guild_id, ids),
        has_transcript=await store.ticket_transcript(ticket_id) is not None)


async def visible_transcript(request: Request, session: dict, access: Access,
                             ticket_id: int) -> tuple[dict, dict]:
    store = request.app.state.store
    t = await store.get_ticket(ticket_id)
    if t is None or t["guild_id"] != access.guild_id or not access.can_see(t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    transcript = await store.ticket_transcript(ticket_id)
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transcript for this ticket")
    await store.audit(access.guild_id, session["user_id"], "ticket.transcript_view",
                      source="web", target=f"ticket:{ticket_id}", ip=client_ip(request))
    return t, transcript


@router.get("/{guild_id}/tickets/{ticket_id}/transcript", response_model=TranscriptOut)
async def get_transcript(request: Request, session: Session, access: GuildAccess,
                         ticket_id: Annotated[int, Path(ge=1)]) -> TranscriptOut:
    """The conversation of a closed ticket, with the staff notes as they were."""
    _t, transcript = await visible_transcript(request, session, access, ticket_id)
    _meta, messages, notes = load_transcript(transcript["content"])
    return TranscriptOut(
        channel_name=transcript["channel_name"], created_at=transcript["created_at"],
        messages=[TranscriptMessage(
            author=m.author, author_id=str(m.author_id), avatar=m.avatar, bot=m.bot,
            created_at=m.created_at.timestamp(), content=m.content,
            attachments=[TranscriptAttachment(**a) for a in m.attachments],
            embeds=[TranscriptEmbed(title=e["title"], description=e["description"],
                                    fields=[(str(n), str(v)) for n, v in e["fields"]])
                    for e in m.embeds]) for m in messages],
        notes=[TranscriptNote(**n) for n in notes])


@router.get("/{guild_id}/tickets/{ticket_id}/transcript.html",
            response_class=Response, responses={200: {"content": {"text/html": {}}}})
async def download_transcript(request: Request, session: Session, access: GuildAccess,
                              ticket_id: Annotated[int, Path(ge=1)]) -> Response:
    """The same HTML file the bot posts in the log channel, as a download."""
    _t, transcript = await visible_transcript(request, session, access, ticket_id)
    meta, messages, notes = load_transcript(transcript["content"])
    lang = access.cfg.get("language") or "en"
    page = render_html(meta, messages, notes, lambda key, /, **kw: translate(lang, key, **kw))
    name = "".join(c for c in transcript["channel_name"] if c.isalnum() or c in "-_") \
        or "transcript"
    return Response(page, media_type="text/html; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{name}.html"',
        # Never shown inside the dashboard: a sandbox even if a browser opens it here
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src https: data:; "
                                   "style-src 'unsafe-inline'"})


@router.get("/{guild_id}/stats", response_model=Stats)
async def get_stats(request: Request, access: GuildAccess,
                    period: Literal["7", "30", "90", "all"] = "30") -> Stats:
    """The same numbers as /stats on Discord (admins and the staff role)."""
    if not access.can_see_stats:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and the staff role")
    store = request.app.state.store
    days = PERIODS[period]
    since = time.time() - days * 86400 if days else 0
    s = compute_stats(await store.tickets_since(access.guild_id, since))
    faq = await store.faq_results_since(access.guild_id, since)
    board = s["leaderboard"][:10]
    return Stats(
        period=period, opened=s["opened"], closed=s["closed"], open=s["open"],
        unclaimed=s["unclaimed"], avg_first_response=s["avg_first_response"],
        avg_resolution=s["avg_resolution"], avg_rating=s["avg_rating"],
        ratings=s["ratings"], by_type=dict(s["by_type"].most_common()),
        by_priority={p or "none": s["by_priority"].get(p, 0)
                     for p in (*config.PRIORITIES, None)},
        faq_solved=faq["solved"], faq_opened=faq["opened"],
        leaderboard=[LeaderboardRow(staff_id=str(r["staff_id"]), handled=r["handled"],
                                    avg_rating=r["avg_rating"], ratings=r["ratings"],
                                    avg_first_response=r["avg_first_response"])
                     for r in board],
        people=await people(request, access.guild_id, {r["staff_id"] for r in board}))
