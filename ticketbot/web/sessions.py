"""Login sessions of the web dashboard: cookies, the current user and CSRF protection.

The session cookie holds a random token; the database keeps only its SHA-256. It is
HttpOnly (scripts can't read it), SameSite=Lax and, over HTTPS, Secure with the
__Host- prefix. Requests that change something must also send the session's CSRF token
in the X-CSRF-Token header (the dashboard reads it from /api/v1/auth/me), and a foreign
Origin is refused.
"""

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response, status

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOUCH_EVERY = 300              # update last_seen_at at most every 5 minutes


def session_cookie(settings) -> str:
    return "__Host-tb_session" if settings.web_https else "tb_session"


def oauth_cookie(settings) -> str:
    return "__Secure-tb_oauth" if settings.web_https else "tb_oauth"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookie(response: Response, settings, token: str) -> None:
    response.set_cookie(session_cookie(settings), token,
                        max_age=settings.web_session_days * 86400, path="/",
                        httponly=True, secure=settings.web_https, samesite="lax")


def clear_session_cookie(response: Response, settings) -> None:
    response.delete_cookie(session_cookie(settings), path="/", httponly=True,
                           secure=settings.web_https, samesite="lax")


async def read_session(request: Request) -> dict | None:
    """The valid session of this browser, or None."""
    settings, store = request.app.state.settings, request.app.state.store
    token = request.cookies.get(session_cookie(settings))
    if not token:
        return None
    session = await store.get_web_session(hash_token(token))
    now = time.time()
    if session is None:
        return None
    if session["expires_at"] <= now:
        await store.delete_web_session(session["id"])
        return None
    if now - session["last_seen_at"] > TOUCH_EVERY:
        await store.update_web_session(session["id"], last_seen_at=now)
    return session


async def current_session(request: Request) -> dict:
    """Dependency: the logged-in session; 401 if there is none. On requests that change
    something it also checks the Origin and the CSRF token."""
    session = await read_session(request)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    if request.method not in SAFE_METHODS:
        check_origin(request)
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), session["csrf_token"].encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or wrong CSRF token")
    return session


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return
    allowed = {request.app.state.settings.web_base_url,
               str(request.base_url).rstrip("/")}
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request from another site")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def discord_token(request: Request, session: dict) -> str:
    """The session's Discord access token, renewed when it is about to expire. If Discord
    refuses to renew it, the login ends (401)."""
    if session["token_expires_at"] - time.time() > 300:
        return session["access_token"]
    from .discord_api import DiscordError

    store = request.app.state.store
    try:
        if not session["refresh_token"]:
            raise DiscordError("no refresh token", 400)
        tokens = await request.app.state.discord.refresh(session["refresh_token"])
        values = {"access_token": tokens["access_token"],
                  "refresh_token": tokens.get("refresh_token") or session["refresh_token"],
                  "token_expires_at": time.time() + float(tokens.get("expires_in", 604800))}
    except (DiscordError, KeyError) as e:
        if getattr(e, "status", 400) in (400, 401):
            await store.delete_web_session(session["id"])
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "The Discord login expired: log in again") from None
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Discord can't be reached") from None
    await store.update_web_session(session["id"], **values)
    session.update(values)
    return session["access_token"]
