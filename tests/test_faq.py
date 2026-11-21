"""FAQ shown before the ticket form (Beta2)."""

from ticketbot.core.i18n import DEFAULT_TYPES


def test_faq_storage(db):
    db.save_guild(1)
    db.ensure_default_types(1, DEFAULT_TYPES["en"])
    general = db.add_faq(1, None, "How do I reset my password?", "Use /reset.")
    bug = db.add_faq(1, "bug", "The game crashes", "Update the drivers.")
    db.add_faq(1, "support", "Refunds", "Within 14 days.")
    assert [e["id"] for e in db.list_faq(1)] == [general, bug, bug + 1]

    # The entries of the type first, then the general ones; never other types
    assert [e["id"] for e in db.faq_for_type(1, "bug", 5)] == [bug, general]
    assert [e["id"] for e in db.faq_for_type(1, "bug", 1)] == [bug]
    assert [e["question"] for e in db.faq_for_type(1, "other", 5)] == [
        "How do I reset my password?"]

    assert db.update_faq(1, bug, "The game crashes at start", "Update the drivers.")
    assert db.get_faq(1, bug)["question"] == "The game crashes at start"
    assert not db.update_faq(2, bug, "x", "y")             # another server's entry
    assert db.get_faq(2, bug) is None

    db.remove_type(1, "bug")                                # its entries go with it
    assert [e["id"] for e in db.list_faq(1)] == [general, bug + 1]
    assert db.remove_faq(1, general) and not db.remove_faq(1, general)
    db.delete_guild(1)
    assert db.count("faq_entries") == 0


def test_faq_results(db):
    db.save_guild(1)
    for solved, when in ((True, 100.0), (True, 200.0), (False, 300.0), (True, 50.0)):
        db.record_faq_result(1, "bug", solved, now=when)
    assert db.faq_results_since(1, 0) == {"solved": 3, "opened": 1}
    assert db.faq_results_since(1, 150) == {"solved": 1, "opened": 1}
    assert db.faq_results_since(2, 0) == {"solved": 0, "opened": 0}
    assert db.purge_faq_results_before(150) == 2
    assert db.faq_results_since(1, 0) == {"solved": 1, "opened": 1}
    db.delete_guild(1)
    assert db.count("faq_results") == 0
