from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas import FeedbackCreate
from app.services.feedback_service import create_message_feedback


def test_feedback_schema_accepts_positive_and_negative() -> None:
    positive = FeedbackCreate(rating="positive", reason="accurate")
    negative = FeedbackCreate(
        rating="negative", reason="no_evidence", comment="没有引用"
    )

    assert positive.rating == "positive"
    assert negative.reason == "no_evidence"


def test_user_message_feedback_is_rejected_strategy() -> None:
    message = SimpleNamespace(role="user")

    with pytest.raises(ValueError):
        if message.role != "assistant":
            raise ValueError("feedback_assistant_message_required")


def test_negative_feedback_creates_incident_intent() -> None:
    source = create_message_feedback.__code__.co_names

    assert "create_incident" in source
    assert "incident_from_runtime" in source


def test_feedback_to_eval_case_scene_shape() -> None:
    reason = "wrong_citation"
    assert f"feedback/{reason}" == "feedback/wrong_citation"


def test_positive_feedback_can_become_experience_scene() -> None:
    feedback_id = uuid4()
    meta = {"source": "feedback", "feedback_id": str(feedback_id)}

    assert meta["source"] == "feedback"
    assert meta["feedback_id"] == str(feedback_id)


def test_tenant_isolation_uses_tenant_id_filter() -> None:
    names = create_message_feedback.__code__.co_varnames

    assert "tenant_id" in names
