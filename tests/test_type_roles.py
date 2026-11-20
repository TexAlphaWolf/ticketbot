"""Staff roles per ticket type (Beta2)."""

from types import SimpleNamespace

import discord
import pytest

from ticketbot.bot.common import is_ticket_staff, staff_mentions
from ticketbot.core.i18n import DEFAULT_TYPES


def test_type_roles_storage(db):
    db.save_guild(1, staff_role=5)
    db.ensure_default_types(1, DEFAULT_TYPES["en"])
    assert db.type_roles(1, "bug") == []
    assert db.add_type_role(1, "bug", 30)
    assert db.add_type_role(1, "bug", 20)
    assert not db.add_type_role(1, "bug", 20)          # already there
    db.add_type_role(1, "support", 40)
    assert db.type_roles(1, "bug") == [20, 30]
    assert db.all_type_roles(1) == {"bug": [20, 30], "support": [40]}
    assert db.remove_type_role(1, "bug", 30) and not db.remove_type_role(1, "bug", 30)
    db.remove_type(1, "bug")                            # roles go with the type
    assert db.all_type_roles(1) == {"support": [40]}
    db.delete_guild(1)
    assert db.count("type_staff_roles") == 0


@pytest.fixture
def member_class(monkeypatch):
    class Member(SimpleNamespace):
        pass

    monkeypatch.setattr(discord, "Member", Member)
    return lambda *roles, admin=False: Member(
        roles=[SimpleNamespace(id=r) for r in roles],
        guild_permissions=SimpleNamespace(administrator=admin))


def test_who_is_staff_for_a_ticket(member_class):
    cfg = {"staff_role": 5}
    mod, dev, admin, user = member_class(5), member_class(20), member_class(admin=True), \
        member_class()
    # Type without roles: the staff role
    assert is_ticket_staff(mod, cfg, []) and not is_ticket_staff(dev, cfg, [])
    # Type handled by @Dev (20): only @Dev and the admins
    assert is_ticket_staff(dev, cfg, [20]) and not is_ticket_staff(mod, cfg, [20])
    assert is_ticket_staff(admin, cfg, [20]) and not is_ticket_staff(user, cfg, [20])
    assert not is_ticket_staff(dev, None, [20])


def test_staff_mentions():
    assert staff_mentions({"staff_role": 5}, []) == "<@&5>"
    assert staff_mentions({"staff_role": 5}, [20, 30]) == "<@&20> <@&30>"
    assert staff_mentions({}, []) == ""


def test_no_translation_repeats_itself():
    from ticketbot.core.i18n import STRINGS

    for lang, strings in STRINGS.items():
        for key, text in strings.items():
            half = len(text) // 2
            assert not (len(text) > 20 and text[:half] == text[half:]), (lang, key)
