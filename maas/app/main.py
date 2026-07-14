from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.openai import router as openai_router
from app.core.config import settings
from app.core.middleware import BodySizeLimitMiddleware


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)
app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(openai_router)
