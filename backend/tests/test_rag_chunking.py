from app.rag.chunking import chunk_document, chunk_text


def test_simple_strategy_chunks_text() -> None:
    chunks = chunk_document("abcdef", strategy="simple", chunk_size=3, overlap=1)

    assert [chunk.content for chunk in chunks] == ["abc", "cde", "ef"]
    assert all(chunk.meta["chunk_strategy"] == "simple" for chunk in chunks)


def test_paragraph_strategy_aggregates_paragraphs() -> None:
    chunks = chunk_document(
        "alpha\n\nbeta\n\ngamma", strategy="paragraph", chunk_size=20, overlap=2
    )

    assert len(chunks) == 1
    assert chunks[0].content == "alpha\n\nbeta\n\ngamma"
    assert chunks[0].meta["chunk_method"] == "paragraph_window"
    assert chunk_text("alpha\n\nbeta")[0].meta["chunk_strategy"] == "paragraph"


def test_markdown_heading_strategy_writes_heading_path() -> None:
    chunks = chunk_document(
        "# Root\nIntro\n## Child\nDetails", strategy="markdown_heading", chunk_size=100
    )

    assert len(chunks) == 2
    assert chunks[0].meta["heading_path"] == ["Root"]
    assert chunks[1].meta["heading_path"] == ["Root", "Child"]
    assert chunks[1].meta["title_path"] == ["Root", "Child"]
    assert chunks[1].meta["chunk_strategy"] == "markdown_heading"


def test_numbered_section_strategy_writes_section_meta() -> None:
    chunks = chunk_document(
        "一、总则\n正文\n1.1 适用范围\n更多正文",
        strategy="numbered_section",
        chunk_size=100,
    )

    assert len(chunks) == 2
    assert chunks[0].meta["section_no"] == "一"
    assert chunks[0].meta["section_title"] == "总则"
    assert chunks[1].meta["section_no"] == "1.1"
    assert chunks[1].meta["section_title"] == "适用范围"


def test_long_structured_section_is_split_with_parent_seq_and_split_index() -> None:
    chunks = chunk_document(
        "# Long\n" + "a" * 30,
        strategy="markdown_heading",
        chunk_size=12,
        overlap=2,
    )

    assert len(chunks) > 1
    assert {chunk.meta["parent_seq"] for chunk in chunks} == {0}
    assert [chunk.meta["split_index"] for chunk in chunks] == list(range(len(chunks)))


def test_unknown_strategy_falls_back_to_simple() -> None:
    chunks = chunk_document("alpha beta", strategy="unknown", chunk_size=50)

    assert len(chunks) == 1
    assert chunks[0].meta["chunk_strategy"] == "simple"


def test_structured_strategy_with_no_matches_falls_back_to_simple() -> None:
    chunks = chunk_document("plain text", strategy="markdown_heading", chunk_size=50)

    assert len(chunks) == 1
    assert chunks[0].meta["chunk_strategy"] == "simple"
    assert chunks[0].meta["fallback_chunking"] is True
    assert chunks[0].meta["requested_chunk_strategy"] == "markdown_heading"


def test_empty_text_returns_empty_list() -> None:
    assert chunk_document("", strategy="paragraph") == []


def test_invalid_overlap_cannot_dead_loop() -> None:
    chunks = chunk_document("abcdef", strategy="simple", chunk_size=3, overlap=3)

    assert [chunk.content for chunk in chunks] == ["abc", "def"]
