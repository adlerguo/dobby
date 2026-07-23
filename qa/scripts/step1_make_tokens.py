import json
import os

from app.core.config import settings
from app.core.security import create_jwt


def main() -> None:
    alice_user_id = os.environ["ALICE_USER_ID"]
    alice_tenant_id = os.environ["ALICE_TENANT_ID"]
    bob_tenant_id = os.environ["BOB_TENANT_ID"]
    tokens = {
        "expired_access": create_jwt(
            {"user_id": alice_user_id, "tenant_id": alice_tenant_id, "roles": ["member"], "typ": "access"},
            secret=settings.jwt_secret,
            ttl_seconds=-3600,
        ),
        "tenant_mismatch": create_jwt(
            {"user_id": alice_user_id, "tenant_id": bob_tenant_id, "roles": ["member"], "typ": "access"},
            secret=settings.jwt_secret,
            ttl_seconds=3600,
        ),
        "non_access": create_jwt(
            {"user_id": alice_user_id, "tenant_id": alice_tenant_id, "roles": ["member"], "typ": "not_access"},
            secret=settings.jwt_secret,
            ttl_seconds=3600,
        ),
    }
    print(json.dumps(tokens, ensure_ascii=False))


if __name__ == "__main__":
    main()
