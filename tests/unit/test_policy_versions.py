"""Which clause of a new version continues which clause of the version before it.

The story is the one the integration tests tell: version 2 inserts a contractor rule at 4.2, so
the staff rule is printed as 4.3 and the supplier rule as 4.4.
"""

from __future__ import annotations

import uuid

from dpolens.engine.policies.checks import snippet
from dpolens.engine.policies.versions import MOVED_SIMILARITY, Earlier, Later, match

CUSTOMER = "Customer records are kept for 2 years after the account closes."
STAFF = "Staff records are kept for 6 years after employment ends."
SUPPLIER = "Supplier records are kept for 5 years after the contract ends."
CONTRACTOR = "Contractor records are kept for 1 year after the contract ends."
BACKUPS = "Backups are encrypted and kept in a second region."


def before(key: str, text: str) -> Earlier:
    return Earlier(id=uuid.uuid4(), key=key, label=None, heading=None, text=text)


def after(key: str, text: str) -> Later:
    return Later(key=key, label=None, heading=None, text=text)


VERSION_1 = [before("r:4.1", CUSTOMER), before("r:4.2", STAFF), before("r:4.3", SUPPLIER)]


def test_an_inserted_clause_moves_the_rules_after_it() -> None:
    matching = match(
        VERSION_1,
        [
            after("r:4.1", CUSTOMER),
            after("r:4.2", CONTRACTOR),
            after("r:4.3", STAFF),
            after("r:4.4", SUPPLIER.replace("5 years", "6 years")),
        ],
    )

    changes = {key: found.change for key, found in matching.matches.items()}
    assert changes == {"r:4.1": "unchanged", "r:4.2": "added", "r:4.3": "moved", "r:4.4": "moved"}
    continues = {key: found.earlier.key for key, found in matching.matches.items() if found.earlier}
    assert continues == {"r:4.1": "r:4.1", "r:4.3": "r:4.2", "r:4.4": "r:4.3"}
    assert matching.removed == []


def test_a_number_that_names_another_rule_now_says_where_that_rule_went() -> None:
    matching = match(
        VERSION_1, [after("r:4.1", CUSTOMER), after("r:4.2", BACKUPS), after("r:4.3", STAFF)]
    )

    assert matching.matches["r:4.2"].change == "added"
    named, went = matching.reused["r:4.2"]
    assert (named.key, went) == ("r:4.2", "r:4.3")
    named, went = matching.reused["r:4.3"]
    assert (named.key, went) == ("r:4.3", None)
    assert [gone.key for gone in matching.removed] == ["r:4.3"]


def test_formulaic_words_under_the_same_number_are_a_match_to_be_checked() -> None:
    """Two rows of a retention schedule share most of their words, so a match like this one is
    kept, and its score is what tells the reviewer to look."""
    matching = match(VERSION_1[:2], [after("r:4.1", CUSTOMER), after("r:4.2", CONTRACTOR)])

    found = matching.matches["r:4.2"]
    assert found.change == "modified"
    assert found.score < MOVED_SIMILARITY


def test_new_words_under_the_same_number_are_the_same_rule_reworded() -> None:
    matching = match(
        [before("r:5.1", "This policy is reviewed every year.")],
        [after("r:5.1", "This policy is reviewed every two years.")],
    )

    assert matching.matches["r:5.1"].change == "modified"
    assert matching.reused == {}
    assert matching.matches["r:5.1"].score > 0.5


def test_under_another_number_a_rule_needs_nearly_the_same_words() -> None:
    matching = match(
        [before("r:4.2", STAFF)],
        [after("r:4.3", "Backups are encrypted and kept in a second region.")],
    )

    assert matching.matches["r:4.3"].change == "added"
    assert [gone.key for gone in matching.removed] == ["r:4.2"]


def test_a_rule_that_stays_put_is_preferred_to_an_identical_one_elsewhere() -> None:
    same = "Requests are answered within one month."
    matching = match(
        [before("r:1", same), before("r:2", same)],
        [after("r:2", same)],
    )

    found = matching.matches["r:2"]
    assert found.change == "unchanged"
    assert found.earlier is not None and found.earlier.key == "r:2"


def test_a_flag_quotes_the_earlier_words_up_to_a_whole_word() -> None:
    assert snippet(STAFF, 30) == "Staff records are kept for 6…"
    assert snippet(STAFF, 200) == STAFF
    assert snippet("Retention,\n  in   full", 200) == "Retention, in full"
