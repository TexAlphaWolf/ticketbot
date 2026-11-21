"""Actions on tickets from the dashboard.

Most actions happen on Discord (a message in the ticket, permissions, closing), so the
web puts them in a queue and the bot carries them out within a few seconds:
the answer is 202 with the command's id, and GET /guilds/{id}/commands/{n} tells how it
went. Notes live only in the database, so they are saved at once.
"""

import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, Field, field_validator

from ...core import config
from ..sessions import client_ip
from .guilds import GuildAccess, Note, Session

router = APIRouter(prefix="/guilds/{guild_id}", tags=["ticket actions"])

TicketId = Annotated[int, Path(ge=1)]
Priority = Literal[tuple(config.PRIORITIES)]


class Queued(BaseModel):
    command_id: int
    status: str


class CommandStatus(BaseModel):
    id: int
    kind: str
    status: Literal["pending", "running", "done", "failed"]
    result: str | None
    created_at: float
    finished_at: float | None


class CloseBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class PriorityBody(BaseModel):
    priority: Priority


class TransferBody(BaseModel):
    member_id: str = Field(pattern=r"^\d{1,20}$")


class EscalateBody(BaseModel):
    level: int | None = Field(default=None, ge=1, le=config.MAX_ESCALATION_LEVELS)
    reason: str | None = Field(default=None, max_length=300)


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the text is empty")
        return value.strip()


class NoteBody(TextBody):
    text: str = Field(min_length=1, max_length=1000)


async def open_ticket_for(request: Request, access, ticket_id: int) -> dict:
    """The ticket, if this user can see it and it is still open."""
    t = await request.app.state.store.get_ticket(ticket_id)
    if t is None or t["guild_id"] != access.guild_id or not access.can_see(t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    if t["status"] == config.STATUS_CLOSED or t["channel_deleted"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "The ticket is closed")
    return t


async def queue(request: Request, session: dict, access, ticket: dict, kind: str,
                **payload) -> Queued:
    store = request.app.state.store
    command_id = await store.enqueue_command(
        access.guild_id, kind, session["user_id"],
        {"ticket_id": ticket["id"], **{k: v for k, v in payload.items() if v is not None}})
    await store.audit(access.guild_id, session["user_id"], "web.queue", source="web",
                      target=f"ticket:{ticket['id']}", details={"kind": kind},
                      ip=client_ip(request))
    return Queued(command_id=command_id, status="pending")


ACCEPTED = {"status_code": status.HTTP_202_ACCEPTED, "response_model": Queued}


@router.post("/tickets/{ticket_id}/close", **ACCEPTED)
async def close(request: Request, session: Session, access: GuildAccess,
                ticket_id: TicketId, body: CloseBody) -> Queued:
    """Close the ticket, with an optional reason (transcripts and rating as on Discord)."""
    t = await open_ticket_for(request, access, ticket_id)
    return await queue(request, session, access, t, "ticket.close", reason=body.reason)


@router.post("/tickets/{ticket_id}/claim", **ACCEPTED)
async def claim(request: Request, session: Session, access: GuildAccess,
                ticket_id: TicketId, body: PriorityBody) -> Queued:
    """Take the ticket, choosing its priority."""
    t = await open_ticket_for(request, access, ticket_id)
    if t["claimed_by"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "The ticket was already claimed")
    return await queue(request, session, access, t, "ticket.claim", priority=body.priority)


@router.post("/tickets/{ticket_id}/priority", **ACCEPTED)
async def priority(request: Request, session: Session, access: GuildAccess,
                   ticket_id: TicketId, body: PriorityBody) -> Queued:
    t = await open_ticket_for(request, access, ticket_id)
    return await queue(request, session, access, t, "ticket.priority",
                       priority=body.priority)


@router.post("/tickets/{ticket_id}/transfer", **ACCEPTED)
async def transfer(request: Request, session: Session, access: GuildAccess,
                   ticket_id: TicketId, body: TransferBody) -> Queued:
    """Give the ticket to another staff member (the bot checks they are staff for it)."""
    t = await open_ticket_for(request, access, ticket_id)
    return await queue(request, session, access, t, "ticket.transfer",
                       member_id=body.member_id)


@router.post("/tickets/{ticket_id}/escalate", **ACCEPTED)
async def escalate(request: Request, session: Session, access: GuildAccess,
                   ticket_id: TicketId, body: EscalateBody) -> Queued:
    """Bring the ticket to the next escalation level, or to `level`."""
    t = await open_ticket_for(request, access, ticket_id)
    levels = await request.app.state.store.escalation_levels(access.guild_id)
    target = body.level or (t["escalation_level"] or 0) + 1
    if not levels or target > levels[-1]["level"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no such escalation level")
    if target <= (t["escalation_level"] or 0):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The ticket is already at that level or higher")
    return await queue(request, session, access, t, "ticket.escalate", level=target,
                       reason=body.reason)


@router.post("/tickets/{ticket_id}/messages", **ACCEPTED)
async def message(request: Request, session: Session, access: GuildAccess,
                  ticket_id: TicketId, body: TextBody) -> Queued:
    """Answer in the ticket: the bot posts the text with your name and avatar."""
    t = await open_ticket_for(request, access, ticket_id)
    return await queue(request, session, access, t, "ticket.message", text=body.text)


@router.post("/tickets/{ticket_id}/notes", status_code=status.HTTP_201_CREATED,
             response_model=Note)
async def add_note(request: Request, session: Session, access: GuildAccess,
                   ticket_id: TicketId, body: NoteBody) -> Note:
    """A private note for the staff (saved at once, like /note add)."""
    t = await open_ticket_for(request, access, ticket_id)
    now = time.time()
    store = request.app.state.store
    await store.add_note(t["id"], session["user_id"], body.text, now)
    await store.audit(access.guild_id, session["user_id"], "ticket.note", source="web",
                      target=f"ticket:{t['id']}", ip=client_ip(request))
    return Note(author_id=str(session["user_id"]), text=body.text, created_at=now)


@router.get("/commands/{command_id}", response_model=CommandStatus)
async def command_status(request: Request, session: Session, access: GuildAccess,
                         command_id: Annotated[int, Path(ge=1)]) -> CommandStatus:
    """How a queued action went: pending → running → done or failed (with the reason)."""
    c = await request.app.state.store.get_command(command_id)
    if c is None or c["guild_id"] != access.guild_id or \
            (c["requested_by"] != session["user_id"] and not access.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Command not found")
    return CommandStatus(id=c["id"], kind=c["kind"], status=c["status"],
                         result=c["result"], created_at=c["created_at"],
                         finished_at=c["finished_at"])
