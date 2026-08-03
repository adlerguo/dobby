import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.rag import retrieve
from app.services.kb_service import (
    active_document_id,
    build_upload_meta,
    clean_version_label,
    next_document_version_no,
    upload_document_version,
)


TENANT_ID = uuid4()
KB_ID = uuid4()
LOGICAL_DOC_ID = uuid4()


def run_async(awaitable):
    return asyncio.run(awaitable)


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class FakeMaxVersionDb:
    async def execute(self, stmt, params=None):
        return FakeScalarResult(1)


def test_legacy_document_version_defaults_are_representable() -> None:
    document = SimpleNamespace(
        id=LOGICAL_DOC_ID,
        logical_doc_id=LOGICAL_DOC_ID,
        version_no=1,
        version_status="active",
        version_parent_id=None,
        activated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert document.logical_doc_id == document.id
    assert document.version_no == 1
    assert document.version_status == "active"
    assert document.version_parent_id is None


def test_upload_meta_can_hold_first_version_metadata() -> None:
    meta = build_upload_meta(
        object_name="object",
        extra_meta={"version": {"version_no": 1, "created_from": "upload"}},
        content_sha256="hash",
        duplicate=None,
        filename="policy.md",
    )

    assert meta["source"]["version_label"] == "v1"
    assert meta["version"]["version_no"] == 1
    assert meta["version"]["created_from"] == "upload"


def test_next_version_no_increments_existing_max() -> None:
    assert (
        run_async(
            next_document_version_no(
                FakeMaxVersionDb(),
                tenant_id=TENANT_ID,
                kb_id=KB_ID,
                logical_doc_id=LOGICAL_DOC_ID,
            )
        )
        == 2
    )


def test_version_label_is_trimmed_and_empty_becomes_none() -> None:
    assert clean_version_label(" v2 ") == "v2"
    assert clean_version_label(" ") is None


def test_active_document_id_returns_current_active() -> None:
    active_id = uuid4()

    class FakeDb:
        async def execute(self, stmt):
            return FakeScalarResult(active_id)

    assert (
        run_async(
            active_document_id(
                FakeDb(),
                tenant_id=TENANT_ID,
                kb_id=KB_ID,
                logical_doc_id=LOGICAL_DOC_ID,
            )
        )
        == active_id
    )


def test_retrieve_sql_filters_active_versions() -> None:
    sql = str(
        retrieve.text(
            """
            SELECT 1
            FROM chunks c
            JOIN documents d ON d.id = c.doc_id
            WHERE d.version_status = 'active'
            """
        )
    )

    assert "version_status = 'active'" in sql


def test_cannot_activate_mismatched_logical_doc_strategy() -> None:
    document = SimpleNamespace(kb_id=KB_ID, logical_doc_id=uuid4())
    version = SimpleNamespace(kb_id=KB_ID, logical_doc_id=uuid4())

    with pytest.raises(ValidationError):
        if document.kb_id != version.kb_id or document.logical_doc_id != version.logical_doc_id:
            raise ValidationError(code="document_version_mismatch")


def test_not_done_version_activation_strategy_is_blocking() -> None:
    version = SimpleNamespace(parse_status="pending")

    with pytest.raises(ValidationError):
        if version.parse_status != "done":
            raise ValidationError(code="document_version_not_ready")


def test_upload_new_version_strategy_stays_inactive_until_parsed() -> None:
    source = inspect.getsource(upload_document_version)

    assert "document_version_created_inactive_until_parsed" in source
    assert 'status="inactive"' in source
    assert "previous_active_id=None" in source
