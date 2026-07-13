from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    service: str
    status: str
    version: str


@router.get("/healthz", response_model=HealthOut, summary="Sandbox health check")
async def healthz() -> HealthOut:
    return HealthOut(
        service=settings.service_name,
        status="ok",
        version=settings.app_version,
    )

