from app.rag.dedupe import (
    chunk_content_hash,
    file_sha256,
    normalize_text_for_fingerprint,
    text_fingerprint,
)


def test_file_sha256_is_stable_for_same_bytes() -> None:
    content = b"same bytes"

    assert file_sha256(content) == file_sha256(content)


def test_text_fingerprint_ignores_whitespace_and_english_case() -> None:
    assert text_fingerprint(" Alpha\n\nBeta  ") == text_fingerprint("alpha beta")
    assert normalize_text_for_fingerprint(" Alpha\n\tBeta ") == "alpha beta"


def test_chunk_content_hash_is_stable() -> None:
    assert chunk_content_hash("Chunk text") == chunk_content_hash(" chunk   text ")


def test_different_text_has_different_fingerprint() -> None:
    assert text_fingerprint("合同审批") != text_fingerprint("报销审批")
