from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import ChannelCreate, ChannelOut, ChannelProbeIn, ChannelProbeOut, ChannelUpdate
from app.services import (
    create_channel,
    delete_channel,
    get_channel,
    list_channels,
    mark_channel_health,
    probe_persisted_channel,
    probe_transient_channel,
    update_channel,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/channels", response_model=list[ChannelOut], summary="List model channels")
async def admin_list_channels(db: AsyncSession = Depends(get_db)) -> list[ChannelOut]:
    return await list_channels(db)


@router.post("/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED, summary="Create model channel")
async def admin_create_channel(payload: ChannelCreate, db: AsyncSession = Depends(get_db)) -> ChannelOut:
    return await create_channel(db, payload)


@router.post("/channels/probe", response_model=ChannelProbeOut, summary="Probe a transient model channel")
async def admin_probe_transient_channel(payload: ChannelProbeIn) -> ChannelProbeOut:
    return await probe_transient_channel(payload)


@router.get("/channels/{channel_id}", response_model=ChannelOut, summary="Get model channel")
async def admin_get_channel(channel_id: UUID, db: AsyncSession = Depends(get_db)) -> ChannelOut:
    try:
        return await get_channel(db, channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel_not_found") from None


@router.patch("/channels/{channel_id}", response_model=ChannelOut, summary="Update model channel")
async def admin_update_channel(
    channel_id: UUID,
    payload: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
) -> ChannelOut:
    try:
        return await update_channel(db, channel_id, payload)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel_not_found") from None


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disable model channel")
async def admin_delete_channel(channel_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    await delete_channel(db, channel_id)


@router.post("/channels/{channel_id}/health", response_model=ChannelOut, summary="Probe model channel")
async def admin_probe_channel(channel_id: UUID, db: AsyncSession = Depends(get_db)) -> ChannelOut:
    try:
        result = await probe_persisted_channel(db, channel_id)
        await mark_channel_health(db, channel_id, result.health)
        return await get_channel(db, channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel_not_found") from None
