"""Prometheus metrics (Beta4)."""

import asyncio
import time

import pytest
from conftest import new_store
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from test_web import make_settings
from test_web_api import GUILD, seed

from ticketbot.web.app import create_app

TOKEN = "a-long-random-token-for-the-tests-1234"


@pytest.fixture
def metrics(tmp_path):
    asyncio.run(seed(tmp_path / "ticketbot.db"))
    settings = make_settings(tmp_path, metrics_token=TOKEN)
    with TestClient(create_app(settings)) as c:
        c.db_path = tmp_path / "ticketbot.db"
        yield c


def scrape(c) -> dict:
    """{(name, labels...): value}"""
    r = c.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    values = {}
    for family in text_string_to_metric_families(r.text):
        for sample in family.samples:
            values[(sample.name, *sorted(sample.labels.items()))] = sample.value
    return values


def test_metrics_need_the_token(metrics, tmp_path):
    assert metrics.get("/metrics").status_code == 401
    r = metrics.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert metrics.get("/metrics", headers={"Authorization": TOKEN}).status_code == 401
    with TestClient(create_app(make_settings(tmp_path))) as off:   # no METRICS_TOKEN
        assert off.get("/metrics").status_code == 404


def test_ticket_metrics(metrics):
    values = scrape(metrics)
    g = ("guild", str(GUILD))
    open_total = sum(v for k, v in values.items() if k[0] == "ticketbot_open_tickets")
    assert open_total == 4                       # the seed: tickets 1-4 open, 5 closed
    assert values[("ticketbot_bot_up",)] == 0    # no heartbeat yet
    assert ("ticketbot_tickets_opened_24h", g) in values
    assert values[("ticketbot_pending_web_actions",)] == 0
    assert ("ticketbot_info", ("version", __import__("ticketbot").__version__)) in values

    async def heartbeat():
        store = await new_store(metrics.db_path)
        await store.save_bot_status(version="3.0.0b4", started_at=time.time() - 60,
                                    heartbeat_at=time.time(), guilds=3, latency=0.05)
        await store.save_bot_status(version="3.0.0b4", started_at=time.time() - 60,
                                    heartbeat_at=time.time(), guilds=4, latency=0.04)
        await store.close()

    asyncio.run(heartbeat())
    values = scrape(metrics)
    assert values[("ticketbot_bot_up",)] == 1
    assert values[("ticketbot_bot_guilds",)] == 4            # one row, updated
    assert values[("ticketbot_bot_latency_seconds",)] == 0.04


def test_requests_are_counted_by_route(metrics):
    metrics.get("/api/v1/health")
    metrics.get(f"/api/v1/guilds/{GUILD}/tickets")           # 401, not logged in
    metrics.get("/some/dashboard/page")
    values = scrape(metrics)
    assert values[("ticketbot_http_requests_total", ("method", "GET"),
                   ("route", "/api/v1/health"), ("status", "200"))] >= 1
    routes = {dict(k[1:]).get("route") for k in values if k[0] == "ticketbot_http_requests_total"}
    assert "/api/v1/guilds/{guild_id}/tickets" in routes      # the template, not the ID
    assert not any(str(GUILD) in (r or "") for r in routes)
    assert "dashboard" in routes
