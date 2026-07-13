from io import BytesIO

from docx import Document as DocxDocument
from pypdf import PdfReader


def parse_document_bytes(*, content: bytes, mime: str | None, filename: str) -> str:
    normalized_mime = (mime or "").lower()
    normalized_name = filename.lower()

    if normalized_mime in {"text/plain", "text/markdown"} or normalized_name.endswith((".txt", ".md")):
        return parse_text(content)
    if normalized_mime == "application/pdf" or normalized_name.endswith(".pdf"):
        return parse_pdf(content)
    if (
        normalized_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or normalized_name.endswith(".docx")
    ):
        return parse_docx(content)

    if normalized_mime.startswith("text/"):
        return parse_text(content)
    raise ValueError("unsupported_document_type")


def parse_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def parse_pdf(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    pages: list[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[page {page_index}]\n{text}")
    return "\n\n".join(pages)


def parse_docx(content: bytes) -> str:
    document = DocxDocument(BytesIO(content))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n\n".join(paragraphs)
