import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_jwt(payload: dict[str, Any], *, secret: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    token_payload = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}

    header_raw = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_raw = _b64url_encode(json.dumps(token_payload, separators=(",", ":"), default=str).encode("utf-8"))
    signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_raw}.{payload_raw}.{_b64url_encode(signature)}"


def decode_jwt(token: str, *, secret: str) -> dict[str, Any]:
    try:
        header_raw, payload_raw, signature_raw = token.split(".", 2)
        signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        signature = _b64url_decode(signature_raw)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_signature")

        header = json.loads(_b64url_decode(header_raw))
        if header.get("alg") != "HS256":
            raise ValueError("invalid_algorithm")

        payload = json.loads(_b64url_decode(payload_raw))
        exp = int(payload.get("exp", 0))
        if exp < int(datetime.now(UTC).timestamp()):
            raise ValueError("token_expired")
        return payload
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_token") from exc
