"""The home page when the React dashboard isn't built: it says how to build it, and
still lets you log in and out (a form, no JavaScript). When it is built, / is the
dashboard (spa.py)."""

import hmac
import html
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__
from .api.auth import end_session
from .sessions import check_origin, read_session
from .spa import built, index

router = APIRouter(include_in_schema=False)

ERRORS = {
    "cancelled": "The login was cancelled.",
    "expired": "The login took too long or was started in another browser: try again.",
    "invalid": "The login answer from Discord wasn't valid: try again.",
    "scope": "Discord didn't grant the permissions the dashboard needs.",
    "discord": "Discord couldn't be reached or refused the login: try again later.",
}


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, login_error: str | None = None):
    if built(request.app.state.static_dir):
        return index(request.app.state.static_dir)
    session = await read_session(request)
    parts = [f"<h1>TicketBot {html.escape(__version__)}</h1>",
             "<p>The web dashboard isn't built yet: in the <code>frontend</code> folder run "
             "<code>npm ci</code> and <code>npm run build</code>, then restart "
             "<code>python -m ticketbot web</code>. The API is documented at "
             '<a href="/api/docs">/api/docs</a>.</p>']
    if login_error:
        parts.append(f"<p><strong>{html.escape(ERRORS.get(login_error, 'Login failed.'))}"
                     "</strong></p>")
    if session:
        name = session["global_name"] or session["username"]
        parts.append(f"<p>Logged in as <strong>{html.escape(name)}</strong> "
                     f"(@{html.escape(session['username'])}). "
                     '<a href="/api/v1/auth/me">/api/v1/auth/me</a></p>')
        parts.append('<form method="post" action="/logout">'
                     f'<input type="hidden" name="csrf_token" '
                     f'value="{html.escape(session["csrf_token"])}">'
                     '<button type="submit">Log out</button></form>')
    elif request.app.state.settings.discord_login:
        parts.append('<p><a href="/api/v1/auth/login">Log in with Discord</a></p>')
    else:
        parts.append("<p>Login with Discord isn't configured yet: set DISCORD_CLIENT_ID "
                     "and DISCORD_CLIENT_SECRET in .env.</p>")
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>TicketBot</title></head><body>{''.join(parts)}</body></html>")
    return HTMLResponse(page)


@router.post("/logout")
async def logout_form(request: Request) -> RedirectResponse:
    """The Log out button of the page above (the API has POST /api/v1/auth/logout)."""
    check_origin(request)
    session = await read_session(request)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    if session is None:
        return response
    form = parse_qs((await request.body())[:2048].decode(errors="replace"))
    sent = form.get("csrf_token", [""])[0]
    if not hmac.compare_digest(sent.encode(), session["csrf_token"].encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or wrong CSRF token")
    await end_session(request, session, response)
    return response
