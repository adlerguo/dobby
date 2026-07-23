import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

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
    user_id = uuid4()
    logs = [
        FakeAuditLog(
            id=uuid4(),
            tenant_id=TENANT_ID,
            user_id=user_id,
            action="user.login",
            resource_type="auth",
            resource_id=None,
            ip="127.0.0.1",
            detail={"ok": True},
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        FakeAuditLog(
            id=uuid4(),
            tenant_id=TENANT_ID,
            user_id=uuid4(),
            action="agent.run",
            resource_type="agent",
            resource_id=uuid4(),
            ip="127.0.0.3",
            detail={"结果": "成功"},
            created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
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

    def apply_filters(
        tenant_id,
        user_id=None,
        action=None,
        resource_type=None,
        date_from=None,
        date_to=None,
        **kwargs,
    ):
        rows = [log for log in logs if log.tenant_id == tenant_id]
        if user_id is not None:
            rows = [log for log in rows if log.user_id == user_id]
        if action is not None:
            rows = [log for log in rows if log.action == action]
        if resource_type is not None:
            rows = [log for log in rows if log.resource_type == resource_type]
        if date_from is not None:
            rows = [log for log in rows if log.created_at >= date_from]
        if date_to is not None:
            rows = [log for log in rows if log.created_at <= date_to]
        return sorted(rows, key=lambda log: log.created_at, reverse=True)

    async def fake_list_audit_logs(db, *, tenant_id, **kwargs):
        offset = kwargs.pop("offset", 0)
        limit = kwargs.pop("limit", 50)
        return apply_filters(tenant_id, **kwargs)[offset : offset + limit]

    async def fake_iter_export_audit_logs(db, *, tenant_id, **kwargs):
        limit = kwargs.pop("limit", 50000)
        for log in apply_filters(tenant_id, **kwargs)[:limit]:
            yield log

    async def fake_is_audit_log_export_truncated(db, *, tenant_id, **kwargs):
        limit = kwargs.pop("limit", 50000)
        return len(apply_filters(tenant_id, **kwargs)) > limit

    async def fake_db():
        yield object()

    monkeypatch.setattr(audit_api, "list_audit_logs", fake_list_audit_logs)
    monkeypatch.setattr(
        audit_api, "iter_export_audit_logs", fake_iter_export_audit_logs
    )
    monkeypatch.setattr(
        audit_api, "is_audit_log_export_truncated", fake_is_audit_log_export_truncated
    )

    app = FastAPI()
    app.include_router(audit_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_tenant_admin_can_view_only_own_tenant_audit_logs(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth(
        "tenant_admin"
    )

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 200
    tenant_ids = {item["tenant_id"] for item in response.json()}
    assert tenant_ids == {str(TENANT_ID)}


@pytest.mark.parametrize("role", ["builder", "member"])
def test_builder_and_member_cannot_view_audit_logs(
    client: TestClient, role: str
) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth(role)

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 403


def test_audit_log_export_csv_uses_same_filters_as_list(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth(
        "tenant_admin"
    )

    list_response = client.get("/api/v1/audit-logs", params={"action": "agent.run"})
    export_response = client.get(
        "/api/v1/audit-logs/export", params={"action": "agent.run"}
    )

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")
    assert export_response.headers["content-disposition"].startswith(
        "attachment; filename=audit_logs_"
    )
    assert export_response.headers["x-export-truncated"] == "false"
    assert list_response.json()[0]["action"] == "agent.run"
    assert (
        "created_at,user_id,action,resource_type,resource_id,ip,detail"
        in export_response.text
    )
    rows = list(csv.DictReader(StringIO(export_response.text)))
    assert len(rows) == 1
    assert rows[0]["action"] == "agent.run"
    assert rows[0]["resource_type"] == "agent"
    assert json.loads(rows[0]["detail"]) == {"结果": "成功"}
    assert "user.login" not in export_response.text


def test_audit_log_export_requires_audit_view(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_auth] = lambda: make_auth("member")

    response = client.get("/api/v1/audit-logs/export")

    assert response.status_code == 403
