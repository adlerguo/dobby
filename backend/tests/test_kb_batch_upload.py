import asyncio
import os
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.api.v1 import kbs as kbs_api
from app.core.auth import get_current_auth
from app.core.database import get_db
from app.core.errors import NotFoundError, ValidationError
from app.services import kb_service


TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()
KB_ID = uuid4()


def run_async(awaitable):
    return asyncio.run(awaitable)


def make_auth(*, tenant_id: UUID = TENANT_ID) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        user_id=uuid4(),
        roles=[],
        permissions=["kb:create"],
    )


class FakeKbRepository:
    def __init__(self, db, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    async def get_by_id(self, kb_id: UUID):
        if self.tenant_id != TENANT_ID or kb_id != KB_ID:
            return None
        return SimpleNamespace(id=kb_id, tenant_id=self.tenant_id, status="active")


def test_batch_upload_service_creates_valid_files_and_keeps_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upload_document(db, *, tenant_id, kb_id, file: UploadFile, extra_meta=None):
        if file.filename == "bad.exe":
            raise ValidationError(code="unsupported_document_type")
        return SimpleNamespace(
            id=uuid4(),
            name=file.filename,
            meta=dict(extra_meta or {}),
        )

    files = [
        UploadFile(filename="alpha.txt", file=BytesIO(b"alpha")),
        UploadFile(filename="bad.exe", file=BytesIO(b"bad")),
        UploadFile(filename="beta.md", file=BytesIO(b"beta")),
    ]
    monkeypatch.setattr(kb_service, "KnowledgeBaseRepository", FakeKbRepository)
    monkeypatch.setattr(kb_service, "upload_document", fake_upload_document)

    result = run_async(
        kb_service.upload_documents_batch(
            object(), tenant_id=TENANT_ID, kb_id=KB_ID, files=files
        )
    )

    assert result is not None
    batch, created_documents = result
    assert batch.total == 3
    assert batch.created == 2
    assert batch.failed == 1
    assert [item.status for item in batch.items] == ["created", "failed", "created"]
    assert batch.items[1].error == "unsupported_document_type"
    assert len(created_documents) == 2
    assert all(document.meta["batch_id"] == str(batch.batch_id) for document in created_documents)


def test_batch_upload_service_returns_none_for_missing_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kb_service, "KnowledgeBaseRepository", FakeKbRepository)

    result = run_async(
        kb_service.upload_documents_batch(
            object(),
            tenant_id=OTHER_TENANT_ID,
            kb_id=KB_ID,
            files=[UploadFile(filename="alpha.txt", file=BytesIO(b"alpha"))],
        )
    )

    assert result is None


def test_batch_upload_api_accepts_multipart_and_enqueues_created_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    queued: list[UUID] = []
    audits: list[dict] = []

    async def fake_db():
        yield object()

    async def fake_upload_documents_batch(db, *, tenant_id, kb_id, files):
        assert tenant_id == TENANT_ID
        assert kb_id == KB_ID
        assert [file.filename for file in files] == ["alpha.txt", "bad.exe"]
        return (
            kbs_api.DocumentBatchCreateOut(
                batch_id=uuid4(),
                total=2,
                created=1,
                failed=1,
                items=[
                    kbs_api.DocumentBatchItemOut(
                        filename="alpha.txt",
                        status="created",
                        document_id=document_id,
                    ),
                    kbs_api.DocumentBatchItemOut(
                        filename="bad.exe",
                        status="failed",
                        error="unsupported_document_type",
                    ),
                ],
            ),
            [SimpleNamespace(id=document_id)],
        )

    async def fake_enqueue_parse_document(document_id: UUID) -> None:
        queued.append(document_id)

    async def fake_write_audit(db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(kbs_api, "upload_documents_batch", fake_upload_documents_batch)
    monkeypatch.setattr(kbs_api, "enqueue_parse_document", fake_enqueue_parse_document)
    monkeypatch.setattr(kbs_api, "write_audit", fake_write_audit)

    app = FastAPI()
    app.include_router(kbs_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_auth] = lambda: make_auth()
    client = TestClient(app)

    response = client.post(
        f"/api/v1/kbs/{KB_ID}/documents/batch",
        files=[
            ("files", ("alpha.txt", b"alpha", "text/plain")),
            ("files", ("bad.exe", b"bad", "application/octet-stream")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] == 2
    assert payload["created"] == 1
    assert payload["failed"] == 1
    assert payload["items"][0]["document_id"] == str(document_id)
    assert payload["items"][1]["error"] == "unsupported_document_type"
    assert queued == [document_id]
    assert audits[0]["action"] == "document.batch_upload"
    assert audits[0]["detail"]["total"] == 2
    assert audits[0]["detail"]["created"] == 1
    assert audits[0]["detail"]["failed"] == 1


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeMappings:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return self.values


class FakeDocumentResult:
    def __init__(self, values) -> None:
        self.values = values

    def mappings(self):
        return FakeMappings(self.values)


class FakeBatchStatusDb:
    def __init__(self, *, kb, documents=None) -> None:
        self.kb = kb
        self.documents = documents or []
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        if self.calls == 1:
            return FakeScalarResult(self.kb)
        return FakeDocumentResult(self.documents)


def test_batch_status_query_aggregates_document_states() -> None:
    batch_id = uuid4()
    documents = [
        {
            "id": uuid4(),
            "name": "done.txt",
            "parse_status": "done",
            "meta": {"batch_id": str(batch_id)},
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
        {
            "id": uuid4(),
            "name": "failed.txt",
            "parse_status": "failed",
            "meta": {
                "batch_id": str(batch_id),
                "ingest_task": {
                    "error": {"error_code": "parser_failed"},
                },
            },
            "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        },
        {
            "id": uuid4(),
            "name": "pending.txt",
            "parse_status": "pending",
            "meta": {"batch_id": str(batch_id)},
            "created_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
        },
    ]
    db = FakeBatchStatusDb(
        kb=SimpleNamespace(id=KB_ID, tenant_id=TENANT_ID, status="active"),
        documents=documents,
    )

    result = run_async(
        kbs_api.get_document_batch_status(
            KB_ID,
            batch_id,
            auth=make_auth(),
            db=db,
        )
    )

    assert result.total == 3
    assert result.document_success == 1
    assert result.document_failed == 1
    assert result.document_processing == 1
    failed_item = next(item for item in result.items if item.name == "failed.txt")
    assert failed_item.error_code == "parser_failed"


def test_batch_status_query_is_tenant_scoped() -> None:
    db = FakeBatchStatusDb(kb=None)

    with pytest.raises(NotFoundError):
        run_async(
            kbs_api.get_document_batch_status(
                KB_ID,
                uuid4(),
                auth=make_auth(tenant_id=OTHER_TENANT_ID),
                db=db,
            )
        )
