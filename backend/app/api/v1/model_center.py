from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_perm
from app.core.database import get_db
from app.schemas.model_center import ModelCenterChannelTestOut, ModelCenterConnectIn, ModelCenterConnectOut
from app.services.audit_service import write_audit
from app.services.model_center_service import (
    ConnectionTestFailed,
    connect_catalog_model,
    test_existing_channel,
)

router = APIRouter(prefix="/model-center", tags=["model-center"])


def model_center_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if isinstance(exc, ConnectionTestFailed):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "connection_test_failed", "summary": exc.summary},
        )
    if detail in {"model_catalog_not_found", "channel_not_found"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail == "model_name_exists":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail in {"protocol_not_supported", "model_type_not_supported"}:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if detail in {"maas_probe_failed", "model_channel_create_failed"}:
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.post("/catalog/{catalog_id}/connect", response_model=ModelCenterConnectOut, summary="Connect catalog model")
async def connect_catalog_model_api(
    catalog_id: UUID,
    payload: ModelCenterConnectIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("maas:admin")),
    db: AsyncSession = Depends(get_db),
) -> ModelCenterConnectOut:
    try:
        result = await connect_catalog_model(db, tenant_id=auth.tenant_id, catalog_id=catalog_id, payload=payload)
    except ValueError as exc:
        raise model_center_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="model_center.connect",
        resource_type="model",
        resource_id=result.model.id,
        detail={
            "catalog_id": str(catalog_id),
            "runtime_name": result.model.name,
            "channel_id": str(result.channel.id),
            "health": result.channel.health,
        },
        request=request,
    )
    return result


@router.post("/channels/{channel_id}/test", response_model=ModelCenterChannelTestOut, summary="Test model channel")
async def test_model_center_channel_api(
    channel_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("maas:admin")),
    db: AsyncSession = Depends(get_db),
) -> ModelCenterChannelTestOut:
    try:
        result = await test_existing_channel(db, tenant_id=auth.tenant_id, channel_id=channel_id)
    except ValueError as exc:
        raise model_center_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="model_center.channel_test",
        resource_type="model_channel",
        resource_id=result.channel.id,
        detail={"health": result.channel.health},
        request=request,
    )
    return result
