from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

models = Table(
    "models",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("provider", Text),
    Column("type", Text, nullable=False),
    Column("display_name", Text),
    Column("description", Text),
    Column("is_active", Boolean, server_default=text("true")),
    Column("provider_config", JSONB, server_default=text("'{}'::jsonb")),
    Column("import_source", Text, server_default=text("'external'")),
    Column("model_icon_path", Text),
    Column("publish_date", Text),
    Column("scope_type", Text, server_default=text("'tenant'")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

model_channels = Table(
    "model_channels",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True)),
    Column("model_id", UUID(as_uuid=True), ForeignKey("models.id")),
    Column("base_url", Text, nullable=False),
    Column("api_key_enc", Text, nullable=False),
    Column("weight", Integer),
    Column("rpm_limit", Integer),
    Column("status", Text),
    Column("health", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

usage_records = Table(
    "usage_records",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("channel_id", UUID(as_uuid=True)),
    Column("model_id", UUID(as_uuid=True)),
    Column("agent_id", UUID(as_uuid=True)),
    Column("user_id", UUID(as_uuid=True)),
    Column("prompt_tokens", Integer),
    Column("completion_tokens", Integer),
    Column("latency_ms", Integer),
    Column("cost", Numeric(12, 6)),
    Column("cache_hit", Boolean),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text),
    Column("key_hash", Text, nullable=False),
    Column("scopes", JSONB),
    Column("status", Text),
)
