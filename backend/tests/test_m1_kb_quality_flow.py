from uuid import uuid4

from app.rag.cleaning import CleanTextResult
from app.rag.chunking import chunk_document
from app.rag.dedupe import chunk_content_hash, file_sha256, text_fingerprint
from app.rag.ingest import (
    build_chunk_ingest_meta,
    build_ingest_success_meta,
    document_source_meta,
)
from app.rag.retrieve import Candidate, source_fields
from app.services.kb_service import build_upload_meta


def make_cleaning_result(text: str = "# 标题\n正文") -> CleanTextResult:
    return CleanTextResult(
        text=text,
        raw_chars=len(text) + 10,
        cleaned_chars=len(text),
        raw_lines=5,
        cleaned_lines=2,
        removed_lines=3,
        removed_blank_lines=1,
        removed_noise_lines=2,
        cleaning_version="m1_v1",
    )


class FakeDocument:
    def __init__(self, *, name: str = "制度.md", meta: dict | None = None) -> None:
        self.name = name
        self.meta = meta or {}


def test_m1_upload_meta_keeps_batch_hash_duplicate_and_source() -> None:
    meta = build_upload_meta(
        object_name="object/path",
        extra_meta={"batch_id": "batch-1", "source": {"tags": ["制度"]}},
        content_sha256=file_sha256(b"same file"),
        duplicate={"id": uuid4(), "name": "old.md"},
        filename="制度.md",
    )

    assert meta["object_name"] == "object/path"
    assert meta["batch_id"] == "batch-1"
    assert meta["file_sha256"] == file_sha256(b"same file")
    assert meta["duplicate"]["status"] == "file_duplicate"
    assert meta["source"]["source_name"] == "制度.md"
    assert meta["source"]["source_type"] == "upload"
    assert meta["source"]["tags"] == ["制度"]
    assert meta["warnings"][0]["code"] == "file_duplicate"


def test_m1_ingest_meta_keeps_cleaning_fingerprint_chunking_and_existing_fields() -> None:
    fingerprint = text_fingerprint("# 标题\n正文")
    meta = build_ingest_success_meta(
        document_meta={
            "batch_id": "batch-1",
            "file_sha256": "hash",
            "source": {"source_name": "制度手册", "source_type": "upload"},
        },
        cleaning_result=make_cleaning_result(),
        fingerprint=fingerprint,
        text_duplicate={"id": uuid4(), "name": "same-content.md"},
        chunk_count=2,
        embedding_dim=1536,
        chunk_strategy="markdown_heading",
        chunk_method="markdown_heading",
        fallback_chunking=False,
    )

    assert meta["batch_id"] == "batch-1"
    assert meta["file_sha256"] == "hash"
    assert meta["source"]["source_name"] == "制度手册"
    assert meta["duplicate"]["status"] == "text_duplicate"
    assert meta["text_fingerprint"] == fingerprint
    ingest_task = meta["ingest_task"]
    assert ingest_task["status"] == "done"
    assert ingest_task["chunk_count"] == 2
    assert ingest_task["embedding_dim"] == 1536
    assert ingest_task["cleaned_chars"] == len("# 标题\n正文")
    assert ingest_task["text_fingerprint"] == fingerprint
    assert ingest_task["chunk_strategy"] == "markdown_heading"
    assert ingest_task["fallback_chunking"] is False


def test_m1_chunk_meta_keeps_structure_hash_cleaning_duplicate_and_source() -> None:
    chunks = chunk_document(
        "# 总则\n同一段内容\n同一段内容",
        strategy="markdown_heading",
        chunk_size=100,
        overlap=0,
    )
    source_meta = document_source_meta(
        FakeDocument(
            meta={
                "source": {
                    "source_name": "制度手册",
                    "source_type": "manual",
                    "tags": ["HR"],
                    "version_label": "v2",
                    "published_at": "2026-01-01",
                }
            }
        )
    )
    first = build_chunk_ingest_meta(
        chunks[0].meta,
        content_hash=chunk_content_hash(chunks[0].content),
        cleaning_version="m1_v1",
        duplicate_in_document=False,
        source_meta=source_meta,
    )
    duplicate = build_chunk_ingest_meta(
        {"chunk_strategy": "paragraph", "chunk_method": "paragraph_window"},
        content_hash=first["content_hash"],
        cleaning_version="m1_v1",
        duplicate_in_document=True,
        source_meta=source_meta,
    )

    assert first["content_hash"]
    assert first["cleaning_version"] == "m1_v1"
    assert first["chunk_strategy"] == "markdown_heading"
    assert first["heading_path"] == ["总则"]
    assert first["source_name"] == "制度手册"
    assert first["source_type"] == "manual"
    assert first["tags"] == ["HR"]
    assert first["version_label"] == "v2"
    assert first["published_at"] == "2026-01-01"
    assert "duplicate_in_document" not in first
    assert duplicate["duplicate_in_document"] is True


def test_m1_retrieve_source_fields_supports_legacy_meta_without_source() -> None:
    candidate = Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="legacy.md",
        seq=0,
        content="legacy content",
        meta={},
        doc_meta={},
    )

    assert source_fields(candidate) == {
        "source_name": None,
        "source_type": None,
        "tags": [],
        "version_label": None,
        "published_at": None,
    }
