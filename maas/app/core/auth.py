import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_service_token(
    x_service_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.maas_admin_token
    provided = x_service_token or bearer_token(authorization)
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_service_token")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
