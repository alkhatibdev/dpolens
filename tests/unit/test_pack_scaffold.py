"""Starting a pack: everything a contributor fills in, and nothing that loads before they have."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import click
import pytest
import yaml
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.evals.run import EvalSetError, read_questions
from dpolens.engine.packs.format import PackFormatError, read_pack_metadata
from dpolens.engine.packs.scaffold import NewPack, start_pack

LGPD = NewPack(
    slug="lgpd",
    name="Lei Geral de Proteção de Dados Pessoais",
    jurisdiction="Brazil",
    lang="pt",
)
runner = CliRunner()


def started(tmp_path: Path, pack: NewPack = LGPD) -> list[Path]:
    return start_pack(pack, tmp_path / "packs", tmp_path / "evals", today=date(2026, 11, 2))


def test_a_new_pack_holds_what_a_contributor_fills_in(tmp_path: Path) -> None:
    written = started(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in written] == [
        "packs/lgpd/pack.yaml",
        "packs/lgpd/lgpd",
        "evals/lgpd/tuning.yaml",
        "evals/lgpd/tuning.en.yaml",
        "evals/lgpd/held_out.yaml",
        "evals/lgpd/held_out.en.yaml",
    ]
    raw = yaml.safe_load((tmp_path / "packs/lgpd/pack.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "Lei Geral de Proteção de Dados Pessoais"
    assert raw["documents"][0]["title"] == "Lei Geral de Proteção de Dados Pessoais"
    assert raw["version"] == "2026.1"
    assert raw["trust_tier"] == "community"
    assert raw["authoritative_language"] == "pt"


def test_it_does_not_load_until_what_only_the_contributor_knows_is_filled_in(
    tmp_path: Path,
) -> None:
    started(tmp_path)

    with pytest.raises(
        PackFormatError, match="missing required fields: effective_date, source_url, license"
    ):
        read_pack_metadata(tmp_path / "packs" / "lgpd")
    for name in ("tuning.yaml", "held_out.en.yaml"):
        with pytest.raises(EvalSetError, match="holds no questions"):
            read_questions(tmp_path / "evals" / "lgpd" / name)


def test_filled_in_it_is_a_pack(tmp_path: Path) -> None:
    """The lines left commented out are the ones to fill in, and nothing else is needed."""
    started(tmp_path)
    metadata = tmp_path / "packs" / "lgpd" / "pack.yaml"
    text = metadata.read_text(encoding="utf-8")
    text = re.sub(r"^# effective_date:.*$", "effective_date: 2020-01-01", text, flags=re.M)
    text = re.sub(r"^# source_url:.*$", "source_url: https://example.invalid/", text, flags=re.M)
    text = re.sub(
        r"^# license: >-\n(#   .*\n)+",
        "license: Excluded from copyright as an official act.\n",
        text,
        flags=re.M,
    )
    text = re.sub(r"^    # expected_clauses:.*$", "    expected_clauses: 65", text, flags=re.M)
    metadata.write_text(text, encoding="utf-8")

    pack = read_pack_metadata(tmp_path / "packs" / "lgpd")

    assert pack.slug == "lgpd"
    assert pack.jurisdiction == "Brazil"
    assert [(document.slug, document.expected_clauses) for document in pack.documents] == [
        ("lgpd", 65)
    ]


def test_a_law_in_english_is_asked_in_english_alone(tmp_path: Path) -> None:
    started(tmp_path, NewPack("sg-pdpa", "Personal Data Protection Act 2012", "Singapore", "en"))

    assert sorted(path.name for path in (tmp_path / "evals" / "sg-pdpa").iterdir()) == [
        "held_out.yaml",
        "tuning.yaml",
    ]


def test_a_pack_that_exists_is_left_as_it_is(tmp_path: Path) -> None:
    started(tmp_path)
    metadata = tmp_path / "packs" / "lgpd" / "pack.yaml"
    before = metadata.read_text(encoding="utf-8")

    with pytest.raises(PackFormatError, match="already exists, and a pack is started once"):
        started(tmp_path)

    assert metadata.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("slug", ["LGPD", "lgpd br", "-lgpd", "lgpd/br", "lgpd:br", ""])
def test_a_slug_that_cannot_start_a_key_is_refused(tmp_path: Path, slug: str) -> None:
    with pytest.raises(PackFormatError, match="cannot start a key"):
        started(tmp_path, NewPack(slug, LGPD.name, LGPD.jurisdiction, LGPD.lang))

    assert not (tmp_path / "packs").exists()


def test_the_command_starts_one_and_says_what_comes_next(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "pack",
            "scaffold",
            "lgpd",
            "--name",
            LGPD.name,
            "--jurisdiction",
            "Brazil",
            "--lang",
            "pt",
            "--packs",
            str(tmp_path / "packs"),
            "--evals",
            str(tmp_path / "evals"),
        ],
    )

    said = " ".join(click.unstyle(result.output).split())
    assert result.exit_code == 0, said
    assert "Started lgpd:" in said
    assert "packs/BUILDING.md" in said
    assert (tmp_path / "packs" / "lgpd" / "pack.yaml").is_file()


def test_the_command_refuses_in_one_line(tmp_path: Path) -> None:
    (tmp_path / "packs" / "lgpd").mkdir(parents=True)

    result = runner.invoke(
        app,
        [
            "pack",
            "scaffold",
            "lgpd",
            "--name",
            LGPD.name,
            "--jurisdiction",
            "Brazil",
            "--lang",
            "pt",
            "--packs",
            str(tmp_path / "packs"),
            "--evals",
            str(tmp_path / "evals"),
        ],
    )

    assert result.exit_code == 1
    assert "already exists, and a pack is started once" in click.unstyle(result.output)
    assert "Traceback" not in result.output
