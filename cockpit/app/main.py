from fastapi import FastAPI

from app.api.v1.assistants import router as assistants_router
from app.api.v1.eval_cases import router as eval_cases_router
from app.api.v1.eval_runs import router as eval_runs_router
from app.api.v1.experiences import router as experiences_router
from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.include_router(health_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(assistants_router, prefix="/api/v1")
app.include_router(eval_cases_router, prefix="/api/v1")
app.include_router(eval_runs_router, prefix="/api/v1")
app.include_router(experiences_router, prefix="/api/v1")
