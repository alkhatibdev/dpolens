"""Batches for embedding: strings of about one length together, and none past the budget."""

from __future__ import annotations

from dpolens.engine.embedding.index import BATCH_BUDGET, batches


def test_every_string_is_in_one_batch_shortest_first() -> None:
    tokens = [300, 20, 512, 64, 20, 128]

    placed = [at for batch in batches(tokens) for at in batch]

    assert sorted(placed) == list(range(len(tokens)))
    assert [tokens[at] for at in placed] == sorted(tokens)


def test_no_batch_holds_more_than_the_budget() -> None:
    tokens = [512] * 10 + [128] * 100 + [20] * 300

    for batch in batches(tokens):
        assert len(batch) * max(tokens[at] for at in batch) ** 2 <= BATCH_BUDGET


def test_the_longest_strings_go_one_at_a_time() -> None:
    assert [len(batch) for batch in batches([512] * 3)] == [1, 1, 1]
    assert [len(batch) for batch in batches([128] * 20)] == [16, 4]


def test_nothing_to_embed_is_no_batch() -> None:
    assert batches([]) == []
