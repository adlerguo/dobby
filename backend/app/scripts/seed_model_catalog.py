import asyncio
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import ModelCatalog


MOCK_CATALOG_ITEMS: list[dict[str, Any]] = [
    {
        "provider": "mock",
        "model_code": "mock-chat",
        "display_name": "Mock Chat",
        "model_type": "llm",
        "description": "仅用于离线演示的 Mock 对话模型，生产模式不会参与真实路由。",
        "context_window": 4096,
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "mock://local",
        "protocol": "mock",
        "recommended_parameters": {
            "temperature": 0.2,
            "max_tokens": 512,
            "availability": "demo_only",
            "is_demo": True,
        },
        "official_url": None,
        "pricing": {"status": "free_local"},
        "icon": "mock",
        "sort_order": 10,
        "is_active": True,
    },
    {
        "provider": "mock",
        "model_code": "mock-embedding",
        "display_name": "Mock Embedding",
        "model_type": "embedding",
        "description": "仅用于离线演示的 Mock 向量模型，生产模式不会参与真实路由。",
        "context_window": 8192,
        "supports_streaming": False,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "mock://local",
        "protocol": "mock",
        "recommended_parameters": {"dimensions": 1536, "availability": "demo_only", "is_demo": True},
        "official_url": None,
        "pricing": {"status": "free_local"},
        "icon": "mock",
        "sort_order": 11,
        "is_active": True,
    },
]


REAL_CATALOG_ITEMS: list[dict[str, Any]] = [
    {
        "provider": "deepseek",
        "model_code": "deepseek-chat",
        "display_name": "DeepSeek Chat",
        "model_type": "llm",
        "description": "DeepSeek 通用对话模型，已收录待用户使用真实 API Key 实测。",
        "context_window": 64000,
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "https://api.deepseek.com",
        "protocol": "openai_compatible",
        "recommended_parameters": {"temperature": 0.7, "max_tokens": 2048, "availability": "needs_real_key"},
        "official_url": "https://api-docs.deepseek.com/",
        "pricing": {"status": "see_official"},
        "icon": "deepseek",
        "sort_order": 20,
        "is_active": True,
    },
    {
        "provider": "deepseek",
        "model_code": "deepseek-reasoner",
        "display_name": "DeepSeek Reasoner",
        "model_type": "llm",
        "description": "DeepSeek 推理模型，已收录待用户使用真实 API Key 实测。",
        "context_window": 64000,
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "https://api.deepseek.com",
        "protocol": "openai_compatible",
        "recommended_parameters": {"temperature": 0.6, "max_tokens": 4096, "availability": "needs_real_key"},
        "official_url": "https://api-docs.deepseek.com/",
        "pricing": {"status": "see_official"},
        "icon": "deepseek",
        "sort_order": 21,
        "is_active": True,
    },
    {
        "provider": "openai",
        "model_code": "gpt-4o-mini",
        "display_name": "GPT-4o mini",
        "model_type": "llm",
        "description": "OpenAI 轻量通用对话模型，已收录待用户使用真实 API Key 实测。",
        "context_window": 128000,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "default_base_url": "https://api.openai.com",
        "protocol": "openai_compatible",
        "recommended_parameters": {"temperature": 0.7, "max_tokens": 2048, "availability": "needs_real_key"},
        "official_url": "https://platform.openai.com/docs/models",
        "pricing": {"status": "see_official"},
        "icon": "openai",
        "sort_order": 30,
        "is_active": True,
    },
    {
        "provider": "openai",
        "model_code": "text-embedding-3-small",
        "display_name": "text-embedding-3-small",
        "model_type": "embedding",
        "description": "OpenAI 小型向量模型，已收录待用户使用真实 API Key 实测。",
        "context_window": 8191,
        "supports_streaming": False,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "https://api.openai.com",
        "protocol": "openai_compatible",
        "recommended_parameters": {"dimensions": 1536, "availability": "needs_real_key"},
        "official_url": "https://platform.openai.com/docs/models",
        "pricing": {"status": "see_official"},
        "icon": "openai",
        "sort_order": 31,
        "is_active": True,
    },
    {
        "provider": "qwen",
        "model_code": "qwen-plus",
        "display_name": "通义千问 Plus",
        "model_type": "llm",
        "description": "通义千问 Plus，DashScope OpenAI 兼容模式，已收录待用户使用真实 API Key 实测。",
        "context_window": 131072,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": False,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode",
        "protocol": "openai_compatible",
        "recommended_parameters": {"temperature": 0.7, "max_tokens": 2048, "availability": "needs_real_key"},
        "official_url": "https://help.aliyun.com/zh/model-studio/",
        "pricing": {"status": "see_official"},
        "icon": "qwen",
        "sort_order": 40,
        "is_active": True,
    },
    {
        "provider": "qwen",
        "model_code": "text-embedding-v4",
        "display_name": "通义 text-embedding-v4",
        "model_type": "embedding",
        "description": "通义千问文本向量模型，DashScope OpenAI 兼容模式，预置 dimensions=1536 以适配当前 pgvector 列。",
        "context_window": 8192,
        "supports_streaming": False,
        "supports_tools": False,
        "supports_vision": False,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode",
        "protocol": "openai_compatible",
        "recommended_parameters": {"dimensions": 1536, "availability": "needs_real_key"},
        "official_url": "https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai",
        "pricing": {"status": "see_official"},
        "icon": "qwen",
        "sort_order": 41,
        "is_active": True,
    },
]


async def main() -> None:
    async with SessionLocal() as db:
        await seed_model_catalog(db)
        await db.commit()


async def seed_model_catalog(db: AsyncSession) -> None:
    demo_mode = os.getenv("SEED_DEMO_MODE", "").lower() in {"1", "true", "yes"}
    items = [*REAL_CATALOG_ITEMS, *(MOCK_CATALOG_ITEMS if demo_mode else [])]
    if not demo_mode:
        await disable_demo_catalog_items(db)
    for item in items:
        result = await db.execute(select(ModelCatalog).where(ModelCatalog.model_code == item["model_code"]))
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(ModelCatalog(**item))
            continue
        for key, value in item.items():
            setattr(existing, key, value)


async def disable_demo_catalog_items(db: AsyncSession) -> None:
    for model_code in {"mock-chat", "mock-embedding"}:
        result = await db.execute(select(ModelCatalog).where(ModelCatalog.model_code == model_code))
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.is_active = False
            existing.recommended_parameters = {
                **(existing.recommended_parameters or {}),
                "availability": "demo_only",
                "is_demo": True,
            }


if __name__ == "__main__":
    asyncio.run(main())
