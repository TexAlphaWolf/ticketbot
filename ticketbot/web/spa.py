"""The React dashboard: the files built by `npm run build` (frontend/ → web/static).

Every page of the dashboard is the same index.html; React shows the right page from the
address. Hashed files in /assets never change, so browsers may keep them for a year.
When the dashboard isn't built, home.py shows a small page that says how to build it.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

DEFAULT_DIR = Path(__file__).parent / "static"

router = APIRouter(include_in_schema=False)


def built(static_dir: Path) -> bool:
    return (static_dir / "index.html").is_file()


def index(static_dir: Path) -> FileResponse:
    return FileResponse(static_dir / "index.html", media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@router.get("/{path:path}")
async def page(request: Request, path: str):
    static_dir: Path = request.app.state.static_dir
    if path.startswith("api/") or path == "api" or not built(static_dir):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    root = static_dir.resolve()
    target = (static_dir / path).resolve()
    if path and target.is_file() and target.is_relative_to(root):
        headers = ({"Cache-Control": "public, max-age=31536000, immutable"}
                   if path.startswith("assets/") else {"Cache-Control": "no-cache"})
        return FileResponse(target, headers=headers)
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")   # a missing file
    return index(static_dir)
