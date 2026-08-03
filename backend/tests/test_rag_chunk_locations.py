from app.rag.chunking import TextBlock, chunk_document_blocks


def test_pdf_blocks_write_page_range() -> None:
    chunks = chunk_document_blocks(
        [
            TextBlock(text="Page one content", page=1, paragraph=1, block_index=1),
            TextBlock(text="Page two content", page=2, paragraph=2, block_index=2),
        ],
        strategy="paragraph",
        chunk_size=200,
        overlap=0,
    )

    assert len(chunks) == 1
    assert chunks[0].meta["page_start"] == 1
    assert chunks[0].meta["page_end"] == 2
    assert chunks[0].meta["block_start"] == 1
    assert chunks[0].meta["block_end"] == 2


def test_text_blocks_write_paragraph_range() -> None:
    chunks = chunk_document_blocks(
        [
            TextBlock(text="Alpha", paragraph=1, block_index=1),
            TextBlock(text="Beta", paragraph=2, block_index=2),
        ],
        strategy="paragraph",
        chunk_size=200,
        overlap=0,
    )

    assert chunks[0].meta["page_start"] is None
    assert chunks[0].meta["paragraph_start"] == 1
    assert chunks[0].meta["paragraph_end"] == 2


def test_multiple_chunks_keep_location_ranges() -> None:
    chunks = chunk_document_blocks(
        [
            TextBlock(text="Alpha " * 8, page=1, paragraph=1, block_index=1),
            TextBlock(text="Beta " * 8, page=2, paragraph=2, block_index=2),
        ],
        strategy="simple",
        chunk_size=20,
        overlap=0,
    )

    assert len(chunks) > 1
    assert chunks[0].meta["block_start"] == 1
    assert chunks[-1].meta["block_end"] == 2
    assert any(chunk.meta["page_start"] == 2 for chunk in chunks)


def test_empty_location_does_not_raise() -> None:
    chunks = chunk_document_blocks(
        [TextBlock(text="Alpha", block_index=None)],
        strategy="paragraph",
        chunk_size=100,
        overlap=0,
    )

    assert chunks[0].meta["page_start"] is None
    assert chunks[0].meta["paragraph_start"] is None
    assert chunks[0].meta["block_start"] == 1
    assert chunks[0].meta["chunk_strategy"] == "paragraph"
