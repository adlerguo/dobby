from fastapi import FastAPI

from app.api.v1.agents import router as agents_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.evals import router as evals_router
from app.api.v1.health import router as health_router
from app.api.v1.kbs import router as kbs_router
from app.api.v1.model_catalog import router as model_catalog_router
from app.api.v1.model_center import router as model_center_router
from app.api.v1.models import router as models_router
from app.api.v1.publish import router as publish_router
from app.api.v1.public_agents import router as public_agents_router
from app.api.v1.rbac import router as rbac_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.tools import router as tools_router
from app.api.v1.users import router as users_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import settings
from app.core.middleware import BodySizeLimitMiddleware


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url="/api/v1/openapi.json",
)
app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)

app.include_router(health_router)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(tenants_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(rbac_router, prefix="/api/v1")
app.include_router(kbs_router, prefix="/api/v1")
app.include_router(model_catalog_router, prefix="/api/v1")
app.include_router(model_center_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(publish_router, prefix="/api/v1")
app.include_router(public_agents_router, prefix="/api/v1")
app.include_router(tools_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(evals_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
