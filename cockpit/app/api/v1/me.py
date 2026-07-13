from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def me(current_user: CurrentUser = Depends(get_current_user)) -> dict[str, str | None]:
    return {
        "user_id": current_user.user_id,
        "org_id": current_user.org_id,
        "version": settings.app_version,
    }

