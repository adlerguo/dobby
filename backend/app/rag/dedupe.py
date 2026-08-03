import hashlib
import re


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_text_for_fingerprint(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().casefold()


def text_fingerprint(text: str) -> str:
    normalized = normalize_text_for_fingerprint(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def chunk_content_hash(content: str) -> str:
    return text_fingerprint(content)
