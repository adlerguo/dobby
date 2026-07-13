from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    seq: int
    content: str
    meta: dict[str, int | str]


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 80) -> list[TextChunk]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []

    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    chunks: list[TextChunk] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(build_chunk(len(chunks), current))
                current = ""
            chunks.extend(split_long_paragraph(paragraph, start_seq=len(chunks), chunk_size=chunk_size, overlap=overlap))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(build_chunk(len(chunks), current))
        current = paragraph

    if current:
        chunks.append(build_chunk(len(chunks), current))

    return chunks


def split_long_paragraph(paragraph: str, *, start_seq: int, chunk_size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    start = 0
    while start < len(paragraph):
        end = min(start + chunk_size, len(paragraph))
        content = paragraph[start:end].strip()
        if content:
            chunks.append(build_chunk(start_seq + len(chunks), content))
        if end == len(paragraph):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunk(seq: int, content: str) -> TextChunk:
    return TextChunk(seq=seq, content=content, meta={"chunk_method": "paragraph_window"})
