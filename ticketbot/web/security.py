"""HTTP security headers added to every response."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The dashboard loads only its own files; avatars and icons come from Discord's CDN
CSP = ("default-src 'self'; img-src 'self' data: https://cdn.discordapp.com; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
# The API docs page (Swagger UI) loads its script and style from jsDelivr
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: "
            "https://fastapi.tiangolo.com; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'")
DOCS_PATH = "/api/docs"

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class SecurityHeaders:
    """Pure ASGI middleware (it doesn't buffer the body, so streaming keeps working)."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False):
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = scope["path"] == DOCS_PATH

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", DOCS_CSP if docs else CSP)
                if self.hsts:   # only when the dashboard is served over HTTPS
                    headers.setdefault("Strict-Transport-Security",
                                       "max-age=31536000; includeSubDomains")
                if scope["path"].startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)
