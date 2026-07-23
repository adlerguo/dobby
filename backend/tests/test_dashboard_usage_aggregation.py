import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.services.dashboard_service import by_channel_series, by_model_series


def make_usage_record(
    *,
    model_id=None,
    channel_id=None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    latency_ms: int | None = None,
    cost: Decimal | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        model_id=model_id,
        channel_id=channel_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        cost=cost,
        created_at=datetime.now(UTC),
    )


def test_usage_records_aggregate_by_model_and_channel() -> None:
    model_id = uuid4()
    other_model_id = uuid4()
    channel_id = uuid4()
    other_channel_id = uuid4()
    snapshot = {
        "models": {model_id: "GPT Small"},
        "usage_records": [
            make_usage_record(
                model_id=model_id,
                channel_id=channel_id,
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
                cost=Decimal("0.25"),
            ),
            make_usage_record(
                model_id=model_id,
                channel_id=channel_id,
                prompt_tokens=20,
                completion_tokens=10,
                latency_ms=300,
                cost=Decimal("0.75"),
            ),
            make_usage_record(
                model_id=other_model_id,
                channel_id=other_channel_id,
                prompt_tokens=3,
                completion_tokens=2,
                latency_ms=None,
                cost=None,
            ),
        ],
    }

    assert by_model_series(snapshot) == [
        {
            "model_id": str(model_id),
            "model_name": "GPT Small",
            "call_count": 2,
            "token_total": 45,
            "cost_total": 1.0,
            "avg_latency_ms": 200,
        },
        {
            "model_id": str(other_model_id),
            "model_name": "未知模型",
            "call_count": 1,
            "token_total": 5,
            "cost_total": 0.0,
            "avg_latency_ms": 0,
        },
    ]
    assert by_channel_series(snapshot) == [
        {
            "channel_id": str(channel_id),
            "call_count": 2,
            "token_total": 45,
            "cost_total": 1.0,
            "avg_latency_ms": 200,
        },
        {
            "channel_id": str(other_channel_id),
            "call_count": 1,
            "token_total": 5,
            "cost_total": 0.0,
            "avg_latency_ms": 0,
        },
    ]


def test_usage_record_aggregations_are_empty_without_usage_data() -> None:
    snapshot = {"models": {}, "usage_records": []}

    assert by_model_series(snapshot) == []
    assert by_channel_series(snapshot) == []
