"""Redaction, which is a promise rather than a nicety.

The interesting cases are the near misses: a long number that is not a card, an
account code that is not an IBAN, a version string that is not a phone number.
A redactor that hides those teaches everybody to ignore it.
"""

from __future__ import annotations

import pytest

from dpolens.engine.logs.redaction import (
    MAX_PATTERN,
    check_pattern,
    luhn,
    redact,
)


class TestEmail:
    def test_an_address_is_hidden_and_named(self) -> None:
        result = redact("can we log hamad@example.com for debugging")

        assert "hamad@example.com" not in result.text
        assert "[redacted:email]" in result.text
        assert result.count == 1
        assert result.types == ("email",)

    def test_several_addresses_are_all_hidden(self) -> None:
        result = redact("mail a@b.co and c@d.org")

        assert result.count == 2
        assert "@" not in result.text.replace("[redacted:email]", "")

    def test_a_question_with_nothing_personal_is_untouched(self) -> None:
        asked = "how long can we keep a deleted user's data"

        result = redact(asked)

        assert result.text == asked
        assert result.count == 0
        assert result.types == ()


class TestCards:
    def test_a_card_number_is_hidden(self) -> None:
        result = redact("the card 4242 4242 4242 4242 is in the logs")

        assert "4242" not in result.text
        assert result.types == ("card",)

    def test_a_long_number_that_fails_the_check_is_left_alone(self) -> None:
        """Otherwise every reference number in every question becomes noise."""
        result = redact("ticket 1234 5678 9012 3456 is about retention")

        assert "1234 5678 9012 3456" in result.text
        assert result.count == 0

    @pytest.mark.parametrize("number", ["4242424242424242", "4242-4242-4242-4242"])
    def test_separators_do_not_matter(self, number: str) -> None:
        assert redact(f"card {number}").types == ("card",)

    def test_luhn_itself(self) -> None:
        assert luhn("4242424242424242")
        assert not luhn("4242424242424243")


class TestIban:
    def test_a_valid_iban_is_hidden(self) -> None:
        result = redact("pay into GB82WEST12345698765432 please")

        assert "GB82WEST12345698765432" not in result.text
        assert "iban" in result.types

    def test_something_iban_shaped_that_does_not_check_out(self) -> None:
        result = redact("the code GB00WEST12345698765432 is not an account")

        assert "GB00WEST12345698765432" in result.text


class TestPhonesAndIdentifiers:
    def test_a_phone_number_is_hidden(self) -> None:
        result = redact("call +971 50 123 4567 about the request")

        assert "4567" not in result.text
        assert "phone" in result.types

    def test_an_emirates_id_is_hidden(self) -> None:
        result = redact("subject 784-1990-1234567-1 asked for erasure")

        assert "784-1990-1234567-1" not in result.text
        assert "emirates_id" in result.types

    def test_a_version_number_is_not_a_phone_number(self) -> None:
        untouched = "does clause 5.2.1 apply to article 17"

        assert redact(untouched).text == untouched

    def test_a_year_is_not_a_phone_number(self) -> None:
        untouched = "what changed in 2018 for retention"

        assert redact(untouched).text == untouched


class TestAddedPatterns:
    def test_an_operator_can_add_a_local_identifier_format(self) -> None:
        """The reason configuration exists at all: a format we did not think of."""
        result = redact("national id 1234567890 please", extra={"saudi_id": r"\b1\d{9}\b"})

        assert "1234567890" not in result.text
        assert "saudi_id" in result.types

    def test_an_added_pattern_cannot_remove_a_built_in(self) -> None:
        result = redact("mail a@b.co", extra={"nothing": r"zzz"})

        assert "[redacted:email]" in result.text

    def test_a_pattern_that_hangs_is_abandoned_rather_than_waited_for(self) -> None:
        """A regular expression from outside this repository is a denial of service
        waiting to happen, and this is the one that does it."""
        catastrophic = r"(a+)+b"

        result = redact("a" * 40, extra={"slow": catastrophic})

        assert result.count == 0
        assert "slow" not in result.types

    def test_a_broken_pattern_does_not_break_the_search(self) -> None:
        result = redact("mail a@b.co", extra={"broken": "("})

        assert "[redacted:email]" in result.text
        assert "broken" not in result.types


class TestCheckPattern:
    def test_accepts_a_reasonable_one(self) -> None:
        check_pattern("saudi_id", r"\b1\d{9}\b")

    def test_refuses_a_pattern_that_matches_nothing_at_all(self) -> None:
        """It would replace every position in the text, which is not redaction."""
        with pytest.raises(ValueError, match="empty string"):
            check_pattern("everything", r"\b*")

    def test_refuses_a_pattern_that_does_not_compile(self) -> None:
        with pytest.raises(ValueError, match="does not compile"):
            check_pattern("broken", "(")

    def test_refuses_a_pattern_longer_than_the_cap(self) -> None:
        with pytest.raises(ValueError, match="longer than"):
            check_pattern("long", "a" * (MAX_PATTERN + 1))

    def test_refuses_a_name_that_is_not_a_word(self) -> None:
        """The name is stored on every row it fires on, so it has to read as one."""
        with pytest.raises(ValueError, match="identifiers"):
            check_pattern("not a name", r"\d+")


def test_everything_at_once_is_counted_and_named() -> None:
    result = redact(
        "hamad@example.com called +971 50 123 4567 about card 4242 4242 4242 4242",
    )

    assert set(result.types) == {"email", "phone", "card"}
    assert result.count == 3
    assert "hamad" not in result.text
    assert "4242" not in result.text
    assert "4567" not in result.text
