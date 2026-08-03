import logging
from collections.abc import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from app.api.v1.agents import router as agents_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.copilot_tasks import router as copilot_tasks_router
from app.api.v1.computer_use import router as computer_use_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.evals import router as evals_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.health import router as health_router
from app.api.v1.incidents import router as incidents_router
from app.api.v1.kbs import router as kbs_router
from app.api.v1.model_catalog import router as model_catalog_router
from app.api.v1.model_center import router as model_center_router
from app.api.v1.models import router as models_router
from app.api.v1.openai_compat import router as openai_compat_router
from app.api.v1.publish import router as publish_router
from app.api.v1.public_agents import router as public_agents_router
from app.api.v1.rbac import router as rbac_router
from app.api.v1.security_evals import router as security_evals_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.tools import router as tools_router
from app.api.v1.users import router as users_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import settings
from app.core.errors import AppError
from app.core.middleware import BodySizeLimitMiddleware
from app.core.database import SessionLocal
from app.services.copilot_task_recovery import recover_interrupted_copilot_tasks

try:
    import psycopg
except ImportError:  # pragma: no cover - psycopg is installed in the service image.
    psycopg = None


logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url="/api/v1/openapi.json",
)
app.add_middleware(
    BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes
)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
            }
        },
    )


async def database_unavailable_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    lines = str(exc).splitlines()
    first_line = lines[0] if lines else repr(exc)
    logger.error(
        "database_unavailable %s: %s path=%s",
        exc.__class__.__name__,
        first_line,
        request.url.path,
    )
    logger.debug(
        "database_unavailable traceback", exc_info=(type(exc), exc, exc.__traceback__)
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "Database is temporarily unavailable.",
            }
        },
    )


app.add_exception_handler(AppError, app_error_handler)


def database_exception_classes() -> Iterable[type[Exception]]:
    yield OperationalError
    yield InterfaceError
    if psycopg is not None:
        yield psycopg.OperationalError
        yield psycopg.InterfaceError
        connection_exception = getattr(psycopg.errors, "ConnectionException", None)
        if connection_exception is not None:
            yield connection_exception


for exception_class in database_exception_classes():
    app.add_exception_handler(exception_class, database_unavailable_handler)


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
app.include_router(openai_compat_router, prefix="/api/v1")
app.include_router(tools_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(copilot_router, prefix="/api/v1")
app.include_router(copilot_tasks_router, prefix="/api/v1")
app.include_router(computer_use_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(evals_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(security_evals_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")


@app.on_event("startup")
async def recover_copilot_tasks_on_startup() -> None:
    try:
        async with SessionLocal() as db:
            result = await recover_interrupted_copilot_tasks(db)
            if any(result.values()):
                logger.info("copilot task recovery: %s", result)
    except Exception as exc:  # pragma: no cover - protects startup before migrations.
        logger.warning("copilot task recovery skipped: %s", exc)
