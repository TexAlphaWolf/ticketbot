"""Search and filters of the ticket list (dashboard)."""

import asyncio

from conftest import new_store
from test_web_api import ADMIN, GUILD, MEMBER, STAFF, api, as_user  # noqa: F401

from ticketbot.db import store as store_module

BASE = f"/api/v1/guilds/{GUILD}/tickets"


def test_search_in_the_store(tmp_path, monkeypatch):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        for n in range(1, 31):
            await store.create_ticket(
                guild_id=1, number=n, name=f"bug-user{n}-1", owner_id=100 + n % 3,
                type_key="bug", type_label="Bug report", type_emoji="x",
                subject="Refund please" if n % 10 == 0 else f"Crash {n}",
                description="Invoice 4711" if n == 7 else "", opened_at=float(n),
                last_activity=float(n))

        async def ids(**kw):
            rows, nxt = await store.list_tickets(1, status="all", **kw)
            return [r["number"] for r in rows], nxt

        assert await ids(text="refund") == ([30, 20, 10], None)     # in the subject
        assert await ids(text="INVOICE 4711") == ([7], None)        # in the answers
        assert await ids(text="#12") == ([12], None)
        assert await ids(text="12") == ([12], None)
        assert await ids(text="user25") == ([25], None)             # channel name
        assert await ids(text="nothing like this") == ([], None)
        assert await ids(text="crash", limit=3) == ([29, 28, 27], 27)
        assert await ids(text="crash", limit=3, before_id=27) == ([26, 25, 24], 24)
        assert (await ids(person=100))[0] == [30, 27, 24, 21, 18, 15, 12, 9, 6, 3]
        assert (await ids(opened_from=5, opened_to=8))[0] == [7, 6, 5]
        assert (await ids(priority="none"))[0][:2] == [30, 29]
        assert (await ids(priority="high"))[0] == []

        monkeypatch.setattr(store_module, "SEARCH_SCAN", 5)     # 5 decrypted per page
        assert await ids(text="refund") == ([30], 26)
        assert await ids(text="refund", before_id=26) == ([], 21)   # nothing yet: go on
        assert await ids(text="refund", before_id=21) == ([20], 16)
        await store.close()

    asyncio.run(scenario())


def test_search_in_the_api(api):  # noqa: F811
    as_user(api, ADMIN, owner=True)

    def numbers(**params):
        r = api.get(BASE, params={"status": "all", **params})
        assert r.status_code == 200, r.text
        return [t["number"] for t in r.json()["tickets"]]

    assert numbers(q="subject 3") == [3]
    assert numbers(q="answers") == [5, 4, 3, 2, 1]
    assert numbers(q="#2") == [2]
    assert numbers(q=str(MEMBER)) == [MEMBER]           # short numbers are ticket numbers
    assert numbers(person=str(STAFF)) == [4]
    assert numbers(priority="none") == [5, 4, 3, 2, 1]
    assert api.get(BASE, params={"priority": "urgent"}).status_code == 422
    assert api.get(BASE, params={"person": "abc"}).status_code == 422
    assert numbers(**{"from": 0, "to": 1}) == []
