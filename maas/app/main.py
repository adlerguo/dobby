import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.openai import router as openai_router
from app.core.config import settings
from app.core.health_probe import channel_health_probe_loop
from app.core.middleware import BodySizeLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(channel_health_probe_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(openai_router)
