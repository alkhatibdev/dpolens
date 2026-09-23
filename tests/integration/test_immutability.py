"""A published version cannot change, and the database is what enforces it.

A citation is worthless if the text it points at can move underneath it.
Application code could promise this; these tests prove the promise survives
code that never asked.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document, DocumentNode, DocumentVersion
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded(session: Session, testlaw_pack: Path) -> Session:
    load_pack(session, testlaw_pack)
    session.commit()
    return session


def test_published_clause_text_cannot_be_changed(loaded: Session) -> None:
    with pytest.raises(IntegrityError, match="immutable"):
        loaded.execute(text("UPDATE node_texts SET body_text = 'rewritten'"))
    loaded.rollback()


def test_published_clauses_cannot_be_deleted(loaded: Session) -> None:
    with pytest.raises(IntegrityError, match="immutable"):
        loaded.execute(
            text("DELETE FROM document_nodes WHERE canonical_key = 'testlaw:art-5:para-1:pt-a'")
        )
    loaded.rollback()


def test_a_published_version_cannot_be_redated(loaded: Session) -> None:
    with pytest.raises(IntegrityError, match="immutable"):
        loaded.execute(text("UPDATE document_versions SET effective_date = '2030-01-01'"))
    loaded.rollback()


def test_drafts_remain_editable(session: Session) -> None:
    document = Document(kind="org_policy", slug="acme-retention", title="Retention policy")
    session.add(document)
    session.flush()
    draft = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="draft",
        effective_date=date(2026, 1, 1),
        source_ref="upload:1",
    )
    session.add(draft)
    session.commit()

    draft.version_label = "reviewed"
    session.commit()

    assert session.scalar(select(DocumentVersion.version_label)) == "reviewed"


def test_the_document_row_itself_stays_editable(loaded: Session) -> None:
    """Archiving hides a document. It never touches the text of a version."""
    document = loaded.scalar(select(Document).where(Document.slug == "testlaw"))
    assert document is not None

    document.status = "archived"
    loaded.commit()

    assert loaded.scalar(select(Document.status).where(Document.slug == "testlaw")) == "archived"


def test_nodes_of_a_draft_can_still_be_fixed(session: Session) -> None:
    document = Document(kind="org_policy", slug="acme-security", title="Security policy")
    session.add(document)
    session.flush()
    draft = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="draft",
        effective_date=date(2026, 1, 1),
        source_ref="upload:2",
    )
    session.add(draft)
    session.flush()
    node = DocumentNode(
        document_version_id=draft.id,
        canonical_key="acme-security:sec-1",
        node_type="section",
        order_index=0,
        depth=0,
    )
    session.add(node)
    session.commit()

    node.label = "1."
    session.commit()

    assert session.scalar(select(DocumentNode.label)) == "1."
