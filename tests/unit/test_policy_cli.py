"""`dpolens policy parse`: how DPOLens reads a policy, before anything is stored."""

from __future__ import annotations

import json
from pathlib import Path

import click
from typer.testing import CliRunner, Result

from dpolens.cli.main import app

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
runner = CliRunner()
BORDERS = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def said(result: Result) -> str:
    """The output as the words a person reads, on one line, whatever the terminal draws."""
    return " ".join(click.unstyle(result.output).translate(BORDERS).split())


def test_prints_the_clauses_with_their_keys_and_layers() -> None:
    result = runner.invoke(
        app, ["policy", "parse", str(FIXTURES / "typed-numbers.docx"), "--slug", "acme"]
    )

    assert result.exit_code == 0, result.output
    text = said(result)
    assert "Word file, 11 clauses." in text
    assert "2.1 Purpose" in text
    assert "3:term-definition:personal-data Personal Data" in text
    assert "Set aside, not searched: front matter (5 paragraphs)." in text
    assert "Nothing for a reviewer to settle." in text


def test_shows_what_a_reviewer_has_to_settle() -> None:
    result = runner.invoke(app, ["policy", "parse", str(FIXTURES / "numbered-headings.docx")])

    assert result.exit_code == 0, result.output
    text = said(result)
    assert "For a reviewer to settle (1):" in text
    assert '"Paper Storage:" has no number, unlike the headings around it' in text


def test_json_carries_everything() -> None:
    result = runner.invoke(
        app, ["policy", "parse", str(FIXTURES / "arabic-sections.docx"), "--slug", "x", "--json"]
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["coverage"]["missed"] == 0
    assert parsed["clauses"][1]["key"] == "x:بنود-السياسة"
    first = parsed["clauses"][1]["children"][0]
    assert [child["key"] for child in first["children"]] == [
        "x:بنود-السياسة:1-1",
        "x:بنود-السياسة:1-2",
    ]


def test_a_file_it_cannot_read_says_why_in_one_line(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    result = runner.invoke(app, ["policy", "parse", str(pdf)])

    assert result.exit_code == 1
    assert "PDF files are not read. Use the Word or Markdown file the PDF was made from." in said(
        result
    )
