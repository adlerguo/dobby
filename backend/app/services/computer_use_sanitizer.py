from typing import Any

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "cookie",
    "session",
    "authorization",
    "mfa",
    "captcha",
    "private_key",
}


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "***" if is_sensitive_key(key) else sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return mask_sensitive_text(value)
    return value


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_KEYS)


def mask_sensitive_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["password=", "token=", "api_key=", "authorization:"]):
        return "***"
    return text
