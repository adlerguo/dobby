from fastapi import FastAPI

from app.api.exec import router as exec_router
from app.api.health import router as health_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.include_router(health_router)
app.include_router(exec_router)
