from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, TimestampMixin, UUIDMixin


class EvalCase(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"

    target_type: Mapped[str] = mapped_column(String(32), default="assistant", nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scene: Mapped[str | None] = mapped_column(String(128))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    scoring_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class EvalRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "eval_runs"

    target_type: Mapped[str] = mapped_column(String(32), default="assistant", nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    run_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    items: Mapped[list["EvalRunItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EvalRunItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "eval_run_items"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(ForeignKey("eval_cases.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    first_frame_latency_ms: Mapped[int | None] = mapped_column(Integer)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)
    frame_count: Mapped[int | None] = mapped_column(Integer)
    conversation_id: Mapped[str | None] = mapped_column(String(128))
    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    run: Mapped[EvalRun] = relationship(back_populates="items")
    case: Mapped[EvalCase | None] = relationship(lazy="selectin")


class Experience(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "experiences"

    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(128))
    scene: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    embedding = mapped_column(Vector(settings.experience_embedding_dim), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
