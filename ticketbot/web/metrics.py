"""
Prometheus metrics at /metrics (with METRICS_TOKEN, as a bearer token).

- The tickets of every server: read from the database at each scrape, so they are
  right however many processes there are (bot, web server).
- The bot: alive or not, from its heartbeat in the database (it runs in another
  process), its Discord latency and servers.
- The web server: requests and their duration, counted in this process.

Labels never hold personal data: servers are their IDs, routes their templates (e.g.
/api/v1/guilds/{guild_id}/tickets, not the IDs in them).
"""

import hmac
import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.exposition import generate_latest

from .. import __version__
from ..core import config

router = APIRouter(include_in_schema=False)

# The web server's own metrics: kept between scrapes, in this process
HTTP = CollectorRegistry(auto_describe=True)
REQUESTS = Counter("ticketbot_http_requests", "Requests to the web server",
                   ["method", "route", "status"], registry=HTTP)
DURATION = Histogram("ticketbot_http_request_duration_seconds",
                     "How long the web server took to answer", ["method", "route"],
                     buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
                     registry=HTTP)


def route_of(scope: dict) -> str:
    """The route's template, never the real path (IDs, names): few series, no data."""
    path = getattr(scope.get("route"), "path", None)
    if path is None or path == "/{path:path}":           # dashboard pages, files, 404
        return "/api/other" if scope["path"].startswith("/api/") else "dashboard"
    if scope["path"].startswith("/api/v1/") and not path.startswith("/api/"):
        path = "/api/v1" + path                          # a route of an included router
    return path


class CountRequests:
    """ASGI middleware: counts the requests and how long they took. Plain ASGI, so the
    live streams (Server-Sent Events) pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        code = {"status": 500}

        async def send_status(message):
            if message["type"] == "http.response.start":
                code["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        finally:
            route = route_of(scope)
            if not route.endswith("/events"):            # a live stream, not a request
                REQUESTS.labels(scope["method"], route, str(code["status"])).inc()
                DURATION.labels(scope["method"], route).observe(time.perf_counter() - start)


def gauge(name: str, help_text: str, labels: list[str] | None = None) -> GaugeMetricFamily:
    return GaugeMetricFamily(f"ticketbot_{name}", help_text, labels=labels)


def families(snapshot: dict, now: float) -> list[GaugeMetricFamily]:
    """The metrics from one database snapshot (Store.metrics_snapshot)."""
    info = gauge("info", "TicketBot's version (web server)", ["version"])
    info.add_metric([__version__], 1)

    bot = snapshot["bot"]
    up = gauge("bot_up", "1 if the bot sent a heartbeat in the last "
                         f"{config.BOT_DOWN_AFTER} seconds")
    up.add_metric([], 1 if bot and now - bot["heartbeat_at"] < config.BOT_DOWN_AFTER else 0)
    result = [info, up]
    if bot:
        for name, text, value in (
                ("bot_heartbeat_timestamp_seconds", "Last heartbeat of the bot",
                 bot["heartbeat_at"]),
                ("bot_start_time_seconds", "When the bot started", bot["started_at"]),
                ("bot_guilds", "Servers the bot is in", bot["guilds"]),
                ("bot_latency_seconds", "The bot's latency to Discord", bot["latency"])):
            if value is not None:
                metric = gauge(name, text)
                metric.add_metric([], value)
                result.append(metric)
        bot_info = gauge("bot_info", "The bot's version", ["version"])
        bot_info.add_metric([bot["version"]], 1)
        result.append(bot_info)

    open_tickets = gauge("open_tickets", "Open tickets", ["guild", "status", "priority"])
    for row in snapshot["open"]:
        open_tickets.add_metric([str(row["guild_id"]), row["status"],
                                 row["priority"] or "none"], row["n"])
    result.append(open_tickets)

    per_guild = {
        "tickets_opened_24h": ("Tickets opened in the last 24 hours", "opened_24h"),
        "tickets_closed_24h": ("Tickets closed in the last 24 hours", "closed_24h"),
        "first_response_seconds_7d": ("Average time to the first staff answer, tickets "
                                      "opened in the last 7 days", "first_response_7d"),
        "resolution_seconds_7d": ("Average time to close, tickets closed in the last "
                                  "7 days", "resolution_7d"),
        "rating_30d": ("Average rating (1-5), tickets closed in the last 30 days",
                       "rating_30d"),
        "escalated_open_tickets": ("Open tickets escalated to a higher level",
                                   "escalated"),
    }
    for name, (text, key) in per_guild.items():
        metric = gauge(name, text, ["guild"])
        for row in snapshot["guilds"]:
            if row[key] is not None:
                metric.add_metric([str(row["guild_id"])], float(row[key]))
        result.append(metric)
    waiting = gauge("oldest_waiting_seconds",
                    "How long the open ticket waiting longest for the staff has waited",
                    ["guild"])
    for row in snapshot["guilds"]:
        waiting.add_metric([str(row["guild_id"])],
                           max(0.0, now - row["oldest_waiting"])
                           if row["oldest_waiting"] else 0.0)
    result.append(waiting)

    for name, text, key in (
            ("pending_web_actions", "Dashboard actions waiting for the bot",
             "pending_commands"),
            ("web_sessions", "Active dashboard logins", "web_sessions"),
            ("telegram_accounts", "Telegram accounts linked to answer tickets",
             "telegram_accounts")):
        metric = gauge(name, text)
        metric.add_metric([], snapshot[key] or 0)
        result.append(metric)
    return result


class Snapshot:
    """A collector for one scrape (prometheus_client collectors are synchronous; the
    database is read before, asynchronously)."""

    def __init__(self, metrics: list[GaugeMetricFamily]):
        self.metrics = metrics

    def collect(self):
        return self.metrics


def check_token(request: Request) -> None:
    expected = request.app.state.settings.metrics_token
    if expected is None:                          # metrics are off: nothing here
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
            token.strip().encode(), expected.get_secret_value().strip().encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid METRICS_TOKEN is needed",
                            headers={"WWW-Authenticate": "Bearer"})


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    check_token(request)
    now = time.time()
    registry = CollectorRegistry(auto_describe=False)
    registry.register(Snapshot(families(
        await request.app.state.store.metrics_snapshot(now), now)))
    body = generate_latest(registry) + generate_latest(HTTP)
    return Response(body, media_type=CONTENT_TYPE_LATEST,
                    headers={"Cache-Control": "no-store"})
