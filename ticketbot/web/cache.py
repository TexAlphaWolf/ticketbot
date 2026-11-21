"""A tiny in-memory cache with expiry, for answers from Discord (servers, roles,
names): the dashboard asks again at most once a minute."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class TTLCache:
    def __init__(self, seconds: float, max_items: int = 5000, stale_seconds: float = 600):
        self.seconds, self.max_items, self.stale_seconds = seconds, max_items, stale_seconds
        self._data: dict = {}
        self._locks: dict = {}

    def get(self, key, *, stale: bool = False):
        """The value if it is still fresh; with stale=True also an expired one, for a
        while (better than an error when Discord can't answer)."""
        found = self._data.get(key)
        if found is None:
            return None
        until, value = found
        now = time.monotonic()
        if until < now:
            if until + self.stale_seconds < now:
                del self._data[key]
                return None
            if not stale:
                return None
        return value

    def set(self, key, value) -> None:
        if len(self._data) >= self.max_items:
            now = time.monotonic()
            self._data = {k: v for k, v in self._data.items() if v[0] >= now}
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic() + self.seconds, value)

    def drop(self, key) -> None:
        self._data.pop(key, None)

    async def fetch(self, key, load: Callable[[], Awaitable]):
        """The cached value, or load it. Requests arriving together for the same key
        wait for one load instead of each asking Discord (which answers 429 to bursts).
        If the load fails, a recently expired value is used instead, when there is one."""
        found = self.get(key)
        if found is not None:
            return found
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                found = self.get(key)               # loaded while we were waiting
                if found is not None:
                    return found
                try:
                    found = await load()
                except Exception:
                    old = self.get(key, stale=True)
                    if old is not None:
                        return old
                    raise
                self.set(key, found)
                return found
        finally:
            if not lock.locked() and self._locks.get(key) is lock:
                del self._locks[key]
