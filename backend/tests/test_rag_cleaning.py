from app.rag.cleaning import CLEANING_VERSION, clean_text


def test_clean_text_removes_control_chars_but_keeps_tabs_and_newlines() -> None:
    result = clean_text("alpha\x00\tbeta\nline\x08two")

    assert result.text == "alpha\tbeta\nlinetwo"
    assert result.raw_chars == 20
    assert result.cleaned_chars == len(result.text)
    assert result.cleaning_version == CLEANING_VERSION


def test_clean_text_collapses_consecutive_blank_lines() -> None:
    result = clean_text("alpha\n\n\n\nbeta")

    assert result.text == "alpha\n\nbeta"
    assert result.removed_blank_lines == 2
    assert result.removed_lines == 2


def test_clean_text_removes_page_number_lines() -> None:
    result = clean_text("Title\n1\nBody\n- 2 -\n第 3 页\nPage 4 of 10\nEnd")

    assert result.text == "Title\nBody\nEnd"
    assert result.removed_noise_lines == 4
    assert result.removed_lines == 4


def test_clean_text_removes_repeated_short_headers_conservatively() -> None:
    text = "\n".join(
        [
            "Company Confidential",
            "First body paragraph",
            "Company Confidential",
            "Second body paragraph",
            "Company Confidential",
            "Third body paragraph",
        ]
    )

    result = clean_text(text)

    assert "Company Confidential" not in result.text
    assert "First body paragraph" in result.text
    assert result.removed_noise_lines == 3


def test_clean_text_keeps_repeated_section_like_titles() -> None:
    text = "\n".join(
        [
            "1.1 Scope",
            "Body A",
            "1.1 Scope",
            "Body B",
            "1.1 Scope",
            "Body C",
        ]
    )

    result = clean_text(text)

    assert result.text.count("1.1 Scope") == 3
    assert result.removed_noise_lines == 0


def test_clean_text_can_be_disabled() -> None:
    result = clean_text("alpha\n\n\n1\nbeta", {"enabled": False})

    assert result.text == "alpha\n\n\n1\nbeta"
    assert result.removed_lines == 0
