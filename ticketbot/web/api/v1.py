"""REST API, version 1: /api/v1/... (used by the dashboard and, later, other apps)."""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from ... import __version__
from . import actions, auth, guilds

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(guilds.router)
router.include_router(actions.router)


class Health(BaseModel):
    status: str
    version: str
    database: str


@router.get("/health", response_model=Health, tags=["system"])
async def health(request: Request, response: Response) -> Health:
    """Whether the web API and its database work (for monitoring and Docker)."""
    try:
        async with request.app.state.store.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(status="ok" if database == "ok" else "error", version=__version__,
                  database=database)
