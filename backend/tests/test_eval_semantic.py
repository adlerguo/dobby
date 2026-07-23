import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.models import Agent, EvalCase
from app.services import eval_service


TENANT_ID = uuid4()
USER_ID = uuid4()


class FakeDB:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.added = []
        self.commits = 0

    async def get(self, model, id_):
        if model is Agent and id_ == self.agent.id:
            return self.agent
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                setattr(obj, "id", uuid4())
            if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
                setattr(obj, "created_at", datetime.now(UTC))

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            setattr(obj, "id", uuid4())
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            setattr(obj, "created_at", datetime.now(UTC))


def run_async(awaitable):
    return asyncio.run(awaitable)


def make_agent() -> Agent:
    return Agent(
        id=uuid4(),
        tenant_id=TENANT_ID,
        name="Eval Agent",
        type="assistant",
        config={},
        model_id=uuid4(),
        status="active",
    )


def make_case(*, input_text: str) -> EvalCase:
    return EvalCase(
        id=uuid4(),
        tenant_id=TENANT_ID,
        scene="semantic",
        input=input_text,
        expected="reset password",
        assert_type="semantic",
        threshold=Decimal("0.8"),
    )


def test_run_agent_eval_semantic_assertion_records_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent()
    db = FakeDB(agent)
    close_case = make_case(input_text="close")
    unrelated_case = make_case(input_text="unrelated")

    async def fake_load_eval_cases(db, *, tenant_id, case_ids):
        return [close_case, unrelated_case]

    async def fake_dispatch_single_agent(db, *, tenant_id, user_id, agent_id, payload):
        answer = "change your password" if payload.query == "close" else "book a flight"
        return SimpleNamespace(
            answer=answer,
            tool_results=[],
            citations=[],
            usage={},
            conversation_id=uuid4(),
            trace_id=uuid4(),
        )

    async def fake_embed_texts(*, model, texts):
        assert model == eval_service.DEFAULT_EMBEDDING_MODEL
        if texts[0] == "change your password":
            return [[1.0, 0.0], [1.0, 0.0]]
        return [[0.0, 1.0], [1.0, 0.0]]

    monkeypatch.setattr(eval_service, "load_eval_cases", fake_load_eval_cases)
    monkeypatch.setattr(
        eval_service, "dispatch_single_agent", fake_dispatch_single_agent
    )
    monkeypatch.setattr(eval_service, "embed_texts", fake_embed_texts)

    report = run_async(
        eval_service.run_agent_eval(
            db,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            agent_id=agent.id,
            payload=SimpleNamespace(
                case_ids=[],
                workspace_id=None,
                max_tokens=3500,
                history_limit=0,
                top_k=4,
                max_tool_rounds=1,
                write_passed_experiences=False,
            ),
        )
    )

    assert report is not None
    assert report.passed == 1
    assert report.failed == 1
    assert report.runs[0].passed is True
    assert report.runs[0].detail["reason"] == "semantic_similarity"
    assert report.runs[0].detail["similarity"] == 1.0
    assert report.runs[1].passed is False
    assert report.runs[1].detail["reason"] == "semantic_similarity"
    assert report.runs[1].detail["similarity"] == 0.0
