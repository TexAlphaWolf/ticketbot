"""Login with Discord (OAuth2 authorization code flow with PKCE) and logout."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ...core import crypto
from ..discord_api import DiscordError, avatar_url
from ..sessions import (
    clear_session_cookie,
    client_ip,
    current_session,
    hash_token,
    new_token,
    oauth_cookie,
    session_cookie,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_SECONDS = 600            # the login must be completed within 10 minutes
STATE_CONTEXT = "web.oauth_state"
STATE_PATH = "/api/v1/auth"


def safe_next(value: str | None) -> str:
    """Only a path of this site: never another site (open redirect)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class User(BaseModel):
    id: str                    # a string: Discord IDs don't fit in a JavaScript number
    username: str
    global_name: str | None
    avatar_url: str


class Me(BaseModel):
    user: User
    csrf_token: str
    expires_at: float


@router.get("/login", status_code=status.HTTP_302_FOUND,
            responses={302: {"description": "To the Discord login page"}})
async def login(request: Request, next: str | None = None) -> RedirectResponse:
    """Start the login with Discord; `next` is the page to open afterwards."""
    settings = request.app.state.settings
    if not settings.discord_login:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Login with Discord isn't configured: set DISCORD_CLIENT_ID "
                            "and DISCORD_CLIENT_SECRET in .env")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    sealed = crypto.active().encrypt(json.dumps({
        "state": state, "verifier": verifier, "next": safe_next(next),
        "until": time.time() + STATE_SECONDS}), STATE_CONTEXT)
    response = RedirectResponse(
        request.app.state.discord.authorize_url(state, code_challenge(verifier)),
        status_code=status.HTTP_302_FOUND)
    response.set_cookie(oauth_cookie(settings), sealed, max_age=STATE_SECONDS,
                        path=STATE_PATH, httponly=True, secure=settings.web_https,
                        samesite="lax")
    return response


@router.get("/callback", status_code=status.HTTP_302_FOUND, include_in_schema=False)
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   error: str | None = None, iss: str | None = None) -> RedirectResponse:
    """Discord sends the browser back here after the login."""
    settings, store = request.app.state.settings, request.app.state.store

    def finish(target: str) -> RedirectResponse:
        response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
        response.delete_cookie(oauth_cookie(settings), path=STATE_PATH, httponly=True,
                               secure=settings.web_https, samesite="lax")
        return response

    try:
        saved = json.loads(crypto.active().decrypt(
            request.cookies.get(oauth_cookie(settings), ""), STATE_CONTEXT))
    except (crypto.CryptoError, ValueError, TypeError):
        saved = None
    if saved is None or saved["until"] < time.time():
        return finish("/?login_error=expired")
    if error:                  # e.g. access_denied: the user pressed Cancel
        return finish("/?login_error=" + ("cancelled" if error == "access_denied"
                                           else "discord"))
    # iss (RFC 9207): the answer must come from Discord, not from another login service
    if not code or not state or not hmac.compare_digest(state, saved["state"]) or \
            (iss is not None and iss != "https://discord.com"):
        return finish("/?login_error=invalid")

    discord = request.app.state.discord
    try:
        tokens = await discord.exchange_code(code, saved["verifier"])
        if not {"identify", "guilds"} <= set(tokens.get("scope", "").split()):
            return finish("/?login_error=scope")
        user = await discord.fetch_user(tokens["access_token"])
    except (DiscordError, KeyError):
        return finish("/?login_error=discord")

    now = time.time()
    old = request.cookies.get(session_cookie(settings))
    if old:                    # a new login replaces the session of this browser
        await store.delete_web_session(hash_token(old))
    token = new_token()
    user_id = int(user["id"])
    await store.create_web_session(
        id=hash_token(token), user_id=user_id, username=user["username"],
        global_name=user.get("global_name"), avatar=user.get("avatar"),
        access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token"),
        token_expires_at=now + float(tokens.get("expires_in", 604800)),
        csrf_token=secrets.token_urlsafe(32), ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        created_at=now, last_seen_at=now, expires_at=now + settings.web_session_days * 86400)
    await store.audit(None, user_id, "auth.login", source="web", ip=client_ip(request))
    response = finish(saved["next"])
    set_session_cookie(response, settings, token)
    return response


@router.get("/me", response_model=Me)
async def me(session: Annotated[dict, Depends(current_session)]) -> Me:
    """Who is logged in, and the CSRF token to send in X-CSRF-Token."""
    return Me(user=User(id=str(session["user_id"]), username=session["username"],
                        global_name=session["global_name"],
                        avatar_url=avatar_url(session["user_id"], session["avatar"])),
              csrf_token=session["csrf_token"], expires_at=session["expires_at"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: Annotated[dict, Depends(current_session)]):
    """End this login (needs the X-CSRF-Token header)."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    await end_session(request, session, response)
    return response


async def end_session(request: Request, session: dict, response: Response) -> None:
    store = request.app.state.store
    await store.delete_web_session(session["id"])
    request.app.state.guilds_cache.drop(session["id"])
    try:                       # Discord forgets the token too; not essential
        await request.app.state.discord.revoke(session["access_token"])
    except DiscordError:
        pass
    await store.audit(None, session["user_id"], "auth.logout", source="web",
                      ip=client_ip(request))
    clear_session_cookie(response, request.app.state.settings)
