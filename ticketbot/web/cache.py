"""A tiny in-memory cache with expiry, for answers from Discord (servers, roles,
names): the dashboard asks again at most once a minute."""

import time


class TTLCache:
    def __init__(self, seconds: float, max_items: int = 5000):
        self.seconds, self.max_items = seconds, max_items
        self._data: dict = {}

    def get(self, key):
        found = self._data.get(key)
        if found is None:
            return None
        until, value = found
        if until < time.monotonic():
            del self._data[key]
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
