"""Server management from the dashboard, for admins: settings, ticket types with their
questions and roles, FAQ and escalation levels. The same rules and limits as the
admin commands on Discord. Changes are saved at once; what must change on Discord
(the panel, the guidelines, permissions) is queued for the bot."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from ...core import config
from ...core.i18n import LANGUAGES
from ...core.logic import new_type_key, valid_emoji
from ..discord_api import DiscordError
from ..permissions import Access
from ..sessions import client_ip
from .guilds import GuildAccess, Session

router = APIRouter(prefix="/guilds/{guild_id}", tags=["server management"])


async def admin_access(access: GuildAccess) -> Access:
    if not access.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the server's admins")
    return access


Admin = Annotated[Access, Depends(admin_access)]
TypeKey = Annotated[str, Path(min_length=1, max_length=40)]


async def record(request: Request, session: dict, access: Access, action: str,
                 target: str | None = None, **details) -> None:
    await request.app.state.store.audit(
        access.guild_id, session["user_id"], action, source="web", target=target,
        details={k: v for k, v in details.items() if v is not None} or None,
        ip=client_ip(request))


async def queue(request: Request, session: dict, access: Access, kind: str,
                **payload) -> int:
    return await request.app.state.store.enqueue_command(
        access.guild_id, kind, session["user_id"], payload or None)


def clean(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


# ----------------------------------------------------------- Discord roles ---

class Role(BaseModel):
    id: str
    name: str
    color: int
    position: int
    assignable: bool       # not @everyone and not managed by an integration (bots, boosts)


async def discord_roles(request: Request, guild_id: int) -> dict[int, dict]:
    cache = request.app.state.members_cache
    found = cache.get(("roles", guild_id))
    if found is None:
        try:
            found = {int(r["id"]): r
                     for r in await request.app.state.discord.guild_roles(guild_id)}
        except DiscordError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                "Discord can't be reached") from None
        cache.set(("roles", guild_id), found)
    return found


async def assignable_role(request: Request, guild_id: int, role_id: str) -> int:
    rid = int(role_id)
    role = (await discord_roles(request, guild_id)).get(rid)
    if role is None or rid == guild_id or role.get("managed"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Choose a normal role of the server (not @everyone or a bot's)")
    return rid


@router.get("/roles", response_model=list[Role])
async def list_roles(request: Request, access: Admin) -> list[Role]:
    """The server's roles, highest first."""
    roles = await discord_roles(request, access.guild_id)
    return sorted((Role(id=str(rid), name=r["name"], color=r.get("color", 0),
                        position=r.get("position", 0),
                        assignable=rid != access.guild_id and not r.get("managed"))
                   for rid, r in roles.items()), key=lambda r: -r.position)


# ----------------------------------------------------------- settings ------

class Settings(BaseModel):
    language: str
    retention_days: int
    staff_reminders: bool
    auto_assign: bool
    ticket_cooldown: int          # minutes, 0 = off
    telegram_messages: bool       # the users' messages in tickets also go to Telegram
    ticket_mode: Literal["channel", "thread"]
    staff_role: str | None


class SettingsChange(BaseModel):
    language: Literal[tuple(LANGUAGES)] | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)
    staff_reminders: bool | None = None
    auto_assign: bool | None = None
    telegram_messages: bool | None = None
    ticket_cooldown: int | None = Field(default=None, ge=0,
                                        le=config.MAX_TICKET_COOLDOWN_MINUTES)


class ModeChange(BaseModel):
    mode: Literal["channel", "thread"]


class Queued(BaseModel):
    command_id: int
    status: str = "pending"


def settings_of(cfg: dict) -> Settings:
    return Settings(language=cfg.get("language") or "en",
                    retention_days=cfg.get("retention_days") or 30,
                    staff_reminders=bool(cfg.get("staff_reminders", True)),
                    auto_assign=bool(cfg.get("auto_assign")),
                    ticket_cooldown=cfg.get("ticket_cooldown") or 0,
                    telegram_messages=bool(cfg.get("telegram_messages", True)),
                    ticket_mode=cfg.get("ticket_mode") or "channel",
                    staff_role=str(cfg["staff_role"]) if cfg.get("staff_role") else None)


@router.get("/settings", response_model=Settings)
async def get_settings(access: Admin) -> Settings:
    return settings_of(access.cfg)


@router.patch("/settings", response_model=Settings)
async def change_settings(request: Request, session: Session, access: Admin,
                          body: SettingsChange) -> Settings:
    """Change one or more settings. The panel and the guidelines on Discord are updated
    by the bot when the language, the retention or the reminders change."""
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return settings_of(access.cfg)
    cfg = await request.app.state.store.save_guild(access.guild_id, **changes)
    names = {"retention_days": "retention", "staff_reminders": "reminders",
             "auto_assign": "autoassign", "ticket_cooldown": "cooldown"}
    for field, value in changes.items():
        await record(request, session, access, "settings." + names.get(field, field),
                     value=value)
    if "language" in changes:
        await queue(request, session, access, "panel.refresh")
    if changes.keys() & {"language", "retention_days", "staff_reminders"}:
        await queue(request, session, access, "guidelines.refresh")
    return settings_of(cfg)


@router.put("/settings/mode", status_code=status.HTTP_202_ACCEPTED, response_model=Queued)
async def change_mode(request: Request, session: Session, access: Admin,
                      body: ModeChange) -> Queued:
    """Channels or private threads for new tickets. The bot checks its permissions in
    the panel channel and gives the staff roles access to the threads."""
    return Queued(command_id=await queue(request, session, access, "settings.mode",
                                         mode=body.mode))


# ------------------------------------------------------------ types -------

class Question(BaseModel):
    position: int
    label: str
    placeholder: str
    long: bool
    required: bool


class TypeOut(BaseModel):
    key: str
    label: str
    emoji: str
    description: str
    position: int
    roles: list[str]
    questions: list[Question]


class TypeIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    emoji: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=100)

    @field_validator("label", "emoji", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("emoji")
    @classmethod
    def _emoji(cls, value: str) -> str:
        if not valid_emoji(value):
            raise ValueError("not a valid emoji: use one emoji, or a custom one like "
                             "<:name:id>")
        return value


class TypeChange(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    emoji: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=100)

    @field_validator("emoji")
    @classmethod
    def _emoji(cls, value: str | None) -> str | None:
        if value is not None and not valid_emoji(value.strip()):
            raise ValueError("not a valid emoji: use one emoji, or a custom one like "
                             "<:name:id>")
        return clean(value)


class QuestionIn(BaseModel):
    label: str = Field(min_length=1, max_length=45)
    placeholder: str = Field(default="", max_length=100)
    long: bool = False
    required: bool = True


class RoleIn(BaseModel):
    role_id: str = Field(pattern=r"^\d{1,20}$")


async def type_out(request: Request, guild_id: int, t: dict,
                   roles: dict[str, list[int]]) -> TypeOut:
    questions = await request.app.state.store.list_questions(guild_id, t["key"])
    return TypeOut(key=t["key"], label=t["label"], emoji=t["emoji"],
                   description=t["description"] or "", position=t["position"] or 0,
                   roles=[str(r) for r in roles.get(t["key"], [])],
                   questions=[Question(position=q["position"], label=q["label"],
                                       placeholder=q["placeholder"] or "",
                                       long=bool(q["long"]), required=bool(q["required"]))
                              for q in questions])


async def existing_type(request: Request, access: Access, key: str) -> dict:
    t = await request.app.state.store.get_type(access.guild_id, key)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    return t


@router.get("/types", response_model=list[TypeOut])
async def list_types(request: Request, access: Admin) -> list[TypeOut]:
    """The ticket types with their questions and roles, in the panel's order."""
    store = request.app.state.store
    roles = await store.all_type_roles(access.guild_id)
    return [await type_out(request, access.guild_id, t, roles)
            for t in await store.list_types(access.guild_id)]


@router.post("/types", status_code=status.HTTP_201_CREATED, response_model=TypeOut)
async def add_type(request: Request, session: Session, access: Admin,
                   body: TypeIn) -> TypeOut:
    store = request.app.state.store
    types = await store.list_types(access.guild_id)
    if len(types) >= config.MAX_TICKET_TYPES:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You can have up to {config.MAX_TICKET_TYPES} ticket types")
    key = new_type_key(body.label, {t["key"] for t in types})
    await store.add_type(access.guild_id, key, body.label, body.emoji, body.description)
    await record(request, session, access, "type.add", f"type:{key}", label=body.label)
    await queue(request, session, access, "panel.refresh")
    return await type_out(request, access.guild_id,
                          await store.get_type(access.guild_id, key), {})


@router.patch("/types/{key}", response_model=TypeOut)
async def edit_type(request: Request, session: Session, access: Admin, key: TypeKey,
                    body: TypeChange) -> TypeOut:
    store = request.app.state.store
    await existing_type(request, access, key)
    changes = {k: clean(v) for k, v in body.model_dump(exclude_none=True).items()}
    if changes:
        await store.update_type(access.guild_id, key, **changes)
        await record(request, session, access, "type.edit", f"type:{key}", **changes)
        await queue(request, session, access, "panel.refresh")
    return await type_out(request, access.guild_id, await store.get_type(access.guild_id, key),
                          await store.all_type_roles(access.guild_id))


@router.delete("/types/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_type(request: Request, session: Session, access: Admin,
                      key: TypeKey) -> Response:
    """Open tickets of the type keep working; its questions, roles and FAQ go."""
    store = request.app.state.store
    await existing_type(request, access, key)
    if len(await store.list_types(access.guild_id)) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "The last ticket type can't be removed")
    await store.remove_type(access.guild_id, key)
    await record(request, session, access, "type.remove", f"type:{key}")
    await queue(request, session, access, "panel.refresh")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/types/{key}/questions", status_code=status.HTTP_201_CREATED,
             response_model=TypeOut)
async def add_question(request: Request, session: Session, access: Admin, key: TypeKey,
                       body: QuestionIn) -> TypeOut:
    """A question of the ticket form (up to 3 per type)."""
    store = request.app.state.store
    t = await existing_type(request, access, key)
    if len(await store.list_questions(access.guild_id, key)) >= config.MAX_TYPE_QUESTIONS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Up to {config.MAX_TYPE_QUESTIONS} questions per type")
    position = await store.add_question(access.guild_id, key, body.label.strip(),
                                        body.placeholder.strip(), long=body.long,
                                        required=body.required)
    await record(request, session, access, "type.question_add", f"type:{key}",
                 position=position)
    return await type_out(request, access.guild_id, t,
                          await store.all_type_roles(access.guild_id))


@router.delete("/types/{key}/questions/{position}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_question(request: Request, session: Session, access: Admin, key: TypeKey,
                          position: Annotated[int, Path(ge=1, le=10)]) -> Response:
    """The following questions move up by one."""
    await existing_type(request, access, key)
    if not await request.app.state.store.remove_question(access.guild_id, key, position):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    await record(request, session, access, "type.question_remove", f"type:{key}",
                 position=position)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/types/{key}/roles", status_code=status.HTTP_201_CREATED,
             response_model=TypeOut)
async def add_type_role(request: Request, session: Session, access: Admin, key: TypeKey,
                        body: RoleIn) -> TypeOut:
    """A role that handles this type instead of the staff role."""
    store = request.app.state.store
    t = await existing_type(request, access, key)
    rid = await assignable_role(request, access.guild_id, body.role_id)
    if not await store.add_type_role(access.guild_id, key, rid):
        raise HTTPException(status.HTTP_409_CONFLICT, "The role already handles this type")
    await record(request, session, access, "type.role_add", f"type:{key}", role=rid)
    if access.cfg.get("ticket_mode") == "thread":
        await queue(request, session, access, "thread.access", role_ids=[str(rid)])
    return await type_out(request, access.guild_id, t,
                          await store.all_type_roles(access.guild_id))


@router.delete("/types/{key}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_type_role(request: Request, session: Session, access: Admin,
                           key: TypeKey, role_id: Annotated[int, Path(ge=1)]) -> Response:
    await existing_type(request, access, key)
    if not await request.app.state.store.remove_type_role(access.guild_id, key, role_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The role doesn't handle this type")
    await record(request, session, access, "type.role_remove", f"type:{key}", role=role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ tickets -----

@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(request: Request, session: Session, access: Admin,
                        ticket_id: Annotated[int, Path(ge=1)]) -> Response:
    """Delete a closed ticket everywhere: dashboard, statistics, notes, transcript, its
    channel if still there, its messages in the log and archive channels and its
    Telegram notifications (like deleting the archive message). With LEGAL_HOLD_DAYS a
    hidden copy of the transcript stays for that long."""
    store = request.app.state.store
    t = await store.get_ticket(ticket_id)
    if t is None or t["guild_id"] != access.guild_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    if t["status"] != config.STATUS_CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Close the ticket first")
    telegram = await store.telegram_messages_of(ticket_id)   # gone with the ticket's row
    removed = await store.delete_ticket(ticket_id, request.app.state.settings.legal_hold_days)
    await record(request, session, access, "ticket.delete", f"ticket:{ticket_id}")
    # The bot deletes what is left on Discord: the channel, if it is still there (closed
    # tickets keep it for a while, to reopen them), the transcript messages and the
    # notifications on Telegram
    channel_id = None if t["channel_deleted"] else str(t["channel_id"])
    if removed or channel_id or telegram:
        await queue(request, session, access, "transcript.delete_messages",
                    channel_id=channel_id, telegram=telegram, transcripts=[
                        {k: str(v) if v else None for k, v in r.items() if k != "id"}
                        for r in removed])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ FAQ ---------

class FaqOut(BaseModel):
    id: int
    type_key: str | None          # None = every type
    question: str
    answer: str
    created_at: float


class FaqText(BaseModel):
    question: str = Field(min_length=1, max_length=config.FAQ_QUESTION_LENGTH)
    answer: str = Field(min_length=1, max_length=config.FAQ_ANSWER_LENGTH)

    @field_validator("question", "answer")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty text")
        return value.strip()


class FaqIn(FaqText):
    type_key: str | None = None


def faq_out(e: dict) -> FaqOut:
    return FaqOut(id=e["id"], type_key=e["type_key"], question=e["question"],
                  answer=e["answer"], created_at=e["created_at"])


@router.get("/faq", response_model=list[FaqOut])
async def list_faq(request: Request, access: Admin) -> list[FaqOut]:
    return [faq_out(e) for e in await request.app.state.store.list_faq(access.guild_id)]


@router.post("/faq", status_code=status.HTTP_201_CREATED, response_model=FaqOut)
async def add_faq(request: Request, session: Session, access: Admin, body: FaqIn) -> FaqOut:
    """Shown before the form of its type (or of every type)."""
    store = request.app.state.store
    if len(await store.list_faq(access.guild_id)) >= config.MAX_FAQ_ENTRIES:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You can have up to {config.MAX_FAQ_ENTRIES} FAQ entries")
    if body.type_key is not None:
        await existing_type(request, access, body.type_key)
    entry_id = await store.add_faq(access.guild_id, body.type_key, body.question,
                                   body.answer)
    await record(request, session, access, "faq.add", f"faq:{entry_id}", type=body.type_key)
    return faq_out(await store.get_faq(access.guild_id, entry_id))


@router.put("/faq/{entry_id}", response_model=FaqOut)
async def edit_faq(request: Request, session: Session, access: Admin,
                   entry_id: Annotated[int, Path(ge=1)], body: FaqText) -> FaqOut:
    store = request.app.state.store
    if not await store.update_faq(access.guild_id, entry_id, body.question, body.answer):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ entry not found")
    await record(request, session, access, "faq.edit", f"faq:{entry_id}")
    return faq_out(await store.get_faq(access.guild_id, entry_id))


@router.delete("/faq/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_faq(request: Request, session: Session, access: Admin,
                     entry_id: Annotated[int, Path(ge=1)]) -> Response:
    if not await request.app.state.store.remove_faq(access.guild_id, entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ entry not found")
    await record(request, session, access, "faq.remove", f"faq:{entry_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ escalation --

class LevelOut(BaseModel):
    level: int
    role_id: str
    after_hours: float | None     # None = only with /escalate or the dashboard


class LevelIn(BaseModel):
    role_id: str = Field(pattern=r"^\d{1,20}$")
    after_hours: float | None = Field(default=None, ge=0.5, le=config.MAX_ESCALATION_HOURS)


async def levels_out(request: Request, guild_id: int) -> list[LevelOut]:
    return [LevelOut(level=lv["level"], role_id=str(lv["role_id"]),
                     after_hours=lv["after_hours"])
            for lv in await request.app.state.store.escalation_levels(guild_id)]


@router.get("/escalation", response_model=list[LevelOut])
async def list_levels(request: Request, access: Admin) -> list[LevelOut]:
    return await levels_out(request, access.guild_id)


@router.post("/escalation", status_code=status.HTTP_201_CREATED,
             response_model=list[LevelOut])
async def add_level(request: Request, session: Session, access: Admin,
                    body: LevelIn) -> list[LevelOut]:
    """The next level. A higher level must wait longer than the ones below it."""
    store = request.app.state.store
    levels = await store.escalation_levels(access.guild_id)
    rid = await assignable_role(request, access.guild_id, body.role_id)
    if len(levels) >= config.MAX_ESCALATION_LEVELS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You can have up to {config.MAX_ESCALATION_LEVELS} levels")
    if any(lv["role_id"] == rid for lv in levels):
        raise HTTPException(status.HTTP_409_CONFLICT, "The role is already a level")
    timed = [lv["after_hours"] for lv in levels if lv["after_hours"]]
    if body.after_hours is not None and timed and body.after_hours <= max(timed):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Use more than {max(timed):g} hours (the levels below wait "
                            "that long)")
    level = await store.add_escalation_level(access.guild_id, rid, body.after_hours)
    await record(request, session, access, "escalation.add", f"level:{level}", role=rid,
                 after_hours=body.after_hours)
    return await levels_out(request, access.guild_id)


@router.delete("/escalation/{level}", response_model=list[LevelOut])
async def remove_level(request: Request, session: Session, access: Admin,
                       level: Annotated[int, Path(ge=1, le=config.MAX_ESCALATION_LEVELS)]
                       ) -> list[LevelOut]:
    """The levels above it move down by one."""
    if not await request.app.state.store.remove_escalation_level(access.guild_id, level):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Level not found")
    await record(request, session, access, "escalation.remove", f"level:{level}")
    return await levels_out(request, access.guild_id)

