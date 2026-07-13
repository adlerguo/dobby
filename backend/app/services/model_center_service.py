from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Model, ModelCatalog, ModelChannel
from app.schemas.model_center import (
    ConnectionTestOut,
    MaasChannelOut,
    MaasProbeOut,
    ModelCenterChannelTestOut,
    ModelCenterConnectIn,
    ModelCenterConnectOut,
)
from app.schemas.models import ModelChannelOut, ModelHubOut
from app.services.model_catalog_service import get_model_catalog_item
from app.services.model_service import ensure_model_name_available, load_model_by_name


class ConnectionTestFailed(ValueError):
    def __init__(self, summary: str | None) -> None:
        super().__init__("connection_test_failed")
        self.summary = summary or "connection_test_failed"


async def connect_catalog_model(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    catalog_id: UUID,
    payload: ModelCenterConnectIn,
) -> ModelCenterConnectOut:
    catalog = await get_model_catalog_item(db, catalog_id)
    if catalog is None:
        raise ValueError("model_catalog_not_found")
    validate_connectable_catalog(catalog)
    await ensure_model_name_available(db, payload.runtime_name)

    base_url = payload.base_url or catalog.default_base_url
    # The test_after_create flag is accepted for API compatibility, but this
    # first batch always probes before creating records to avoid failed channels.
    test_result = await probe_transient_catalog_channel(
        catalog=catalog,
        base_url=base_url,
        api_key=payload.api_key,
    )
    if not test_result.ok:
        raise ConnectionTestFailed(test_result.error)

    channel = await create_maas_catalog_channel(
        tenant_id=tenant_id,
        catalog=catalog,
        runtime_name=payload.runtime_name,
        base_url=base_url,
        api_key=payload.api_key,
        weight=payload.weight,
    )
    model = await load_model_by_name(db, payload.runtime_name)
    if model is None:
        raise ValueError("model_create_failed")
    apply_catalog_model_metadata(model, catalog, base_url=base_url)
    await db.commit()
    await db.refresh(model)
    channel = await probe_maas_channel(channel.id)
    stored_channel = await db.get(ModelChannel, channel.id)
    if stored_channel is None:
        raise ValueError("model_channel_create_failed")
    return ModelCenterConnectOut(
        model=ModelHubOut.model_validate(model),
        channel=ModelChannelOut.model_validate(stored_channel),
        test_result=test_result,
    )


async def test_existing_channel(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    channel_id: UUID,
) -> ModelCenterChannelTestOut:
    channel = await db.get(ModelChannel, channel_id)
    if channel is None or channel.tenant_id != tenant_id:
        raise ValueError("channel_not_found")
    maas_channel = await probe_maas_channel(channel_id)
    await db.refresh(channel)
    test_result = ConnectionTestOut(
        ok=maas_channel.health == "ok",
        health=maas_channel.health or "failed",
        error=maas_channel.error,
        embedding_dim=maas_channel.embedding_dim,
    )
    return ModelCenterChannelTestOut(
        channel=ModelChannelOut.model_validate(channel),
        test_result=test_result,
    )


def validate_connectable_catalog(catalog: ModelCatalog) -> None:
    if catalog.model_type == "rerank":
        raise ValueError("model_type_not_supported")
    if catalog.protocol not in {"mock", "openai_compatible"}:
        raise ValueError("protocol_not_supported")


async def probe_transient_catalog_channel(
    *,
    catalog: ModelCatalog,
    base_url: str,
    api_key: str,
) -> ConnectionTestOut:
    body = {
        "model": catalog.model_code,
        "model_type": catalog.model_type,
        "provider": catalog.provider,
        "base_url": base_url,
        "api_key": api_key,
        "protocol": catalog.protocol,
        "request_defaults": catalog_request_defaults(catalog),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{settings.maas_base_url.rstrip('/')}/admin/channels/probe", json=body)
            response.raise_for_status()
            result = MaasProbeOut.model_validate(response.json())
    except httpx.HTTPError as exc:
        raise ValueError("maas_probe_failed") from exc
    return ConnectionTestOut(ok=result.ok, health=result.health, error=result.error, embedding_dim=result.embedding_dim)


async def create_maas_catalog_channel(
    *,
    tenant_id: UUID,
    catalog: ModelCatalog,
    runtime_name: str,
    base_url: str,
    api_key: str,
    weight: int,
) -> MaasChannelOut:
    body = {
        "tenant_id": str(tenant_id),
        "model": runtime_name,
        "model_type": catalog.model_type,
        "provider": catalog.provider,
        "base_url": base_url,
        "api_key": api_key,
        "weight": weight,
        "status": "active",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{settings.maas_base_url.rstrip('/')}/admin/channels", json=body)
            response.raise_for_status()
            return MaasChannelOut.model_validate(response.json())
    except httpx.HTTPError as exc:
        raise ValueError("model_channel_create_failed") from exc


async def probe_maas_channel(channel_id: UUID) -> MaasChannelOut:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{settings.maas_base_url.rstrip('/')}/admin/channels/{channel_id}/health")
            response.raise_for_status()
            return MaasChannelOut.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ValueError("channel_not_found") from exc
        raise ValueError("maas_probe_failed") from exc
    except httpx.HTTPError as exc:
        raise ValueError("maas_probe_failed") from exc


def apply_catalog_model_metadata(model: Model, catalog: ModelCatalog, *, base_url: str) -> None:
    availability = catalog.recommended_parameters.get("availability")
    model.provider = catalog.provider
    model.type = catalog.model_type
    model.display_name = catalog.display_name
    model.description = catalog.description
    model.is_active = True
    model.import_source = "catalog"
    model.model_icon_path = catalog.icon
    model.provider_config = {
        **(model.provider_config or {}),
        "catalog_id": str(catalog.id),
        "catalog_code": catalog.model_code,
        "protocol": catalog.protocol,
        "availability": availability,
        "default_base_url": base_url,
        "connected_at": datetime.now(UTC).isoformat(),
        "supports_streaming": catalog.supports_streaming,
        "supports_tools": catalog.supports_tools,
        "supports_vision": catalog.supports_vision,
        "recommended_parameters": catalog.recommended_parameters or {},
        "request_defaults": catalog_request_defaults(catalog),
    }


def catalog_request_defaults(catalog: ModelCatalog) -> dict:
    excluded = {"availability"}
    return {key: value for key, value in (catalog.recommended_parameters or {}).items() if key not in excluded}
