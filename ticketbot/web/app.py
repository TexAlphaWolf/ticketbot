"""The FastAPI application."""

import asyncio
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .. import __version__
from ..core.settings import Settings, SettingsError
from . import spa
from .api import v1
from .cache import TTLCache
from .database import open_web_store
from .discord_api import DiscordBot
from .home import router as home_router
from .security import DOCS_PATH, SecurityHeaders
from .spa import router as spa_router


def create_app(settings: Settings, static_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = await open_web_store(settings)
        app.state.discord = DiscordBot(settings)
        app.state.guilds_cache = TTLCache(60)        # session → its Discord servers
        app.state.members_cache = TTLCache(60)       # (server, user) → member
        try:
            yield
        finally:
            await app.state.discord.close()
            await app.state.store.close()

    app = FastAPI(title="TicketBot", version=__version__, lifespan=lifespan,
                  docs_url=DOCS_PATH if settings.web_api_docs else None,
                  redoc_url=None,
                  openapi_url="/api/openapi.json" if settings.web_api_docs else None)
    app.add_middleware(SecurityHeaders, hsts=settings.web_https)
    app.include_router(v1.router)
    app.include_router(home_router)
    app.include_router(spa_router)       # last: every other path is a dashboard page
    app.state.static_dir = static_dir or spa.DEFAULT_DIR

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        # The same JSON shape for every error, also for unknown paths
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    return app


async def _check_database(settings: Settings) -> None:
    store = await open_web_store(settings)
    await store.close()


def _check_port(host: str, port: int) -> None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            raise SettingsError(
                f"{host}:{port} is already used by another program. Close it, or choose "
                f"another port in .env, e.g. WEB_PORT={port + 1}") from None


def wait_for_database(settings: Settings, wait: float, *, sleep=time.sleep,
                      clock=time.monotonic) -> None:
    """Check the database; with `wait` > 0 try again for that many seconds while it isn't
    ready (Docker: the bot updates it at start, PostgreSQL may still be starting)."""
    until = clock() + wait
    said = False
    while True:
        try:
            asyncio.run(_check_database(settings))
            return
        except Exception as e:
            if clock() >= until:
                if isinstance(e, SettingsError):
                    raise
                raise SettingsError(f"The database can't be reached: {e}") from None
            if not said:
                print(f"[web] waiting for the database (up to {wait:.0f}s): {e}")
                said = True
            sleep(3)


def run(settings: Settings, wait: float = 0) -> None:
    """Start the web server. Raises SettingsError before starting if the database isn't
    ready, so the message isn't buried in a traceback."""
    import uvicorn

    wait_for_database(settings, wait)
    _check_port(settings.web_host, settings.web_port)
    print(f"[web] http://{settings.web_host}:{settings.web_port}"
          + (f" (public: {settings.web_public_url})" if settings.web_public_url else ""))
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(
        app, host=settings.web_host, port=settings.web_port, proxy_headers=True,
        forwarded_allow_ips=settings.web_trusted_proxies, server_header=False,
        log_level="info", timeout_graceful_shutdown=5))
    app.state.server = server          # live connections end when it's stopping
    server.run()
