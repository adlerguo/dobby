from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth
from app.core.database import get_db
from app.schemas.model_catalog import ModelCatalogOut
from app.services.model_catalog_service import (
    get_model_catalog_item,
    list_model_catalog,
)

router = APIRouter(prefix="/model-center/catalog", tags=["model-center"])


@router.get("", response_model=list[ModelCatalogOut], summary="List model catalog")
async def list_model_catalog_api(
    model_type: str | None = Query(
        default=None, pattern="^(llm|embedding|rerank|vision|asr|tts|image)$"
    ),
    provider: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ModelCatalogOut]:
    return await list_model_catalog(db, model_type=model_type, provider=provider)


@router.get(
    "/{catalog_id}", response_model=ModelCatalogOut, summary="Get model catalog item"
)
async def get_model_catalog_item_api(
    catalog_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> ModelCatalogOut:
    item = await get_model_catalog_item(db, catalog_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="model_catalog_not_found"
        )
    return item
