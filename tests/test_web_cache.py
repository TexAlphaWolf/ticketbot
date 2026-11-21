"""Answers from Discord: one request for many pages at once, and short rate limits."""

import asyncio
import time

import pytest

from ticketbot.web import discord_api
from ticketbot.web.cache import TTLCache
from ticketbot.web.discord_api import DiscordError, DiscordOAuth


def test_requests_together_ask_discord_once():
    calls = []

    async def load():
        calls.append(1)
        await asyncio.sleep(0.05)
        return {"servers": 1}

    async def scenario():
        cache = TTLCache(60)
        results = await asyncio.gather(*(cache.fetch("s", load) for _ in range(5)))
        assert results == [{"servers": 1}] * 5 and len(calls) == 1
        assert cache._locks == {}                    # nothing left behind
        assert await cache.fetch("s", load) == {"servers": 1} and len(calls) == 1

    asyncio.run(scenario())


def test_an_expired_answer_is_better_than_an_error():
    async def fail():
        raise DiscordError("GET /users/@me/guilds: HTTP 429", 429)

    async def scenario():
        cache = TTLCache(60, stale_seconds=600)
        cache.set("s", "old")
        until, value = cache._data["s"]
        cache._data["s"] = (until - 120, value)      # expired two minutes ago
        assert cache.get("s") is None
        assert await cache.fetch("s", fail) == "old"
        cache._data["s"] = (time.monotonic() - 700, value)   # too old to use
        with pytest.raises(DiscordError):
            await cache.fetch("s", fail)
        assert "s" not in cache._data

    asyncio.run(scenario())


class Response:
    def __init__(self, status, body=None, headers=None):
        self.status, self.headers = status, headers or {}
        self.body = {} if body is None else body
        self.content_type = "application/json"

    async def json(self):
        return self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Http:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        return self.answers.pop(0)


@pytest.mark.parametrize(("answers", "result", "calls"), [
    ([Response(429, {"retry_after": 0.01}), Response(200, [{"id": "1"}])], [{"id": "1"}], 2),
    ([Response(429, headers={"Retry-After": "0"}), Response(200, [])], [], 2),
    ([Response(429, {"retry_after": 60}), Response(200, [])], 429, 1),     # too long
    ([Response(429, {"retry_after": 0})] * 3, 429, 3),                      # gives up
])
def test_short_rate_limits_are_waited(monkeypatch, answers, result, calls):
    waited = []
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        waited.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(discord_api.asyncio, "sleep", sleep)
    oauth = DiscordOAuth.__new__(DiscordOAuth)
    http = Http(answers)
    oauth._http = lambda: http

    async def scenario():
        if result == 429:
            with pytest.raises(DiscordError) as e:
                await oauth._call("GET", "/users/@me/guilds")
            assert e.value.status == 429
        else:
            assert await oauth._call("GET", "/users/@me/guilds") == result
        assert http.calls == calls and len(waited) == min(calls - 1, 2)

    asyncio.run(scenario())
