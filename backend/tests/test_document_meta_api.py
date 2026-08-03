import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.api.v1 import kbs as kbs_api
from app.core.auth import get_current_auth
from app.core.database import get_db
from app.core.errors import AppError
from app.services.kb_service import build_default_source_meta, build_upload_meta


TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()
DOCUMENT_ID = uuid4()
KB_ID = uuid4()


class FakeDocument:
    def __init__(self, *, tenant_id: UUID = TENANT_ID) -> None:
        self.id = DOCUMENT_ID
        self.tenant_id = tenant_id
        self.kb_id = KB_ID
        self.name = "policy.md"
        self.source_uri = "object://policy.md"
        self.mime = "text/markdown"
        self.size = 100
        self.parse_status = "done"
        self.logical_doc_id = DOCUMENT_ID
        self.version_no = 1
        self.version_status = "active"
        self.version_parent_id = None
        self.activated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.meta = {
            "batch_id": "batch-1",
            "file_sha256": "hash",
            "ingest_task": {"status": "done"},
            "source": {
                "source_name": "policy.md",
                "source_type": "upload",
                "tags": [],
                "version_label": "v1",
                "published_at": None,
            },
        }
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeDb:
    async def flush(self) -> None:
        return None

    async def refresh(self, obj) -> None:
        return None


class FakeDocumentRepository:
    document = FakeDocument()

    def __init__(self, db, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    async def get_by_id(self, document_id: UUID):
        if self.tenant_id != TENANT_ID or document_id != DOCUMENT_ID:
            return None
        return self.document


def make_auth(*, tenant_id: UUID = TENANT_ID) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id, user_id=uuid4(), roles=[], permissions=["kb:create"]
    )


def make_client(monkeypatch) -> tuple[TestClient, list[dict]]:
    audits: list[dict] = []
    FakeDocumentRepository.document = FakeDocument()

    async def fake_db():
        yield FakeDb()

    async def fake_write_audit(db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(kbs_api, "DocumentRepository", FakeDocumentRepository)
    monkeypatch.setattr(kbs_api, "write_audit", fake_write_audit)
    app = FastAPI()
    app.add_exception_handler(
        AppError,
        lambda request, exc: JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
        ),
    )
    app.include_router(kbs_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_auth] = lambda: make_auth()
    return TestClient(app), audits


def test_upload_meta_defaults_source_and_preserves_existing_meta() -> None:
    meta = build_upload_meta(
        object_name="object",
        extra_meta={"batch_id": "batch-1"},
        content_sha256="hash",
        duplicate=None,
        filename="policy.md",
    )

    assert meta["batch_id"] == "batch-1"
    assert meta["file_sha256"] == "hash"
    assert meta["duplicate"] == {"status": "none"}
    assert meta["source"] == {
        "source_name": "policy.md",
        "source_type": "upload",
        "tags": [],
        "version_label": "v1",
        "published_at": None,
    }
    assert build_default_source_meta("x.md", {"tags": ["A"]})["tags"] == ["A"]


def test_patch_document_meta_updates_only_source_and_writes_audit(monkeypatch) -> None:
    client, audits = make_client(monkeypatch)

    response = client.patch(
        f"/api/v1/documents/{DOCUMENT_ID}/meta",
        json={
            "source": {
                "source_name": "员工手册",
                "source_type": "manual",
                "tags": ["制度", "", "制度", "HR"],
                "version_label": "v2",
                "published_at": "2026-01-01",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["batch_id"] == "batch-1"
    assert payload["meta"]["file_sha256"] == "hash"
    assert payload["meta"]["ingest_task"] == {"status": "done"}
    assert payload["meta"]["source"]["source_name"] == "员工手册"
    assert payload["meta"]["source"]["source_type"] == "manual"
    assert payload["meta"]["source"]["tags"] == ["制度", "HR"]
    assert audits[0]["action"] == "document.meta.update"
    assert audits[0]["resource_id"] == DOCUMENT_ID


def test_patch_document_meta_rejects_empty_source_name(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)

    response = client.patch(
        f"/api/v1/documents/{DOCUMENT_ID}/meta",
        json={"source": {"source_name": "   "}},
    )

    assert response.status_code == 422


def test_patch_document_meta_is_tenant_scoped(monkeypatch) -> None:
    client, _ = make_client(monkeypatch)
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth(
        tenant_id=OTHER_TENANT_ID
    )

    response = client.patch(
        f"/api/v1/documents/{DOCUMENT_ID}/meta",
        json={"source": {"source_name": "员工手册"}},
    )

    assert response.status_code == 404
