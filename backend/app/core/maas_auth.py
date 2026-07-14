from app.core.config import settings


def maas_service_headers() -> dict[str, str]:
    return {"X-Service-Token": settings.maas_admin_token or ""}
