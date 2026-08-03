from dataclasses import dataclass
import re
from typing import Any


SUPPORTED_CHUNK_STRATEGIES = {
    "simple",
    "paragraph",
    "markdown_heading",
    "numbered_section",
}
DEFAULT_CHUNK_SIZE = 800
DEFAULT_OVERLAP = 80

MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NUMBERED_SECTION_PATTERNS = (
    re.compile(r"^(?P<no>[一二三四五六七八九十百千]+)、\s*(?P<title>.+?)\s*$"),
    re.compile(r"^（(?P<no>[一二三四五六七八九十百千]+)）\s*(?P<title>.+?)\s*$"),
    re.compile(r"^(?P<no>\d+(?:\.\d+)+)\s+(?P<title>.+?)\s*$"),
    re.compile(r"^(?P<no>\d+(?:\.\d+)*)[.、]\s+(?P<title>.+?)\s*$"),
    re.compile(r"^第\s*(?P<no>[一二三四五六七八九十百千\d]+)\s*章\s*(?P<title>.+?)\s*$"),
)


@dataclass(frozen=True)
class TextChunk:
    seq: int
    content: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int | None = None
    paragraph: int | None = None
    block_index: int | None = None


LOCATION_KEYS = (
    "page_start",
    "page_end",
    "paragraph_start",
    "paragraph_end",
    "block_start",
    "block_end",
)


def chunk_text(
    text: str, *, chunk_size: int = 800, overlap: int = 80
) -> list[TextChunk]:
    return chunk_document(
        text, strategy="paragraph", chunk_size=chunk_size, overlap=overlap
    )


def chunk_document(
    text: str,
    *,
    strategy: str = "simple",
    chunk_size: int = 800,
    overlap: int = 80,
) -> list[TextChunk]:
    chunk_size, overlap = normalize_chunk_window(chunk_size, overlap)
    normalized_strategy = normalize_strategy(strategy)
    try:
        if normalized_strategy == "simple":
            chunks = simple_chunks(text, chunk_size=chunk_size, overlap=overlap)
        elif normalized_strategy == "paragraph":
            chunks = paragraph_chunks(text, chunk_size=chunk_size, overlap=overlap)
        elif normalized_strategy == "markdown_heading":
            chunks = markdown_heading_chunks(
                text, chunk_size=chunk_size, overlap=overlap
            )
        elif normalized_strategy == "numbered_section":
            chunks = numbered_section_chunks(
                text, chunk_size=chunk_size, overlap=overlap
            )
        else:
            chunks = []
    except Exception:
        return mark_fallback(
            simple_chunks(text, chunk_size=chunk_size, overlap=overlap),
            requested_strategy=normalized_strategy,
        )

    if chunks:
        return chunks
    if normalized_strategy == "simple":
        return []
    return mark_fallback(
        simple_chunks(text, chunk_size=chunk_size, overlap=overlap),
        requested_strategy=normalized_strategy,
    )


def chunk_document_blocks(
    blocks: list[Any],
    *,
    strategy: str = "simple",
    chunk_size: int = 800,
    overlap: int = 80,
) -> list[TextChunk]:
    text_blocks = normalize_text_blocks(blocks)
    if not text_blocks:
        return []

    text, ranges = join_blocks_with_ranges(text_blocks)
    chunks = chunk_document(
        text, strategy=strategy, chunk_size=chunk_size, overlap=overlap
    )
    if not chunks:
        return []

    located: list[TextChunk] = []
    search_start = 0
    for chunk in chunks:
        start = text.find(chunk.content, search_start)
        if start < 0:
            start = text.find(chunk.content)
        if start < 0:
            location = empty_location()
        else:
            end = start + len(chunk.content)
            location = location_for_range(start, end, ranges)
            search_start = max(start + 1, search_start)
        meta = dict(chunk.meta)
        meta.update(location)
        located.append(TextChunk(seq=chunk.seq, content=chunk.content, meta=meta))
    return located


def normalize_chunk_window(chunk_size: int, overlap: int) -> tuple[int, int]:
    try:
        normalized_size = int(chunk_size)
    except (TypeError, ValueError):
        normalized_size = DEFAULT_CHUNK_SIZE
    try:
        normalized_overlap = int(overlap)
    except (TypeError, ValueError):
        normalized_overlap = DEFAULT_OVERLAP

    normalized_size = max(normalized_size, 1)
    normalized_overlap = max(normalized_overlap, 0)
    if normalized_overlap >= normalized_size:
        normalized_overlap = max(normalized_size // 10, 0)
    return normalized_size, normalized_overlap


def normalize_strategy(strategy: str | None) -> str:
    normalized = (strategy or "simple").strip().lower()
    return normalized if normalized in SUPPORTED_CHUNK_STRATEGIES else "simple"


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def normalize_text_blocks(blocks: list[Any]) -> list[TextBlock]:
    normalized: list[TextBlock] = []
    for index, block in enumerate(blocks, start=1):
        text = normalize_text(str(getattr(block, "text", "") or ""))
        if not text:
            continue
        normalized.append(
            TextBlock(
                text=text,
                page=to_int_or_none(getattr(block, "page", None)),
                paragraph=to_int_or_none(getattr(block, "paragraph", None)),
                block_index=to_int_or_none(getattr(block, "block_index", None))
                or index,
            )
        )
    return normalized


def join_blocks_with_ranges(
    blocks: list[TextBlock],
) -> tuple[str, list[tuple[int, int, TextBlock]]]:
    parts: list[str] = []
    ranges: list[tuple[int, int, TextBlock]] = []
    cursor = 0
    for block in blocks:
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(block.text)
        cursor += len(block.text)
        ranges.append((start, cursor, block))
    return "".join(parts), ranges


def location_for_range(
    start: int, end: int, ranges: list[tuple[int, int, TextBlock]]
) -> dict[str, int | None]:
    matched = [
        block
        for block_start, block_end, block in ranges
        if block_end > start and block_start < end
    ]
    if not matched:
        return empty_location()
    return {
        "page_start": min_value(block.page for block in matched),
        "page_end": max_value(block.page for block in matched),
        "paragraph_start": min_value(block.paragraph for block in matched),
        "paragraph_end": max_value(block.paragraph for block in matched),
        "block_start": min_value(block.block_index for block in matched),
        "block_end": max_value(block.block_index for block in matched),
    }


def empty_location() -> dict[str, None]:
    return {key: None for key in LOCATION_KEYS}


def min_value(values) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def max_value(values) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def simple_chunks(
    text: str, *, chunk_size: int, overlap: int, base_meta: dict[str, Any] | None = None
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    meta = {"chunk_method": "simple_window", "chunk_strategy": "simple"}
    meta.update(base_meta or {})
    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        content = normalized[start:end].strip()
        if content:
            chunks.append(build_chunk(len(chunks), content, meta, split_index=len(chunks)))
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def paragraph_chunks(
    text: str, *, chunk_size: int, overlap: int, base_meta: dict[str, Any] | None = None
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = [
        paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()
    ]
    chunks: list[TextChunk] = []
    current = ""
    meta = {"chunk_method": "paragraph_window", "chunk_strategy": "paragraph"}
    meta.update(base_meta or {})

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(build_chunk(len(chunks), current, meta))
                current = ""
            chunks.extend(
                split_long_content(
                    paragraph,
                    start_seq=len(chunks),
                    chunk_size=chunk_size,
                    overlap=overlap,
                    base_meta=meta,
                )
            )
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(build_chunk(len(chunks), current, meta))
        current = paragraph

    if current:
        chunks.append(build_chunk(len(chunks), current, meta))

    return chunks


def markdown_heading_chunks(
    text: str, *, chunk_size: int, overlap: int
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    sections: list[tuple[list[str], str]] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_path: list[str] = []
    saw_heading = False

    for line in normalized.splitlines():
        match = MARKDOWN_HEADING_RE.match(line.strip())
        if not match:
            current_lines.append(line)
            continue

        saw_heading = True
        if current_lines and current_path:
            sections.append((current_path[:], "\n".join(current_lines).strip()))
        level = len(match.group(1))
        title = match.group(2).strip()
        heading_stack = heading_stack[: level - 1]
        heading_stack.append(title)
        current_path = heading_stack[:]
        current_lines = [line.strip()]

    if current_lines and current_path:
        sections.append((current_path[:], "\n".join(current_lines).strip()))

    if not saw_heading or not sections:
        return []

    chunks: list[TextChunk] = []
    for path, content in sections:
        if not content:
            continue
        meta = {
            "chunk_method": "markdown_heading",
            "chunk_strategy": "markdown_heading",
            "heading_path": path,
            "title_path": path,
        }
        chunks.extend(
            split_structured_content(
                content,
                start_seq=len(chunks),
                chunk_size=chunk_size,
                overlap=overlap,
                base_meta=meta,
            )
        )
    return chunks


def numbered_section_chunks(
    text: str, *, chunk_size: int, overlap: int
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    sections: list[tuple[str, str, str]] = []
    current_no = ""
    current_title = ""
    current_lines: list[str] = []
    saw_section = False

    for line in normalized.splitlines():
        match = match_numbered_section(line.strip())
        if match is None:
            current_lines.append(line)
            continue

        saw_section = True
        if current_lines and current_no:
            sections.append((current_no, current_title, "\n".join(current_lines).strip()))
        current_no, current_title = match
        current_lines = [line.strip()]

    if current_lines and current_no:
        sections.append((current_no, current_title, "\n".join(current_lines).strip()))

    if not saw_section or not sections:
        return []

    chunks: list[TextChunk] = []
    for section_no, section_title, content in sections:
        if not content:
            continue
        meta = {
            "chunk_method": "numbered_section",
            "chunk_strategy": "numbered_section",
            "section_no": section_no,
            "section_title": section_title,
        }
        chunks.extend(
            split_structured_content(
                content,
                start_seq=len(chunks),
                chunk_size=chunk_size,
                overlap=overlap,
                base_meta=meta,
            )
        )
    return chunks


def match_numbered_section(line: str) -> tuple[str, str] | None:
    if not line:
        return None
    for pattern in NUMBERED_SECTION_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group("no"), match.group("title").strip()
    return None


def split_structured_content(
    content: str,
    *,
    start_seq: int,
    chunk_size: int,
    overlap: int,
    base_meta: dict[str, Any],
) -> list[TextChunk]:
    if len(content) <= chunk_size:
        return [build_chunk(start_seq, content, base_meta)]
    return split_long_content(
        content,
        start_seq=start_seq,
        chunk_size=chunk_size,
        overlap=overlap,
        base_meta=base_meta,
        parent_seq=start_seq,
    )


def split_long_content(
    content: str,
    *,
    start_seq: int,
    chunk_size: int,
    overlap: int,
    base_meta: dict[str, Any],
    parent_seq: int | None = None,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        part = content[start:end].strip()
        if part:
            split_index = len(chunks)
            chunks.append(
                build_chunk(
                    start_seq + split_index,
                    part,
                    base_meta,
                    parent_seq=parent_seq,
                    split_index=split_index,
                )
            )
        if end == len(content):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunk(
    seq: int,
    content: str,
    meta: dict[str, Any],
    *,
    parent_seq: int | None = None,
    split_index: int | None = None,
) -> TextChunk:
    chunk_meta = dict(meta)
    if parent_seq is not None:
        chunk_meta["parent_seq"] = parent_seq
    if split_index is not None:
        chunk_meta["split_index"] = split_index
    return TextChunk(seq=seq, content=content, meta=chunk_meta)


def mark_fallback(chunks: list[TextChunk], *, requested_strategy: str) -> list[TextChunk]:
    marked: list[TextChunk] = []
    for chunk in chunks:
        meta = dict(chunk.meta)
        meta["fallback_chunking"] = True
        meta["requested_chunk_strategy"] = requested_strategy
        marked.append(TextChunk(seq=chunk.seq, content=chunk.content, meta=meta))
    return marked
