import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import Chunk, Document, KnowledgeBase, Tenant, User
from app.rag.embeddings import embed_texts
from app.services import ensure_default_seed


GUIDE_SOURCE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "guide"
GUIDE_SYNC_VERSION = "guide-v1"


@dataclass(frozen=True)
class GuideArticle:
    slug: str
    title: str
    category: str
    order: int
    updated_at: str
    body: str
    source_uri: str
    content_hash: str


async def sync_guide_to_kb(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID | None = None
) -> KnowledgeBase:
    articles = load_guide_articles()
    kb = await ensure_guide_kb(db, tenant_id=tenant_id, user_id=user_id)
    current_sources = {article.source_uri for article in articles}
    current_names = {f"《{article.title}》.md" for article in articles}

    for article in articles:
        await upsert_guide_document(db, tenant_id=tenant_id, kb=kb, article=article)

    existing_docs = (
        (
            await db.execute(
                select(Document).where(
                    Document.tenant_id == tenant_id, Document.kb_id == kb.id
                )
            )
        )
        .scalars()
        .all()
    )
    for document in existing_docs:
        if (
            document.source_uri not in current_sources
            or document.name not in current_names
        ):
            await db.execute(
                delete(Chunk).where(
                    Chunk.tenant_id == tenant_id, Chunk.doc_id == document.id
                )
            )
            await db.delete(document)
    await db.flush()
    return kb


def load_guide_articles() -> list[GuideArticle]:
    articles: list[GuideArticle] = []
    for path in sorted(GUIDE_SOURCE_DIR.glob("**/*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        slug = path.relative_to(GUIDE_SOURCE_DIR).with_suffix("").as_posix()
        title = meta.get("title") or path.stem
        content_hash = hashlib.sha256(
            f"{title}\n{meta.get('updated_at', '')}\n{body}".encode("utf-8")
        ).hexdigest()
        articles.append(
            GuideArticle(
                slug=slug,
                title=title,
                category=meta.get("category") or "使用教程",
                order=int(meta.get("order") or 999),
                updated_at=meta.get("updated_at") or "",
                body=body.strip(),
                source_uri=f"guide://{slug}",
                content_hash=content_hash,
            )
        )
    return articles


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---", 4)
    if end < 0:
        return {}, raw
    meta: dict[str, str] = {}
    for line in raw[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, raw[end + 4 :].strip()


async def ensure_guide_kb(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID | None
) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.name == "平台使用教程"
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=tenant_id,
            name="平台使用教程",
            type="manual",
            description="内置平台使用教程，与教程中心使用同一份内容源。",
            config={"source": "frontend/src/guide", "sync": GUIDE_SYNC_VERSION},
            embedding_model="mock-embedding",
            embedding_dim=1536,
            status="active",
            created_by=user_id,
        )
        db.add(kb)
        await db.flush()
    else:
        kb.type = "manual"
        kb.description = "内置平台使用教程，与教程中心使用同一份内容源。"
        kb.config = {"source": "frontend/src/guide", "sync": GUIDE_SYNC_VERSION}
        kb.embedding_model = "mock-embedding"
        kb.embedding_dim = 1536
        kb.status = "active"
    return kb


async def upsert_guide_document(
    db: AsyncSession, *, tenant_id: UUID, kb: KnowledgeBase, article: GuideArticle
) -> Document:
    name = f"《{article.title}》.md"
    result = await db.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.kb_id == kb.id,
            Document.name == name,
        )
    )
    document = result.scalar_one_or_none()
    existing_hash = (
        document.meta.get("hash") if document is not None and document.meta else None
    )
    meta = {
        "source": "guide",
        "slug": article.slug,
        "title": article.title,
        "category": article.category,
        "order": article.order,
        "updated_at": article.updated_at,
        "hash": article.content_hash,
    }
    if document is None:
        document = Document(
            tenant_id=tenant_id,
            kb_id=kb.id,
            name=name,
            source_uri=article.source_uri,
            mime="text/markdown",
            size=len(article.body.encode("utf-8")),
            parse_status="done",
            meta=meta,
        )
        db.add(document)
        await db.flush()
    else:
        document.source_uri = article.source_uri
        document.mime = "text/markdown"
        document.size = len(article.body.encode("utf-8"))
        document.parse_status = "done"
        document.meta = meta

    existing_chunk = (
        await db.execute(
            select(Chunk.id)
            .where(Chunk.tenant_id == tenant_id, Chunk.doc_id == document.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_hash != article.content_hash or existing_chunk is None:
        await rebuild_document_chunks(
            db, tenant_id=tenant_id, kb=kb, document=document, article=article
        )
    return document


async def rebuild_document_chunks(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    kb: KnowledgeBase,
    document: Document,
    article: GuideArticle,
) -> None:
    await db.execute(
        delete(Chunk).where(Chunk.tenant_id == tenant_id, Chunk.doc_id == document.id)
    )
    chunks = split_markdown(article.body)
    embeddings = await embed_texts(
        model=kb.embedding_model or "mock-embedding", texts=chunks
    )
    for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
        db.add(
            Chunk(
                tenant_id=tenant_id,
                kb_id=kb.id,
                doc_id=document.id,
                seq=index,
                content=f"{article.title}\n\n{content}",
                tokens=len(content),
                meta={
                    "source": "guide",
                    "slug": article.slug,
                    "title": article.title,
                    "category": article.category,
                    "paragraph": index + 1,
                },
                embedding=embedding,
            )
        )


def split_markdown(body: str, limit: int = 1200) -> list[str]:
    paragraphs = [
        paragraph.strip() for paragraph in body.split("\n\n") if paragraph.strip()
    ]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks or [body]


async def main() -> None:
    async with SessionLocal() as db:
        await ensure_default_seed(db)
        tenant = (
            await db.execute(select(Tenant).where(Tenant.code == "default"))
        ).scalar_one()
        admin = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant.id, User.username == "admin"
                )
            )
        ).scalar_one_or_none()
        kb = await sync_guide_to_kb(
            db, tenant_id=tenant.id, user_id=admin.id if admin else None
        )
        await db.commit()
        print(f"guide_kb_id={kb.id}")


if __name__ == "__main__":
    asyncio.run(main())
