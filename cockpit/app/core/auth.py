from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status
from jwt import InvalidTokenError

from app.core.config import settings


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str | None = None
    token: str | None = None


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token_required")
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_authorization")
    return token


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_org_id: str | None = Header(default=None, alias="x-org-id"),
) -> CurrentUser:
    # 关键安全逻辑：只信任 HS256 JWT 中的 userId；x-org-id 只是组织上下文，不作为身份凭据。
    token = _extract_bearer_token(authorization)
    try:
        claims = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
            issuer="wanwu",
            options={"require": ["exp", "nbf", "iss", "sub"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc

    if claims.get("sub") != "user":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_subject")

    user_id = claims.get("userId")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_user")

    return CurrentUser(user_id=str(user_id), org_id=x_org_id, token=token)
