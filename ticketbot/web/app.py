"""The FastAPI application."""

import asyncio
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .. import __version__
from ..core.settings import Settings, SettingsError
from .api import v1
from .database import open_web_store
from .security import DOCS_PATH, SecurityHeaders


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = await open_web_store(settings)
        try:
            yield
        finally:
            await app.state.store.close()

    app = FastAPI(title="TicketBot", version=__version__, lifespan=lifespan,
                  docs_url=DOCS_PATH if settings.web_api_docs else None,
                  redoc_url=None,
                  openapi_url="/api/openapi.json" if settings.web_api_docs else None)
    app.add_middleware(SecurityHeaders, hsts=settings.web_https)
    app.include_router(v1.router)

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


def run(settings: Settings) -> None:
    """Start the web server. Raises SettingsError before starting if the database isn't
    ready, so the message isn't buried in a traceback."""
    import uvicorn

    asyncio.run(_check_database(settings))
    _check_port(settings.web_host, settings.web_port)
    print(f"[web] http://{settings.web_host}:{settings.web_port}"
          + (f" (public: {settings.web_public_url})" if settings.web_public_url else ""))
    uvicorn.run(create_app(settings), host=settings.web_host, port=settings.web_port,
                proxy_headers=True, forwarded_allow_ips=settings.web_trusted_proxies,
                server_header=False, log_level="info")
