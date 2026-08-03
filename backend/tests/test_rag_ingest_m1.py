from app.rag.cleaning import CleanTextResult
from app.rag.dedupe import chunk_content_hash
from app.rag.ingest import (
    build_chunk_ingest_meta,
    build_ingest_success_meta,
    clean_located_blocks,
    resolve_chunking_config,
)
from app.rag.retrieve import Candidate, source_fields


def make_cleaning_result() -> CleanTextResult:
    return CleanTextResult(
        text="cleaned text",
        raw_chars=20,
        cleaned_chars=12,
        raw_lines=5,
        cleaned_lines=3,
        removed_lines=2,
        removed_blank_lines=1,
        removed_noise_lines=1,
        cleaning_version="m1_v1",
    )


def test_build_ingest_success_meta_adds_cleaning_stats_and_fingerprint() -> None:
    meta = build_ingest_success_meta(
        document_meta={"object_name": "object", "duplicate": {"status": "none"}},
        cleaning_result=make_cleaning_result(),
        fingerprint="fingerprint",
        text_duplicate=None,
        chunk_count=3,
        embedding_dim=1536,
        chunk_strategy="markdown_heading",
        chunk_method="markdown_heading",
        fallback_chunking=False,
        block_count=2,
        located_chunk_count=3,
        page_located_chunk_count=1,
    )

    assert meta["object_name"] == "object"
    assert meta["text_fingerprint"] == "fingerprint"
    assert meta["duplicate"] == {"status": "none"}
    assert meta["ingest_task"] == {
        "status": "done",
        "raw_chars": 20,
        "cleaned_chars": 12,
        "raw_lines": 5,
        "cleaned_lines": 3,
        "removed_lines": 2,
        "removed_blank_lines": 1,
        "removed_noise_lines": 1,
        "cleaning_version": "m1_v1",
        "text_fingerprint": "fingerprint",
        "chunk_strategy": "markdown_heading",
        "chunk_method": "markdown_heading",
        "fallback_chunking": False,
        "chunk_count": 3,
        "embedding_dim": 1536,
        "block_count": 2,
        "located_chunk_count": 3,
        "page_located_chunk_count": 1,
    }


def test_build_ingest_success_meta_marks_text_duplicate_without_overriding_file_duplicate() -> None:
    text_duplicate = {"id": "doc-1", "name": "same.md"}
    meta = build_ingest_success_meta(
        document_meta={"duplicate": {"status": "none"}},
        cleaning_result=make_cleaning_result(),
        fingerprint="fingerprint",
        text_duplicate=text_duplicate,
        chunk_count=1,
        embedding_dim=1536,
    )

    assert meta["duplicate"]["status"] == "text_duplicate"
    assert meta["duplicate"]["matched_document_name"] == "same.md"
    assert meta["warnings"][0]["code"] == "text_duplicate"

    file_duplicate_meta = build_ingest_success_meta(
        document_meta={"duplicate": {"status": "file_duplicate"}},
        cleaning_result=make_cleaning_result(),
        fingerprint="fingerprint",
        text_duplicate=text_duplicate,
        chunk_count=1,
        embedding_dim=1536,
    )

    assert file_duplicate_meta["duplicate"] == {"status": "file_duplicate"}
    assert "warnings" not in file_duplicate_meta


def test_build_chunk_ingest_meta_adds_content_hash_and_duplicate_flag() -> None:
    content_hash = chunk_content_hash("same content")

    first = build_chunk_ingest_meta(
        {"chunk_method": "paragraph_window"},
        content_hash=content_hash,
        cleaning_version="m1_v1",
        duplicate_in_document=False,
    )
    duplicate = build_chunk_ingest_meta(
        {"chunk_method": "paragraph_window"},
        content_hash=content_hash,
        cleaning_version="m1_v1",
        duplicate_in_document=True,
    )

    assert first["content_hash"] == content_hash
    assert first["cleaning_version"] == "m1_v1"
    assert "duplicate_in_document" not in first
    assert duplicate["duplicate_in_document"] is True


def test_build_chunk_ingest_meta_inherits_document_source() -> None:
    meta = build_chunk_ingest_meta(
        {"chunk_strategy": "markdown_heading", "heading_path": ["Root"]},
        content_hash="hash",
        cleaning_version="m1_v1",
        duplicate_in_document=False,
        source_meta={
            "source_name": "制度手册",
            "source_type": "upload",
            "tags": ["制度", "HR"],
            "version_label": "v2",
            "published_at": "2026-01-01",
        },
    )

    assert meta["chunk_strategy"] == "markdown_heading"
    assert meta["heading_path"] == ["Root"]
    assert meta["content_hash"] == "hash"
    assert meta["cleaning_version"] == "m1_v1"
    assert meta["source_name"] == "制度手册"
    assert meta["source_type"] == "upload"
    assert meta["tags"] == ["制度", "HR"]
    assert meta["version_label"] == "v2"
    assert meta["published_at"] == "2026-01-01"


def test_clean_located_blocks_preserves_page_paragraph_and_block_index() -> None:
    class Block:
        def __init__(self, text, page, paragraph, block_index) -> None:
            self.text = text
            self.page = page
            self.paragraph = paragraph
            self.block_index = block_index

    blocks = clean_located_blocks(
        [
            Block("Header", 1, 1, 1),
            Block("正文内容", 2, 2, 2),
        ],
        cleaned_text="正文内容",
        config={},
    )

    assert len(blocks) == 1
    assert blocks[0].text == "正文内容"
    assert blocks[0].page == 2
    assert blocks[0].paragraph == 2
    assert blocks[0].block_index == 2


def test_resolve_chunking_config_reads_nested_config_and_legacy_defaults() -> None:
    nested = resolve_chunking_config(
        {
            "chunk_size": 1000,
            "overlap": 100,
            "chunking": {
                "strategy": "numbered_section",
                "chunk_size": 500,
                "overlap": 50,
            },
        }
    )
    legacy = resolve_chunking_config({"chunk_size": 900, "overlap": 90})

    assert nested == {
        "strategy": "numbered_section",
        "chunk_size": 500,
        "overlap": 50,
    }
    assert legacy == {"strategy": "paragraph", "chunk_size": 900, "overlap": 90}


def test_retrieve_source_fields_prefers_chunk_meta_and_falls_back_to_document_source() -> None:
    from uuid import uuid4

    fallback_candidate = Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="doc.md",
        seq=1,
        content="content",
        meta={},
        doc_meta={
            "source": {
                "source_name": "文档来源",
                "source_type": "upload",
                "tags": ["A"],
                "version_label": "v1",
                "published_at": "2026-01-01",
            }
        },
    )
    chunk_candidate = Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="doc.md",
        seq=1,
        content="content",
        meta={"source_name": "片段来源", "tags": ["B"]},
        doc_meta=fallback_candidate.doc_meta,
    )

    assert source_fields(fallback_candidate) == {
        "source_name": "文档来源",
        "source_type": "upload",
        "tags": ["A"],
        "version_label": "v1",
        "published_at": "2026-01-01",
    }
    assert source_fields(chunk_candidate)["source_name"] == "片段来源"
    assert source_fields(chunk_candidate)["tags"] == ["B"]


def test_retrieve_source_fields_and_location_fields_can_be_combined() -> None:
    from app.rag.retrieve import location_fields
    from uuid import uuid4

    candidate = Candidate(
        id=uuid4(),
        doc_id=uuid4(),
        doc_name="doc.md",
        seq=1,
        content="content",
        meta={
            "page_start": 1,
            "page_end": 2,
            "paragraph_start": 3,
            "paragraph_end": 4,
            "block_start": 5,
            "block_end": 6,
        },
        doc_meta={},
    )

    assert location_fields(candidate.meta) == {
        "page_start": 1,
        "page_end": 2,
        "paragraph_start": 3,
        "paragraph_end": 4,
        "block_start": 5,
        "block_end": 6,
    }
