from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.schemas.models import ModelChannelOut, ModelHubCreate, ModelHubOut, ModelHubUpdate, ModelStatusIn
from app.services.audit_service import write_audit
from app.services.model_service import (
    create_model_hub_model,
    get_model_hub_model,
    list_model_channels,
    list_model_hub_models,
    set_model_hub_status,
    update_model_hub_model,
)

router = APIRouter(prefix="/model-hub/models", tags=["model-hub"])


def model_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_exists"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail == "model_channel_create_failed":
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("", response_model=list[ModelHubOut], summary="List model hub models")
async def list_model_hub_api(
    model_type: str | None = Query(default=None, pattern="^(llm|embedding|rerank)$"),
    provider: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    display_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ModelHubOut]:
    return await list_model_hub_models(
        db,
        model_type=model_type,
        provider=provider,
        is_active=is_active,
        display_name=display_name,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ModelHubOut, status_code=status.HTTP_201_CREATED, summary="Create model")
async def create_model_hub_api(
    payload: ModelHubCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("maas:admin")),
    db: AsyncSession = Depends(get_db),
) -> ModelHubOut:
    try:
        model = await create_model_hub_model(db, tenant_id=auth.tenant_id, payload=payload)
    except ValueError as exc:
        raise model_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="model.create",
        resource_type="model",
        resource_id=model.id,
        detail={"name": model.name, "provider": model.provider, "type": model.type},
        request=request,
    )
    return model


@router.get("/{model_id}", response_model=ModelHubOut, summary="Get model")
async def get_model_hub_api(
    model_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ModelHubOut:
    model = await get_model_hub_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_not_found")
    return model


@router.patch("/{model_id}", response_model=ModelHubOut, summary="Update model")
async def update_model_hub_api(
    model_id: UUID,
    payload: ModelHubUpdate,
    request: Request,
    auth: AuthContext = Depends(require_perm("maas:admin")),
    db: AsyncSession = Depends(get_db),
) -> ModelHubOut:
    try:
        model = await update_model_hub_model(db, model_id=model_id, payload=payload)
    except ValueError as exc:
        raise model_error(exc) from exc
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="model.update",
        resource_type="model",
        resource_id=model.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return model


@router.post("/{model_id}/status", response_model=ModelHubOut, summary="Set model status")
async def set_model_status_api(
    model_id: UUID,
    payload: ModelStatusIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("maas:admin")),
    db: AsyncSession = Depends(get_db),
) -> ModelHubOut:
    model = await set_model_hub_status(db, model_id=model_id, is_active=payload.is_active)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_not_found")
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="model.status",
        resource_type="model",
        resource_id=model.id,
        detail={"is_active": payload.is_active},
        request=request,
    )
    return model


@router.get("/{model_id}/channels", response_model=list[ModelChannelOut], summary="List model channels")
async def list_model_channels_api(
    model_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ModelChannelOut]:
    model = await get_model_hub_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_not_found")
    return await list_model_channels(db, tenant_id=auth.tenant_id, model_id=model_id)
