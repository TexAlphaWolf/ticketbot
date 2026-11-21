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


# ------------------------------------------------------- login with Discord ---

class FakeDiscord:
    """Stands in for discord_api.DiscordOAuth: no network in the tests."""

    def __init__(self, scope="identify guilds"):
        self.scope, self.codes, self.revoked = scope, [], []

    def authorize_url(self, state, challenge):
        return f"https://discord.test/authorize?state={state}&code_challenge={challenge}"

    async def exchange_code(self, code, verifier):
        self.codes.append((code, verifier))
        return {"access_token": "discord-access-" + code, "refresh_token": "r",
                "expires_in": 604800, "scope": self.scope}

    async def fetch_user(self, token):
        return {"id": "123456789012345678", "username": "tex", "global_name": "Tex",
                "avatar": None}

    async def revoke(self, token):
        self.revoked.append(token)

    async def close(self):
        pass


@pytest.fixture
def web(tmp_path):
    asyncio.run(_prepare(tmp_path))
    settings = make_settings(tmp_path, discord_client_id="42",
                             discord_client_secret="s3cret")
    with TestClient(create_app(settings), follow_redirects=False) as c:
        c.app.state.discord = FakeDiscord()
        c.db_path = tmp_path / "ticketbot.db"
        yield c


def log_in(c, next_page=None):
    r = c.get("/api/v1/auth/login", params={"next": next_page} if next_page else None)
    assert r.status_code == 302
    state = r.headers["location"].split("state=")[1].split("&")[0]
    return c.get("/api/v1/auth/callback", params={"code": "abc", "state": state})


def test_login_flow(web):
    from urllib.parse import parse_qs, urlparse

    from ticketbot.web.api.auth import code_challenge

    assert web.get("/api/v1/auth/me").status_code == 401
    r = web.get("/api/v1/auth/login", params={"next": "/tickets"})
    query = parse_qs(urlparse(r.headers["location"]).query)
    cookie = r.headers["set-cookie"]
    assert "tb_oauth=" in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
    assert "samesite=lax" in cookie.lower()

    r = web.get("/api/v1/auth/callback", params={"code": "abc", "state": query["state"][0]})
    assert r.status_code == 302 and r.headers["location"] == "/tickets"
    session_cookie = next(h for h in r.headers.get_list("set-cookie")
                          if h.startswith("tb_session="))
    assert "HttpOnly" in session_cookie and "Path=/" in session_cookie
    code, verifier = web.app.state.discord.codes[0]
    assert code == "abc" and code_challenge(verifier) == query["code_challenge"][0]

    me = web.get("/api/v1/auth/me").json()
    assert me["user"] == {"id": "123456789012345678", "username": "tex",
                          "global_name": "Tex", "avatar_url": me["user"]["avatar_url"]}
    assert me["user"]["avatar_url"].startswith("https://cdn.discordapp.com/embed/avatars/")
    assert len(me["csrf_token"]) > 30
    assert "Logged in as <strong>Tex</strong>" in web.get("/").text

    # The database keeps only the hash of the cookie, and the Discord token encrypted
    token = web.cookies["tb_session"]
    rows = raw(web.db_path, "SELECT id, access_token, csrf_token FROM web_sessions")
    assert rows[0][0] != token and len(rows[0][0]) == 64
    assert rows[0][1].startswith("enc:v1:") and rows[0][2].startswith("enc:v1:")
    actions = raw(web.db_path, "SELECT action, source, actor_id FROM audit_log")
    assert actions == [("auth.login", "web", 123456789012345678)]

    # Logging out needs the CSRF token and the same site
    assert web.post("/api/v1/auth/logout").status_code == 403
    assert web.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code \
        == 403
    assert web.post("/api/v1/auth/logout", headers={
        "X-CSRF-Token": me["csrf_token"], "Origin": "https://evil.example"}).status_code == 403
    r = web.post("/api/v1/auth/logout", headers={"X-CSRF-Token": me["csrf_token"],
                                                 "Origin": "http://testserver"})
    assert r.status_code == 204
    assert web.app.state.discord.revoked == ["discord-access-abc"]
    assert web.get("/api/v1/auth/me").status_code == 401
    assert raw(web.db_path, "SELECT COUNT(*) FROM web_sessions") == [(0,)]


def raw(path, sql):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_login_errors(web):
    def callback(**params):
        return web.get("/api/v1/auth/callback", params=params).headers["location"]

    assert callback(code="x", state="y") == "/?login_error=expired"     # no login started
    web.get("/api/v1/auth/login")
    assert callback(code="x", state="forged") == "/?login_error=invalid"
    web.get("/api/v1/auth/login")
    assert callback(error="access_denied") == "/?login_error=cancelled"
    web.app.state.discord = FakeDiscord(scope="identify")
    assert log_in(web).headers["location"] == "/?login_error=scope"
    assert web.get("/api/v1/auth/me").status_code == 401
    assert "didn&#x27;t grant" in web.get("/?login_error=scope").text


def test_only_local_pages_after_login(web):
    from ticketbot.web.api.auth import safe_next

    for bad in ("https://evil.example", "//evil.example", "/\\evil.example", "", None):
        assert safe_next(bad) == "/"
    assert log_in(web, "//evil.example/x").headers["location"] == "/"


def test_expired_session_and_form_logout(web):
    log_in(web)
    raw_update(web.db_path, "UPDATE web_sessions SET expires_at = 1")
    assert web.get("/api/v1/auth/me").status_code == 401
    assert raw(web.db_path, "SELECT COUNT(*) FROM web_sessions") == [(0,)]

    log_in(web)
    csrf = web.get("/api/v1/auth/me").json()["csrf_token"]
    assert web.post("/logout", data={"csrf_token": "wrong"}).status_code == 403
    r = web.post("/logout", data={"csrf_token": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert web.get("/api/v1/auth/me").status_code == 401


def raw_update(path, sql):
    import sqlite3
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(sql)
    conn.close()


def test_login_not_configured(client):
    r = client.get("/api/v1/auth/login", follow_redirects=False)
    assert r.status_code == 503 and "DISCORD_CLIENT_ID" in r.json()["detail"]
    assert "isn't configured" in client.get("/").text


def test_https_cookies(tmp_path):
    asyncio.run(_prepare(tmp_path))
    settings = make_settings(tmp_path, discord_client_id="42", discord_client_secret="s",
                             web_public_url="https://tickets.example.com")
    assert settings.oauth_redirect_uri == \
        "https://tickets.example.com/api/v1/auth/callback"
    with TestClient(create_app(settings), base_url="https://tickets.example.com",
                    follow_redirects=False) as c:
        c.app.state.discord = FakeDiscord()
        r = log_in(c)
        cookies = r.headers.get_list("set-cookie")
        session = next(h for h in cookies if h.startswith("__Host-tb_session="))
        assert "Secure" in session and "Path=/" in session and "Domain" not in session
        assert c.get("/api/v1/auth/me").status_code == 200
