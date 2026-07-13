from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.clients.wanwu_bff import WanwuBFFClient
from app.core.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/assistants", tags=["assistants"])


@router.get("")
async def list_assistants(
    name: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if not current_user.token:
        raise HTTPException(status_code=401, detail="token_required")
    client = WanwuBFFClient()
    try:
        return await client.list_assistants_with_token(current_user.token, current_user.org_id, name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
