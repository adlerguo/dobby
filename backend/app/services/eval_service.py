import math
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, EvalCase, EvalRun, Experience
from app.orchestrator import dispatch_single_agent
from app.rag.embeddings import DEFAULT_EMBEDDING_MODEL, embed_texts
from app.schemas import (
    AgentRunIn,
    EvalCaseCreate,
    EvalCaseUpdate,
    EvalReportOut,
    EvalRunOut,
    EvalRunRequest,
    ExperienceCreate,
)


async def list_eval_cases(
    db: AsyncSession, *, tenant_id: UUID, scene: str | None = None
) -> list[EvalCase]:
    stmt = select(EvalCase).where(EvalCase.tenant_id == tenant_id).order_by(EvalCase.id)
    if scene:
        stmt = stmt.where(EvalCase.scene == scene)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_eval_case(
    db: AsyncSession, *, tenant_id: UUID, payload: EvalCaseCreate
) -> EvalCase:
    case = EvalCase(
        tenant_id=tenant_id,
        scene=payload.scene,
        input=payload.input,
        expected=payload.expected,
        assert_type=payload.assert_type,
        threshold=Decimal(str(payload.threshold))
        if payload.threshold is not None
        else None,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


async def get_eval_case(
    db: AsyncSession, *, tenant_id: UUID, case_id: UUID
) -> EvalCase | None:
    result = await db.execute(
        select(EvalCase).where(EvalCase.id == case_id, EvalCase.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def update_eval_case(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    case_id: UUID,
    payload: EvalCaseUpdate,
) -> EvalCase | None:
    case = await get_eval_case(db, tenant_id=tenant_id, case_id=case_id)
    if case is None:
        return None

    values = payload.model_dump(exclude_unset=True)
    if "threshold" in values and values["threshold"] is not None:
        values["threshold"] = Decimal(str(values["threshold"]))
    for key, value in values.items():
        setattr(case, key, value)
    await db.commit()
    await db.refresh(case)
    return case


async def delete_eval_case(db: AsyncSession, *, tenant_id: UUID, case_id: UUID) -> bool:
    result = await db.execute(
        delete(EvalCase).where(EvalCase.id == case_id, EvalCase.tenant_id == tenant_id)
    )
    await db.commit()
    return bool(result.rowcount)


async def run_agent_eval(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    payload: EvalRunRequest,
) -> EvalReportOut | None:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id or agent.status != "active":
        return None

    cases = await load_eval_cases(db, tenant_id=tenant_id, case_ids=payload.case_ids)
    runs: list[EvalRunOut] = []
    for case in cases:
        result = await dispatch_single_agent(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            payload=AgentRunIn(
                query=case.input or "",
                workspace_id=payload.workspace_id,
                max_tokens=payload.max_tokens,
                history_limit=payload.history_limit,
                top_k=payload.top_k,
                max_tool_rounds=payload.max_tool_rounds,
            ),
        )
        if result is None:
            raise ValueError("agent_not_found")

        semantic_score: float | None = None
        semantic_embedding_failed = False
        if case.assert_type == "semantic":
            try:
                semantic_score = await calculate_semantic_similarity(
                    result.answer, case.expected
                )
            except Exception:
                semantic_score = 0.0
                semantic_embedding_failed = True

        assessment = assess_eval_case(
            case,
            result.answer,
            result.tool_results,
            result.citations,
            result.usage,
            semantic_score=semantic_score,
            semantic_embedding_failed=semantic_embedding_failed,
        )
        eval_run = EvalRun(
            tenant_id=tenant_id,
            agent_id=agent_id,
            case_id=case.id,
            score=Decimal(str(assessment["score"])),
            passed=assessment["passed"],
            detail={
                **assessment,
                "input": case.input,
                "expected": case.expected,
                "answer": result.answer,
                "conversation_id": str(result.conversation_id),
                "trace_id": str(result.trace_id),
                "citation_count": len(result.citations),
                "tool_count": len(result.tool_results),
            },
        )
        db.add(eval_run)
        await db.flush()

        if payload.write_passed_experiences and assessment["passed"]:
            db.add(
                Experience(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    scene=case.scene,
                    content=f"问题：{case.input}\n答案：{result.answer}",
                    embedding=None,
                    meta={
                        "source": "eval",
                        "case_id": str(case.id),
                        "trace_id": str(result.trace_id),
                        "score": assessment["score"],
                    },
                )
            )
        await db.commit()
        await db.refresh(eval_run)
        runs.append(eval_run_out(eval_run))

    passed = sum(1 for run in runs if run.passed)
    total = len(runs)
    return EvalReportOut(
        agent_id=agent_id,
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=round(passed / total * 100, 2) if total else 0.0,
        runs=runs,
    )


async def list_eval_runs(
    db: AsyncSession, *, tenant_id: UUID, agent_id: UUID, limit: int
) -> list[EvalRun]:
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.tenant_id == tenant_id, EvalRun.agent_id == agent_id)
        .order_by(EvalRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def create_experience(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    payload: ExperienceCreate,
) -> Experience | None:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        return None
    experience = Experience(
        tenant_id=tenant_id,
        agent_id=agent_id,
        scene=payload.scene,
        content=payload.content,
        embedding=None,
        meta=payload.meta,
    )
    db.add(experience)
    await db.commit()
    await db.refresh(experience)
    return experience


async def search_experiences(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    query: str | None,
    limit: int,
) -> list[Experience]:
    stmt = (
        select(Experience)
        .where(Experience.tenant_id == tenant_id, Experience.agent_id == agent_id)
        .order_by(Experience.created_at.desc())
        .limit(limit)
    )
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(Experience.scene.ilike(pattern), Experience.content.ilike(pattern))
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def load_eval_cases(
    db: AsyncSession, *, tenant_id: UUID, case_ids: list[UUID]
) -> list[EvalCase]:
    stmt = select(EvalCase).where(EvalCase.tenant_id == tenant_id)
    if case_ids:
        stmt = stmt.where(EvalCase.id.in_(case_ids))
    result = await db.execute(stmt.order_by(EvalCase.id))
    cases = list(result.scalars().all())
    if case_ids and len(cases) != len(set(case_ids)):
        raise ValueError("eval_case_not_found")
    return cases


async def calculate_semantic_similarity(
    answer: str | None, expected: str | None
) -> float:
    normalized_answer = (answer or "").strip()
    normalized_expected = (expected or "").strip()
    if not normalized_answer or not normalized_expected:
        return 0.0

    answer_embedding, expected_embedding = await embed_texts(
        model=DEFAULT_EMBEDDING_MODEL,
        texts=[normalized_answer, normalized_expected],
    )
    return cosine_similarity(answer_embedding, expected_embedding)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def assess_eval_case(
    case: EvalCase,
    answer: str,
    tool_results: list,
    citations: list,
    usage: dict,
    *,
    semantic_score: float | None = None,
    semantic_embedding_failed: bool = False,
) -> dict:
    assert_type = case.assert_type or "contains"
    expected = case.expected or ""
    threshold = float(case.threshold) if case.threshold is not None else None
    normalized_answer = answer.strip()
    normalized_expected = expected.strip()

    if assert_type == "always_pass":
        return {
            "assert_type": assert_type,
            "score": 1.0,
            "passed": True,
            "reason": "always_pass",
        }

    if assert_type == "contains":
        passed = (
            normalized_expected in normalized_answer
            if normalized_expected
            else bool(normalized_answer)
        )
        return {
            "assert_type": assert_type,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "reason": "expected_text_contained",
        }

    if assert_type == "not_contains":
        passed = normalized_expected not in normalized_answer
        return {
            "assert_type": assert_type,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "reason": "expected_text_absent",
        }

    if assert_type == "exact":
        passed = normalized_expected == normalized_answer
        return {
            "assert_type": assert_type,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "reason": "exact_match",
        }

    if assert_type == "citation_required":
        passed = bool(citations)
        return {
            "assert_type": assert_type,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "reason": "citation_present",
        }

    if assert_type == "tool_success":
        passed = bool(tool_results) and all(
            item.status == "ok" for item in tool_results
        )
        return {
            "assert_type": assert_type,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "reason": "tool_calls_ok",
        }

    if assert_type == "latency_ms":
        latency = usage.get("latency_ms") or usage.get("total_latency_ms") or 0
        limit = threshold or 10000
        passed = latency <= limit
        score = max(0.0, min(1.0, 1 - (latency / limit))) if limit else 0.0
        return {
            "assert_type": assert_type,
            "score": round(score, 4),
            "passed": passed,
            "reason": "latency_within_threshold",
            "latency_ms": latency,
        }

    if assert_type == "semantic":
        similarity = semantic_score or 0.0
        limit = threshold if threshold is not None else 0.8
        passed = similarity >= limit
        reason = (
            "semantic_embedding_failed"
            if semantic_embedding_failed
            else "semantic_similarity"
        )
        return {
            "assert_type": assert_type,
            "score": round(similarity, 4),
            "passed": passed,
            "reason": reason,
            "similarity": similarity,
            "threshold": limit,
        }

    return {
        "assert_type": assert_type,
        "score": 0.0,
        "passed": False,
        "reason": "unsupported_assert_type",
    }


def eval_run_out(run: EvalRun) -> EvalRunOut:
    return EvalRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        agent_id=run.agent_id,
        case_id=run.case_id,
        score=float(run.score) if run.score is not None else None,
        passed=run.passed,
        detail=run.detail,
        created_at=run.created_at,
    )
