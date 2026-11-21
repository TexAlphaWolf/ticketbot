"""Web dashboard and API (Beta3): the FastAPI application."""

import asyncio
import base64

import pytest
from conftest import TEST_KEY, new_store
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ticketbot import __version__
from ticketbot.core.settings import Settings, SettingsError
from ticketbot.db import migrate
from ticketbot.db.engine import create_engine
from ticketbot.web.app import create_app
from ticketbot.web.database import open_web_store

KEY = base64.urlsafe_b64encode(TEST_KEY).decode()


def make_settings(tmp_path, **values) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, encryption_key=KEY, **values)


@pytest.fixture
def client(tmp_path):
    async def prepare():          # the bot prepares the database, the web only opens it
        store = await new_store(tmp_path / "ticketbot.db")
        await store.close()

    asyncio.run(prepare())
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__, "database": "ok"}


def test_security_headers(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in r.headers      # not served over HTTPS
    assert "server" not in r.headers or "uvicorn" not in r.headers["server"]

    docs = client.get("/api/docs")
    assert docs.status_code == 200 and "cdn.jsdelivr.net" in \
        docs.headers["content-security-policy"]
    assert client.get("/api/openapi.json").json()["info"]["version"] == __version__


def test_unknown_path_is_a_json_404(client):
    r = client.get("/api/v1/nothing-here")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert r.headers["x-content-type-options"] == "nosniff"


def test_docs_can_be_turned_off_and_hsts_on_https(tmp_path):
    asyncio.run(_prepare(tmp_path))
    settings = make_settings(tmp_path, web_api_docs=False,
                             web_public_url="https://tickets.example.com/")
    assert settings.web_public_url == "https://tickets.example.com" and settings.web_https
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404
        assert "max-age" in c.get("/api/v1/health").headers["strict-transport-security"]


async def _prepare(path):
    store = await new_store(path / "ticketbot.db")
    await store.close()


def test_web_does_not_migrate_the_database(tmp_path):
    settings = make_settings(tmp_path)

    async def scenario():
        with pytest.raises(SettingsError, match="Start the bot first"):
            await open_web_store(settings)                # no database yet
        assert not (tmp_path / "ticketbot.db").exists()   # and none was created

        engine = create_engine(settings.db_url)           # an older schema
        await migrate.upgrade(engine, "0005")
        await engine.dispose()
        with pytest.raises(SettingsError, match="schema 0005, this version needs"):
            await open_web_store(settings)
        assert await _revision(settings) == "0005"        # left as it was

        await _prepare(tmp_path)                          # the bot updates it
        store = await open_web_store(settings)
        await store.close()

    asyncio.run(scenario())


async def _revision(settings):
    engine = create_engine(settings.db_url)
    try:
        return await migrate.current_revision(engine)
    finally:
        await engine.dispose()


def test_web_settings(tmp_path):
    settings = make_settings(tmp_path)
    assert (settings.web_host, settings.web_port, settings.web_public_url) == \
        ("127.0.0.1", 8080, None)
    assert ("WEB_PUBLIC_URL", "not set") in settings.summary()
    for bad in ("tickets.example.com", "ftp://x.com", "https://x.com/dashboard"):
        with pytest.raises(ValidationError, match="address of the dashboard"):
            make_settings(tmp_path, web_public_url=bad)
    with pytest.raises(ValidationError):
        make_settings(tmp_path, web_port=70000)


def test_port_in_use_is_reported_before_starting():
    import socket

    from ticketbot.web.app import _check_port

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        with pytest.raises(SettingsError, match=f"WEB_PORT={port + 1}"):
            _check_port("127.0.0.1", port)
    _check_port("127.0.0.1", port)          # free again
