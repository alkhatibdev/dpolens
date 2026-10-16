"""The file as it was read, which a reviewer sees beside the clauses it became."""

from __future__ import annotations

from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.reading import as_rows, from_rows

SCHEDULE = b"""# Retention schedule

| Record | Kept for |
| --- | --- |
| Customer accounts | 2 years |

1. Review every year.
"""


def test_every_paragraph_keeps_its_place_and_its_look() -> None:
    lines = parse_policy(SCHEDULE, "schedule.md").lines

    assert [(line.position, line.text, line.heading, line.label) for line in lines] == [
        (0, "Retention schedule", 1, None),
        (1, "Record", None, None),
        (2, "Kept for", None, None),
        (3, "Customer accounts", None, None),
        (4, "2 years", None, None),
        (5, "Review every year.", None, "1."),
    ]


def test_a_table_s_cells_keep_their_row_and_column() -> None:
    lines = parse_policy(SCHEDULE, "schedule.md").lines

    assert [(line.table, line.row, line.cell, line.header) for line in lines[1:5]] == [
        (0, 0, 0, True),
        (0, 0, 1, True),
        (0, 1, 0, False),
        (0, 1, 1, False),
    ]


def test_what_is_kept_reads_back_the_same() -> None:
    lines = parse_policy(SCHEDULE, "schedule.md").lines

    assert from_rows(as_rows(lines)) == lines
