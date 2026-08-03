from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    JsonDict,
    TenantMixin,
    TimestampMixin,
)


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    __table_args__ = (
        UniqueConstraint("tenant_id", "username"),
        Index(
            "uq_users_tenant_username_ci",
            "tenant_id",
            func.lower(func.btrim(username)),
            unique=True,
        ),
    )


class Role(IdMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)


class Permission(IdMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    module: Mapped[str | None] = mapped_column(Text)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("permissions.id"),
        primary_key=True,
    )


class KnowledgeBase(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding_model: Mapped[str | None] = mapped_column(
        Text, server_default=text("'text-embedding-3-small'")
    )
    embedding_dim: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1536")
    )
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    __table_args__ = (
        Index(
            "uq_knowledge_bases_tenant_active_name_ci",
            "tenant_id",
            func.lower(func.btrim(name)),
            unique=True,
            postgresql_where=text("status is distinct from 'archived'"),
        ),
    )


class Document(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "documents"

    kb_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(BigInteger)
    parse_status: Mapped[str | None] = mapped_column(
        Text, server_default=text("'pending'")
    )
    meta: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    logical_doc_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    version_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    version_parent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_documents_tenant_kb_name_ci",
            "tenant_id",
            "kb_id",
            func.lower(func.btrim(name)),
            unique=True,
            postgresql_where=text("version_status = 'active'"),
        ),
        Index(
            "uq_documents_tenant_kb_logical_version",
            "tenant_id",
            "kb_id",
            "logical_doc_id",
            "version_no",
            unique=True,
        ),
        Index(
            "uq_documents_tenant_kb_logical_active",
            "tenant_id",
            "kb_id",
            "logical_doc_id",
            unique=True,
            postgresql_where=text("version_status = 'active'"),
        ),
    )


class Chunk(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_kb_id", "kb_id"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "chunks_content_fts",
            func.to_tsvector("simple", text("content")),
            postgresql_using="gin",
        ),
    )

    kb_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    doc_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    seq: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))


class Chunk1024(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "chunks_1024"
    __table_args__ = (
        Index("ix_chunks_1024_kb_id", "kb_id"),
        Index(
            "ix_chunks_1024_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "chunks_1024_content_fts",
            func.to_tsvector("simple", text("content")),
            postgresql_using="gin",
        ),
    )

    kb_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    doc_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    seq: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))


class Chunk3072(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "chunks_3072"
    __table_args__ = (
        Index("ix_chunks_3072_kb_id", "kb_id"),
        Index(
            "chunks_3072_content_fts",
            func.to_tsvector("simple", text("content")),
            postgresql_using="gin",
        ),
    )

    kb_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    doc_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    seq: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072))


class AgentTemplate(IdMixin, Base):
    __tablename__ = "agent_templates"

    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    default_config: Mapped[JsonDict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    builtin: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))


class Agent(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agent_templates.id")
    )
    persona: Mapped[str | None] = mapped_column(Text)
    config: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    model_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'draft'"))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    __table_args__ = (
        Index(
            "uq_agents_tenant_active_name_ci",
            "tenant_id",
            func.lower(func.btrim(name)),
            unique=True,
            postgresql_where=text("status is distinct from 'archived'"),
        ),
    )


class Tool(IdMixin, TenantMixin, Base):
    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    schema: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    config: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    __table_args__ = (
        Index(
            "uq_tools_tenant_active_name_ci",
            "tenant_id",
            func.lower(func.btrim(name)),
            unique=True,
            postgresql_where=text("status is distinct from 'archived'"),
        ),
    )


class AgentTool(Base):
    __tablename__ = "agent_tools"

    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id"), primary_key=True
    )
    tool_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tools.id"), primary_key=True
    )


class AgentKb(Base):
    __tablename__ = "agent_kbs"

    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id"), primary_key=True
    )
    kb_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id"), primary_key=True
    )


class Model(IdMixin, Base):
    __tablename__ = "models"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    provider: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    provider_config: Mapped[JsonDict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    import_source: Mapped[str | None] = mapped_column(
        Text, server_default=text("'external'")
    )
    model_icon_path: Mapped[str | None] = mapped_column(Text)
    publish_date: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str | None] = mapped_column(
        Text, server_default=text("'tenant'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelChannel(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "model_channels"

    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    model_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("models.id")
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    health: Mapped[str | None] = mapped_column(Text, server_default=text("'unknown'"))


class ModelCatalog(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_catalog"
    __table_args__ = (
        Index("ix_model_catalog_provider", "provider"),
        Index("ix_model_catalog_model_type", "model_type"),
        Index("ix_model_catalog_is_active", "is_active"),
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    context_window: Mapped[int | None] = mapped_column(Integer)
    supports_streaming: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    supports_tools: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    supports_vision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    default_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_parameters: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    official_url: Mapped[str | None] = mapped_column(Text)
    pricing: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class ApiKey(IdMixin, Base):
    __tablename__ = "api_keys"

    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))


class PublishedApp(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "published_apps"
    __table_args__ = (
        Index("ix_published_apps_tenant_id", "tenant_id"),
        Index("ix_published_apps_agent_id", "agent_id"),
    )

    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'published'")
    )
    publish_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'api'")
    )
    config: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    active_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class PublishedAppVersion(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "published_app_versions"
    __table_args__ = (
        Index(
            "uq_published_app_versions_tenant_app_no",
            "tenant_id",
            "app_id",
            "version_no",
            unique=True,
        ),
        Index(
            "ix_published_app_versions_tenant_app_status",
            "tenant_id",
            "app_id",
            "status",
        ),
        Index(
            "uq_published_app_versions_tenant_app_active",
            "tenant_id",
            "app_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    app_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("published_apps.id"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    title: Mapped[str | None] = mapped_column(Text)
    release_note: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    precheck_result: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppApiKey(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "app_api_keys"
    __table_args__ = (
        Index("ix_app_api_keys_tenant_app", "tenant_id", "app_id"),
        Index("ix_app_api_keys_status", "status"),
    )

    app_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("published_apps.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    config: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    title: Mapped[str | None] = mapped_column(Text)


class Message(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id")
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer)
    citations: Mapped[list[JsonDict]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )


class MessageFeedback(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        Index("ix_message_feedback_tenant_message", "tenant_id", "message_id"),
        Index(
            "ix_message_feedback_tenant_agent_created",
            "tenant_id",
            "agent_id",
            "created_at",
        ),
        Index(
            "ix_message_feedback_tenant_rating_created",
            "tenant_id",
            "rating",
            "created_at",
        ),
    )

    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id"), nullable=False
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id")
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id")
    )
    trace_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("run_traces.id")
    )
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[JsonDict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    meta: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )


class ConversationIncident(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "conversation_incidents"
    __table_args__ = (
        Index("ix_incidents_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "ix_incidents_tenant_type_created",
            "tenant_id",
            "incident_type",
            "created_at",
        ),
        Index("ix_incidents_tenant_agent_created", "tenant_id", "agent_id", "created_at"),
        Index(
            "uq_incidents_tenant_trace_type",
            "tenant_id",
            "trace_id",
            "incident_type",
            unique=True,
            postgresql_where=text("trace_id is not null"),
        ),
    )

    conversation_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id")
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id")
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id")
    )
    trace_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("run_traces.id")
    )
    incident_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[JsonDict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    resolved_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecord(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_tenant_id_created_at", "tenant_id", "created_at"),
    )

    channel_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    model_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cache_hit: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false")
    )


class Workspace(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    layout: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    __table_args__ = (
        Index(
            "uq_workspaces_tenant_name_ci",
            "tenant_id",
            func.lower(func.btrim(name)),
            unique=True,
        ),
    )


class WorkspaceResource(IdMixin, Base):
    __tablename__ = "workspace_resources"

    workspace_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class Trigger(IdMixin, TenantMixin, Base):
    __tablename__ = "triggers"

    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    type: Mapped[str | None] = mapped_column(Text)
    config: Mapped[JsonDict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))


class RunTrace(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "run_traces"
    __table_args__ = (Index("ix_run_traces_conversation_id", "conversation_id"),)

    conversation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    parent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    span_type: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    input: Mapped[JsonDict | None] = mapped_column(JSONB)
    output: Mapped[JsonDict | None] = mapped_column(JSONB)
    tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class AuditLog(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    action: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[JsonDict | None] = mapped_column(JSONB)


class EvalCase(IdMixin, TenantMixin, Base):
    __tablename__ = "eval_cases"

    scene: Mapped[str | None] = mapped_column(Text)
    input: Mapped[str | None] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    assert_type: Mapped[str | None] = mapped_column(Text)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric)


class EvalRun(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "eval_runs"

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    case_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    detail: Mapped[JsonDict | None] = mapped_column(JSONB)


class CopilotTask(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "copilot_tasks"
    __table_args__ = (
        Index("ix_copilot_tasks_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_copilot_tasks_workspace_status", "tenant_id", "workspace_id", "status"),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    user_goal: Mapped[str] = mapped_column(Text, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'planned'"))
    current_step_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    plan: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    warnings: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)


class CopilotTaskStep(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "copilot_task_steps"
    __table_args__ = (
        Index("ix_copilot_task_steps_task_order", "task_id", "step_order"),
        Index("ix_copilot_task_steps_status", "tenant_id", "status"),
        UniqueConstraint("task_id", "idempotency_key"),
    )

    task_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("copilot_tasks.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    client_step_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_arguments: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dependencies: Mapped[JsonDict] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    wait_condition: Mapped[JsonDict | None] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'L1'"))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[JsonDict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_status: Mapped[str | None] = mapped_column(Text)
    check_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CopilotTaskEvent(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "copilot_task_events"
    __table_args__ = (
        Index("ix_copilot_task_events_task_event", "task_id", "event_id"),
        Index("ix_copilot_task_events_tenant_task_created", "tenant_id", "task_id", "created_at"),
        UniqueConstraint("task_id", "event_id"),
    )

    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    task_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("copilot_tasks.id"), nullable=False)
    step_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("copilot_task_steps.id"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class ComputerUseTarget(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "computer_use_targets"
    __table_args__ = (
        Index("ix_computer_use_targets_tenant_workspace", "tenant_id", "workspace_id"),
        Index("ix_computer_use_targets_tenant_enabled", "tenant_id", "enabled"),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    allowed_url_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    denied_url_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    allow_navigation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    allow_form_fill: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    allow_submit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    allow_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    allow_download: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    allow_login: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    allow_persistent_session: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    max_session_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    max_actions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class ComputerUseSession(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "computer_use_sessions"
    __table_args__ = (
        Index("ix_computer_use_sessions_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_computer_use_sessions_tenant_target", "tenant_id", "target_id"),
        Index("ix_computer_use_sessions_workspace_status", "tenant_id", "workspace_id", "status"),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("copilot_tasks.id"))
    conversation_id: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("computer_use_targets.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending_consent'"))
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'read_only_browser'"))
    current_url: Mapped[str | None] = mapped_column(Text)
    current_title: Mapped[str | None] = mapped_column(Text)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    user_goal: Mapped[str] = mapped_column(Text, nullable=False)
    approved_plan: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'L1'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str | None] = mapped_column(Text)
    takeover_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    browser_context_ref: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    security_events: Mapped[list[JsonDict]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class ComputerUseAction(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "computer_use_actions"
    __table_args__ = (
        Index("ix_computer_use_actions_session_sequence", "session_id", "sequence"),
        Index("ix_computer_use_actions_tenant_status", "tenant_id", "status"),
    )

    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("computer_use_sessions.id"), nullable=False)
    task_step_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("copilot_task_steps.id"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_description: Mapped[str | None] = mapped_column(Text)
    selector_strategy: Mapped[str | None] = mapped_column(Text)
    selector_value: Mapped[str | None] = mapped_column(Text)
    sanitized_input: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    before_url: Mapped[str | None] = mapped_column(Text)
    after_url: Mapped[str | None] = mapped_column(Text)
    before_screenshot_id: Mapped[str | None] = mapped_column(Text)
    after_screenshot_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'L1'"))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confirmation_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Experience(IdMixin, CreatedAtMixin, TenantMixin, Base):
    __tablename__ = "experiences"
    __table_args__ = (
        Index(
            "ix_experiences_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    scene: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    meta: Mapped[JsonDict | None] = mapped_column(JSONB)


class Experiment(IdMixin, TenantMixin, Base):
    __tablename__ = "experiments"

    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    config: Mapped[JsonDict | None] = mapped_column(JSONB)
    metrics: Mapped[JsonDict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'draft'"))


ALL_MODELS = (
    Tenant,
    User,
    Role,
    Permission,
    UserRole,
    RolePermission,
    KnowledgeBase,
    Document,
    Chunk,
    Chunk1024,
    Chunk3072,
    AgentTemplate,
    Agent,
    Tool,
    AgentTool,
    AgentKb,
    Model,
    ModelChannel,
    ModelCatalog,
    ApiKey,
    PublishedApp,
    PublishedAppVersion,
    AppApiKey,
    Conversation,
    Message,
    MessageFeedback,
    ConversationIncident,
    UsageRecord,
    Workspace,
    WorkspaceResource,
    Trigger,
    RunTrace,
    AuditLog,
    CopilotTask,
    CopilotTaskStep,
    CopilotTaskEvent,
    ComputerUseTarget,
    ComputerUseSession,
    ComputerUseAction,
    EvalCase,
    EvalRun,
    Experience,
    Experiment,
)
