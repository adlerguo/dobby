from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.maas_auth import maas_service_headers
from app.models import Model, ModelChannel
from app.schemas.models import ModelChannelOut, ModelHubCreate, ModelHubUpdate
from app.services.validation import detail_from_integrity_error, normalize_unique_text


async def list_model_hub_models(
    db: AsyncSession,
    *,
    model_type: str | None = None,
    provider: str | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Model]:
    stmt = select(Model).order_by(Model.created_at.desc().nullslast(), Model.name)
    if model_type:
        stmt = stmt.where(Model.type == model_type)
    if provider:
        stmt = stmt.where(Model.provider == provider)
    if is_active is not None:
        stmt = stmt.where(Model.is_active.is_(is_active))
    if display_name:
        like = f"%{display_name.strip()}%"
        stmt = stmt.where((Model.display_name.ilike(like)) | (Model.name.ilike(like)))
    result = await db.execute(stmt.offset(offset).limit(limit))
    return list(result.scalars().all())


async def get_model_hub_model(db: AsyncSession, model_id: UUID) -> Model | None:
    return await db.get(Model, model_id)


async def create_model_hub_model(db: AsyncSession, *, tenant_id: UUID, payload: ModelHubCreate) -> Model:
    await ensure_model_name_available(db, payload.name)

    if payload.default_channel is not None:
        # The MaaS service owns channel secret encryption. Backend calls MaaS admin
        # instead of duplicating encryption or writing api_key_enc directly.
        await create_maas_channel(tenant_id=tenant_id, payload=payload)
        model = await load_model_by_name(db, payload.name)
        if model is None:
            raise ValueError("model_create_failed")
        apply_model_values(model, payload.model_dump(exclude={"default_channel"}))
    else:
        model = Model()
        apply_model_values(model, payload.model_dump(exclude={"default_channel"}))
        db.add(model)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "model_create_conflict")) from exc
    await db.refresh(model)
    return model


async def update_model_hub_model(db: AsyncSession, *, model_id: UUID, payload: ModelHubUpdate) -> Model | None:
    model = await db.get(Model, model_id)
    if model is None:
        return None
    if payload.name is not None:
        await ensure_model_name_available(db, payload.name, exclude_id=model_id)
    values = payload.model_dump(exclude_unset=True)
    apply_model_values(model, values)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "model_update_conflict")) from exc
    await db.refresh(model)
    return model


async def set_model_hub_status(db: AsyncSession, *, model_id: UUID, is_active: bool) -> Model | None:
    model = await db.get(Model, model_id)
    if model is None:
        return None
    model.is_active = is_active
    await db.commit()
    await db.refresh(model)
    return model


async def list_model_channels(db: AsyncSession, *, tenant_id: UUID, model_id: UUID) -> list[ModelChannelOut]:
    result = await db.execute(
        select(ModelChannel)
        .where(
            ModelChannel.model_id == model_id,
            (ModelChannel.tenant_id == tenant_id) | (ModelChannel.tenant_id.is_(None)),
        )
        .order_by(ModelChannel.created_at.desc())
    )
    return [ModelChannelOut.model_validate(channel) for channel in result.scalars().all()]


async def ensure_model_name_available(db: AsyncSession, name: str, *, exclude_id: UUID | None = None) -> None:
    stmt = select(Model.id).where(func.lower(func.btrim(Model.name)) == normalize_unique_text(name))
    if exclude_id is not None:
        stmt = stmt.where(Model.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none() is not None:
        raise ValueError("model_name_exists")


async def load_model_by_name(db: AsyncSession, name: str) -> Model | None:
    result = await db.execute(select(Model).where(func.lower(func.btrim(Model.name)) == normalize_unique_text(name)))
    return result.scalar_one_or_none()


def apply_model_values(model: Model, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


async def create_maas_channel(*, tenant_id: UUID, payload: ModelHubCreate) -> None:
    channel = payload.default_channel
    if channel is None:
        return
    body = {
        "tenant_id": str(tenant_id),
        "model": payload.name,
        "model_type": payload.type,
        "provider": payload.provider,
        "base_url": channel.base_url,
        "api_key": channel.api_key,
        "weight": channel.weight,
        "rpm_limit": channel.rpm_limit,
        "status": channel.status,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{settings.maas_base_url.rstrip('/')}/admin/channels",
                json=body,
                headers=maas_service_headers(),
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError("model_channel_create_failed") from exc
