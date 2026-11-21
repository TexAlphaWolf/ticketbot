"""For every member of a server, not only the staff: open a ticket from the browser (the
same form as on Discord, with the FAQ first) and see your own tickets and transcripts.
The bot opens the ticket on Discord, with the same checks (blocks, cooldown, one open
ticket at a time)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, Field

from ...core import config
from ...core.logic import answers_text
from ...core.transcripts import load_transcript
from ..discord_api import guild_icon_url
from .guilds import Session, TranscriptMessage, TranscriptOut, oauth_guilds

router = APIRouter(prefix="/me/guilds", tags=["members"])

GuildId = Annotated[int, Path(ge=1, le=2**63 - 1)]


class MemberGuild(BaseModel):
    id: str
    name: str
    icon_url: str | None


class FormQuestion(BaseModel):
    label: str
    placeholder: str
    long: bool
    required: bool
    max_length: int


class FaqItem(BaseModel):
    question: str
    answer: str


class FormType(BaseModel):
    key: str
    label: str
    emoji: str
    description: str
    questions: list[FormQuestion]   # empty: a free description instead
    faq: list[FaqItem]


class MyTicket(BaseModel):
    id: int
    number: int | None
    name: str | None
    type_label: str
    type_emoji: str
    subject: str | None
    status: str
    channel_id: str | None
    opened_at: float
    closed_at: float | None
    has_transcript: bool


class MemberGuildDetail(MemberGuild):
    types: list[FormType]
    tickets: list[MyTicket]


class NewTicket(BaseModel):
    type_key: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    answers: list[str] = Field(default=[], max_length=config.MAX_TYPE_QUESTIONS)


class FaqResult(BaseModel):
    type_key: str = Field(min_length=1, max_length=40)
    solved: bool


class Queued(BaseModel):
    command_id: int
    status: str = "pending"


class MyCommand(BaseModel):
    status: Literal["pending", "running", "done", "failed"]
    result: str | None
    channel_id: str | None          # the new ticket, when done


async def member_guild(request: Request, session: dict, guild_id: int) -> dict:
    """The server, if the user is in it and TicketBot is set up there (else 404)."""
    oauth = (await oauth_guilds(request, session)).get(guild_id)
    cfg = await request.app.state.store.get_guild(guild_id)
    if oauth is None or cfg is None or not cfg.get("staff_role"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    return oauth


async def my_ticket(request: Request, t: dict) -> MyTicket:
    return MyTicket(
        id=t["id"], number=t["number"], name=t["name"], type_label=t["type_label"],
        type_emoji=t["type_emoji"], subject=t["subject"], status=t["status"],
        channel_id=None if t["channel_deleted"] else str(t["channel_id"]),
        opened_at=t["opened_at"], closed_at=t["closed_at"],
        has_transcript=await request.app.state.store.ticket_transcript(t["id"]) is not None)


@router.get("", response_model=list[MemberGuild])
async def my_guilds(request: Request, session: Session) -> list[MemberGuild]:
    """The servers you are in where TicketBot is set up."""
    store = request.app.state.store
    result = []
    for guild_id, g in (await oauth_guilds(request, session)).items():
        cfg = await store.get_guild(guild_id)
        if cfg and cfg.get("staff_role"):
            result.append(MemberGuild(id=str(guild_id), name=g["name"],
                                      icon_url=guild_icon_url(guild_id, g.get("icon"))))
    return sorted(result, key=lambda g: g.name.lower())


@router.get("/{guild_id}", response_model=MemberGuildDetail)
async def my_guild(request: Request, session: Session, guild_id: GuildId) -> MemberGuildDetail:
    """The ticket form of a server (types, their questions and FAQ) and your tickets."""
    g = await member_guild(request, session, guild_id)
    store = request.app.state.store
    types = []
    for t in await store.list_types(guild_id):
        questions = await store.list_questions(guild_id, t["key"])
        faq = await store.faq_for_type(guild_id, t["key"], config.FAQ_SHOWN)
        types.append(FormType(
            key=t["key"], label=t["label"], emoji=t["emoji"], description=t["description"] or "",
            questions=[FormQuestion(label=q["label"], placeholder=q["placeholder"] or "",
                                    long=bool(q["long"]), required=bool(q["required"]),
                                    max_length=config.LONG_ANSWER_LENGTH if q["long"]
                                    else config.SHORT_ANSWER_LENGTH) for q in questions],
            faq=[FaqItem(question=f["question"], answer=f["answer"]) for f in faq]))
    tickets = [await my_ticket(request, t)
               for t in await store.tickets_of_owner(guild_id, session["user_id"])]
    return MemberGuildDetail(id=str(guild_id), name=g["name"],
                             icon_url=guild_icon_url(guild_id, g.get("icon")),
                             types=types, tickets=tickets)


@router.post("/{guild_id}/tickets", status_code=status.HTTP_202_ACCEPTED,
             response_model=Queued)
async def open_ticket(request: Request, session: Session, guild_id: GuildId,
                      body: NewTicket) -> Queued:
    """Open a ticket: the bot creates it on Discord within a few seconds (see
    GET .../commands/{id} for the channel, or why it couldn't)."""
    await member_guild(request, session, guild_id)
    store = request.app.state.store
    ticket_type = await store.get_type(guild_id, body.type_key)
    if ticket_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    questions = await store.list_questions(guild_id, body.type_key)
    subject = body.subject.strip()
    if not subject:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The subject is empty")
    if questions:
        if len(body.answers) != len(questions):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "Answer every question of the form")
        answers = []
        for q, answer in zip(questions, body.answers, strict=True):
            answer = answer.strip()
            limit = config.LONG_ANSWER_LENGTH if q["long"] else config.SHORT_ANSWER_LENGTH
            if q["required"] and not answer:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    f"“{q['label']}” is required")
            if len(answer) > limit:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    f"“{q['label']}” is longer than {limit} characters")
            answers.append((q["label"], answer))
        description = answers_text(answers)
    else:
        description = body.description.strip()
        if not description:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "The description is empty")
    if await store.has_unfinished_command(guild_id, session["user_id"], "ticket.open"):
        raise HTTPException(status.HTTP_409_CONFLICT, "A ticket is already being opened")
    command_id = await store.enqueue_command(guild_id, "ticket.open", session["user_id"], {
        "type_key": body.type_key, "subject": subject, "description": description})
    if await store.faq_for_type(guild_id, body.type_key, 1):   # shown, and not enough
        await store.record_faq_result(guild_id, body.type_key, solved=False)
    return Queued(command_id=command_id)


@router.post("/{guild_id}/faq", status_code=status.HTTP_204_NO_CONTENT)
async def faq_result(request: Request, session: Session, guild_id: GuildId,
                     body: FaqResult) -> None:
    """The FAQ solved the problem (counted in the statistics, without your name)."""
    await member_guild(request, session, guild_id)
    if body.solved:
        await request.app.state.store.record_faq_result(guild_id, body.type_key, solved=True)


@router.get("/{guild_id}/commands/{command_id}", response_model=MyCommand)
async def my_command(request: Request, session: Session, guild_id: GuildId,
                     command_id: Annotated[int, Path(ge=1)]) -> MyCommand:
    c = await request.app.state.store.get_command(command_id)
    if c is None or c["guild_id"] != guild_id or c["requested_by"] != session["user_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    result = c["result"]
    channel_id = result.removeprefix("channel:") if result and result.startswith(
        "channel:") else None
    return MyCommand(status=c["status"], result=None if channel_id else result,
                     channel_id=channel_id)


@router.get("/{guild_id}/tickets/{ticket_id}/transcript", response_model=TranscriptOut)
async def my_transcript(request: Request, session: Session, guild_id: GuildId,
                        ticket_id: Annotated[int, Path(ge=1)]) -> TranscriptOut:
    """The conversation of one of your closed tickets (without the staff notes)."""
    await member_guild(request, session, guild_id)
    store = request.app.state.store
    t = await store.get_ticket(ticket_id)
    if t is None or t["guild_id"] != guild_id or t["owner_id"] != session["user_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    transcript = await store.ticket_transcript(ticket_id)
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transcript for this ticket")
    _meta, messages, _notes = load_transcript(transcript["content"])
    return TranscriptOut(
        channel_name=transcript["channel_name"], created_at=transcript["created_at"],
        messages=[TranscriptMessage.from_message(m) for m in messages], notes=[])

