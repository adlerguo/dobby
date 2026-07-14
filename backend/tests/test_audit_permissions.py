from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import audit as audit_api
from app.core.auth import get_current_auth
from app.core.database import get_db


@dataclass
class FakeAuditLog:
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    action: str | None
    resource_type: str | None
    resource_id: UUID | None
    ip: str | None
    detail: dict
    created_at: datetime


TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()


def make_auth(role: str) -> SimpleNamespace:
    permissions = ["audit:view"] if role == "tenant_admin" else []
    return SimpleNamespace(
        user=SimpleNamespace(id=uuid4()),
        tenant=SimpleNamespace(id=TENANT_ID),
        roles=[role],
        permissions=permissions,
        tenant_id=TENANT_ID,
        user_id=uuid4(),
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    logs = [
        FakeAuditLog(
            id=uuid4(),
            tenant_id=TENANT_ID,
            user_id=uuid4(),
            action="user.login",
            resource_type="auth",
            resource_id=None,
            ip="127.0.0.1",
            detail={"ok": True},
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        FakeAuditLog(
            id=uuid4(),
            tenant_id=OTHER_TENANT_ID,
            user_id=uuid4(),
            action="user.login",
            resource_type="auth",
            resource_id=None,
            ip="127.0.0.2",
            detail={"ok": True},
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    ]

    async def fake_list_audit_logs(db, *, tenant_id, **kwargs):
        return [log for log in logs if log.tenant_id == tenant_id]

    async def fake_db():
        yield object()

    monkeypatch.setattr(audit_api, "list_audit_logs", fake_list_audit_logs)

    app = FastAPI()
    app.include_router(audit_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_tenant_admin_can_view_only_own_tenant_audit_logs(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth("tenant_admin")

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 200
    tenant_ids = {item["tenant_id"] for item in response.json()}
    assert tenant_ids == {str(TENANT_ID)}


@pytest.mark.parametrize("role", ["builder", "member"])
def test_builder_and_member_cannot_view_audit_logs(client: TestClient, role: str) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth(role)

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 403
