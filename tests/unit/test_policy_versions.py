"""Which clause of a new version continues which clause of the version before it.

The story is the one the integration tests tell: version 2 inserts a contractor rule at 4.2, so
the staff rule is printed as 4.3 and the supplier rule as 4.4.
"""

from __future__ import annotations

import uuid

from dpolens.engine.policies.checks import snippet
from dpolens.engine.policies.versions import (
    ASK_SIMILARITY,
    MOVED_SIMILARITY,
    Earlier,
    Later,
    match,
    questions,
)

CUSTOMER = "Customer records are kept for 2 years after the account closes."
STAFF = "Staff records are kept for 6 years after employment ends."
SUPPLIER = "Supplier records are kept for 5 years after the contract ends."
CONTRACTOR = "Contractor records are kept for 1 year after the contract ends."
BACKUPS = "Backups are encrypted and kept in a second region."
PAYMENTS = "Payment records are kept for 7 years, as tax law requires."


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


def test_a_new_rule_sharing_most_of_a_removed_rule_s_words_is_asked_about() -> None:
    """Renumbered and reworded, it is too far from the rule before to be paired without asking."""
    payments = before("r:4.3", PAYMENTS)
    later = after(
        "r:4.4", PAYMENTS.replace("7 years,", "7 years after the end of the financial year,")
    )

    matching = match([payments], [later])
    asked = questions([later], matching.removed)

    assert matching.matches["r:4.4"].change == "added"
    old, score = asked["r:4.4"]
    assert old == payments
    assert ASK_SIMILARITY <= score < MOVED_SIMILARITY


def test_each_rule_is_in_one_question_at_most_the_closest_pair_first() -> None:
    """The customer rule is closer to the supplier rule than to the staff rule, but the contractor
    rule is closer still, so the customer rule is asked about the staff rule."""
    staff, supplier = before("r:4.2", STAFF), before("r:4.3", SUPPLIER)

    asked = questions([after("r:4.6", CUSTOMER), after("r:4.5", CONTRACTOR)], [staff, supplier])

    assert {key: old.key for key, (old, _) in asked.items()} == {"r:4.5": "r:4.3", "r:4.6": "r:4.2"}


def test_a_pair_said_to_be_different_rules_is_never_asked_about() -> None:
    staff, supplier = before("r:4.2", STAFF), before("r:4.3", SUPPLIER)

    asked = questions(
        [after("r:4.5", CONTRACTOR)], [staff, supplier], skip=lambda new, old: old == supplier
    )

    assert asked["r:4.5"][0] == staff


def test_few_shared_words_or_enough_to_be_paired_are_no_question() -> None:
    assert questions([after("r:4.5", BACKUPS)], [before("r:4.2", STAFF)]) == {}
    invoices = after("r:4.5", PAYMENTS.replace("Payment records", "Invoices"))
    assert questions([invoices], [before("r:4.3", PAYMENTS)]) == {}
