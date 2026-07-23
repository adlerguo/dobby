from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth, require_perm
from app.core.database import get_db
from app.schemas.publish import (
    AppApiKeyCreate,
    AppApiKeyCreatedOut,
    AppApiKeyOut,
    AppApiKeyStatusIn,
    PublishedAppCreate,
    PublishedAppOut,
)
from app.services.audit_service import write_audit
from app.services.publish_service import (
    create_app_api_key,
    create_published_app,
    get_published_app,
    list_app_api_keys,
    list_published_apps,
    set_app_api_key_status,
    unpublish_app,
)

router = APIRouter(prefix="/published-apps", tags=["published-apps"])


def publish_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if detail in {"agent_not_publishable", "published_app_not_active"}:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.post(
    "",
    response_model=PublishedAppOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publish agent as app",
)
async def create_published_app_api(
    payload: PublishedAppCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> PublishedAppOut:
    try:
        app = await create_published_app(
            db, tenant_id=auth.tenant_id, user_id=auth.user_id, payload=payload
        )
    except ValueError as exc:
        raise publish_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="published_app.create",
        resource_type="published_app",
        resource_id=app.id,
        detail={"agent_id": str(app.agent_id), "publish_type": app.publish_type},
        request=request,
    )
    return app


@router.get("", response_model=list[PublishedAppOut], summary="List published apps")
async def list_published_apps_api(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[PublishedAppOut]:
    return await list_published_apps(db, tenant_id=auth.tenant_id)


@router.get("/{app_id}", response_model=PublishedAppOut, summary="Get published app")
async def get_published_app_api(
    app_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> PublishedAppOut:
    app = await get_published_app(db, tenant_id=auth.tenant_id, app_id=app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="published_app_not_found"
        )
    return app


@router.post(
    "/{app_id}/unpublish", response_model=PublishedAppOut, summary="Unpublish app"
)
async def unpublish_app_api(
    app_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> PublishedAppOut:
    app = await unpublish_app(db, tenant_id=auth.tenant_id, app_id=app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="published_app_not_found"
        )
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="published_app.unpublish",
        resource_type="published_app",
        resource_id=app.id,
        request=request,
    )
    return app


@router.post(
    "/{app_id}/keys",
    response_model=AppApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create app API key",
)
async def create_app_api_key_api(
    app_id: UUID,
    payload: AppApiKeyCreate,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> AppApiKeyCreatedOut:
    try:
        key, raw_key = await create_app_api_key(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            app_id=app_id,
            payload=payload,
        )
    except ValueError as exc:
        raise publish_error(exc) from exc
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="app_api_key.create",
        resource_type="app_api_key",
        resource_id=key.id,
        detail={"app_id": str(app_id), "key_prefix": key.key_prefix},
        request=request,
    )
    key_out = AppApiKeyOut.model_validate(key)
    return AppApiKeyCreatedOut(**key_out.model_dump(), api_key=raw_key)


@router.get(
    "/{app_id}/keys", response_model=list[AppApiKeyOut], summary="List app API keys"
)
async def list_app_api_keys_api(
    app_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[AppApiKeyOut]:
    keys = await list_app_api_keys(db, tenant_id=auth.tenant_id, app_id=app_id)
    if keys is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="published_app_not_found"
        )
    return keys


@router.post(
    "/{app_id}/keys/{key_id}/status",
    response_model=AppApiKeyOut,
    summary="Set app API key status",
)
async def set_app_api_key_status_api(
    app_id: UUID,
    key_id: UUID,
    payload: AppApiKeyStatusIn,
    request: Request,
    auth: AuthContext = Depends(require_perm("agent:publish")),
    db: AsyncSession = Depends(get_db),
) -> AppApiKeyOut:
    key = await set_app_api_key_status(
        db,
        tenant_id=auth.tenant_id,
        app_id=app_id,
        key_id=key_id,
        status=payload.status,
    )
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="app_api_key_not_found"
        )
    await write_audit(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="app_api_key.status",
        resource_type="app_api_key",
        resource_id=key.id,
        detail={"app_id": str(app_id), "status": key.status},
        request=request,
    )
    return key
