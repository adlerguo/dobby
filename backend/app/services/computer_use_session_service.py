from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.computer_use import ComputerUseAdapter, PlaywrightComputerUseAdapter
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.models import ComputerUseAction, ComputerUseSession, ComputerUseTarget
from app.schemas.computer_use import (
    ComputerUseCaptureIn,
    ComputerUseCaptureOut,
    ComputerUseConsentIn,
    ComputerUsePageState,
    ComputerUseSessionOut,
    ComputerUseTargetCreate,
)
from app.services.computer_use_audit_service import write_computer_use_audit
from app.services.computer_use_policy import (
    ensure_computer_use_enabled,
    require_url_allowed,
    validate_target,
)
from app.services.computer_use_prompt_injection_guard import inspect_untrusted_page_text
from app.services.computer_use_sanitizer import sanitize_value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_target(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: ComputerUseTargetCreate,
) -> ComputerUseTarget:
    target = ComputerUseTarget(
        tenant_id=tenant_id,
        workspace_id=payload.workspace_id,
        name=payload.name.strip(),
        description=payload.description,
        allowed_domains=[domain.strip().lower() for domain in payload.allowed_domains if domain.strip()],
        allowed_url_patterns=payload.allowed_url_patterns,
        denied_url_patterns=payload.denied_url_patterns,
        allow_navigation=payload.allow_navigation,
        allow_form_fill=False,
        allow_submit=False,
        allow_upload=False,
        allow_download=False,
        allow_login=False,
        allow_persistent_session=False,
        max_session_minutes=min(payload.max_session_minutes, settings.computer_use_max_session_minutes),
        max_actions=min(payload.max_actions, settings.computer_use_max_actions),
        enabled=payload.enabled,
        created_by=user_id,
    )
    db.add(target)
    await db.flush()
    await write_computer_use_audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="computer_use.target_create",
        target_id=target.id,
        detail={"name": target.name, "enabled": target.enabled, "allowed_domains": target.allowed_domains},
        commit=False,
    )
    await db.commit()
    await db.refresh(target)
    return target


async def list_targets(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID | None = None,
    enabled_only: bool = False,
) -> list[ComputerUseTarget]:
    stmt = select(ComputerUseTarget).where(ComputerUseTarget.tenant_id == tenant_id)
    if workspace_id is not None:
        stmt = stmt.where((ComputerUseTarget.workspace_id == workspace_id) | (ComputerUseTarget.workspace_id.is_(None)))
    if enabled_only:
        stmt = stmt.where(ComputerUseTarget.enabled.is_(True))
    result = await db.execute(stmt.order_by(ComputerUseTarget.created_at.desc()))
    return list(result.scalars().all())


async def get_target(db: AsyncSession, *, tenant_id: UUID, target_id: UUID) -> ComputerUseTarget:
    target = await db.get(ComputerUseTarget, target_id)
    if target is None or target.tenant_id != tenant_id:
        raise NotFoundError(code="computer_use_target_not_found", message="目标系统不存在")
    return target


async def create_read_only_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: ComputerUseConsentIn,
    adapter: ComputerUseAdapter | None = None,
) -> ComputerUseSession:
    ensure_computer_use_enabled()
    if not payload.consent_approved:
        raise ValidationError(code="computer_use_consent_required", message="进入浏览器操作模式前需要用户授权")
    target = await get_target(db, tenant_id=tenant_id, target_id=payload.target_id)
    validate_target(target)
    require_url_allowed(payload.start_url, target)

    now = utcnow()
    session = ComputerUseSession(
        tenant_id=tenant_id,
        workspace_id=payload.workspace_id,
        user_id=user_id,
        conversation_id=payload.conversation_id,
        target_id=target.id,
        status="initializing",
        execution_mode="read_only_browser",
        current_url=payload.start_url,
        current_title=None,
        allowed_domains=target.allowed_domains,
        user_goal=payload.user_goal.strip(),
        approved_plan={
            "phase": "4A",
            "mode": "read_only_browser",
            "steps": ["open_page", "inspect_page", "capture_state"],
            "no_write_actions": True,
            **(payload.approved_plan or {}),
        },
        risk_level="L1",
        started_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(minutes=target.max_session_minutes),
        browser_context_ref=None,
    )
    db.add(session)
    await db.flush()

    observation = await (adapter or PlaywrightComputerUseAdapter()).open_read_only(session_id=str(session.id), url=payload.start_url)
    session.status = "running"
    session.current_url = observation.url
    session.current_title = observation.title
    session.last_activity_at = utcnow()
    session.browser_context_ref = f"computer-use-session:{session.id}"
    await add_action(
        db,
        session=session,
        action_type="open_session",
        target_description=payload.user_goal,
        before_url=None,
        after_url=session.current_url,
        after_screenshot_id=observation.screenshot_id,
        status="succeeded",
    )
    await write_computer_use_audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="computer_use.session_start",
        session_id=session.id,
        target_id=target.id,
        detail={
            "start_url": session.current_url,
            "target_name": target.name,
            "allowed_domains": target.allowed_domains,
            "execution_mode": session.execution_mode,
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID,
    allow_all_users: bool = False,
) -> ComputerUseSession:
    session = await db.get(ComputerUseSession, session_id)
    if session is None or session.tenant_id != tenant_id:
        raise NotFoundError(code="computer_use_session_not_found", message="浏览器会话不存在")
    if not allow_all_users and session.user_id != user_id:
        raise NotFoundError(code="computer_use_session_not_found", message="浏览器会话不存在")
    return session


async def capture_session_state(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID,
    payload: ComputerUseCaptureIn,
    adapter: ComputerUseAdapter | None = None,
) -> ComputerUseCaptureOut:
    session = await get_session(db, tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    if session.status not in {"running", "paused"}:
        raise ValidationError(code="computer_use_session_not_running", message="当前会话不能观察页面")
    target = await get_target(db, tenant_id=tenant_id, target_id=session.target_id)
    action_count = await count_session_actions(db, session.id)
    if action_count >= target.max_actions:
        await pause_session_for_security(
            db,
            session=session,
            user_id=user_id,
            code="computer_use_max_actions_reached",
            message="浏览器操作模式已达到最大动作数，已暂停会话",
            detail={"max_actions": target.max_actions},
        )
        raise ValidationError(code="computer_use_max_actions_reached", message="浏览器操作模式已达到最大动作数")
    observed_url = payload.current_url or session.current_url
    if not observed_url:
        raise ValidationError(code="computer_use_missing_url", message="缺少当前页面 URL")
    try:
        require_url_allowed(observed_url, target)
    except ValidationError as exc:
        await pause_session_for_security(
            db,
            session=session,
            user_id=user_id,
            code=exc.code,
            message=exc.message,
            detail={"url": observed_url},
        )
        raise
    finding = inspect_untrusted_page_text(payload.visible_text)
    if finding.risk:
        await pause_session_for_security(
            db,
            session=session,
            user_id=user_id,
            code="computer_use_prompt_injection_detected",
            message="页面内容包含疑似提示注入文本，已暂停会话",
            detail={"flags": finding.flags, "url": observed_url},
        )
        raise ValidationError(
            code="computer_use_prompt_injection_detected",
            message="页面内容包含疑似提示注入文本，已暂停会话",
            detail={"flags": finding.flags},
        )

    before_url = session.current_url
    observation = await (adapter or PlaywrightComputerUseAdapter()).capture_state(
        session_id=str(session.id),
        url=observed_url,
        title=payload.page_title,
    )
    session.current_url = observation.url
    session.current_title = observation.title
    session.last_activity_at = utcnow()
    action = await add_action(
        db,
        session=session,
        action_type="capture_state",
        target_description="只读页面观察",
        before_url=before_url,
        after_url=observation.url,
        after_screenshot_id=observation.screenshot_id,
        status="succeeded",
    )
    await write_computer_use_audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="computer_use.capture_state",
        session_id=session.id,
        target_id=session.target_id,
        detail={"url": observation.url, "title": observation.title},
        commit=False,
    )
    await db.commit()
    await db.refresh(session)
    await db.refresh(action)
    return ComputerUseCaptureOut(
        session=ComputerUseSessionOut.model_validate(session),
        action=action,
        page_state=ComputerUsePageState(
            url=observation.url,
            title=observation.title,
            summary=observation.summary,
            interactive_elements=sanitize_value(observation.interactive_elements),
            screenshot_id=observation.screenshot_id,
            risk_flags=[],
        ),
    )


async def stop_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID,
    reason: str = "user_stop",
    adapter: ComputerUseAdapter | None = None,
) -> ComputerUseSession:
    session = await get_session(db, tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    if session.status not in {"stopped", "succeeded", "failed", "expired"}:
        await (adapter or PlaywrightComputerUseAdapter()).close(session_id=str(session.id))
        now = utcnow()
        session.status = "stopped"
        session.stopped_at = now
        session.last_activity_at = now
        session.stop_reason = reason
        await add_action(
            db,
            session=session,
            action_type="stop",
            target_description=reason,
            before_url=session.current_url,
            after_url=session.current_url,
            status="succeeded",
        )
        await write_computer_use_audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="computer_use.session_stop",
            session_id=session.id,
            target_id=session.target_id,
            detail={"reason": reason, "url": session.current_url},
            commit=False,
        )
        await db.commit()
        await db.refresh(session)
    return session


async def pause_session_for_security(
    db: AsyncSession,
    *,
    session: ComputerUseSession,
    user_id: UUID,
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    now = utcnow()
    events = list(session.security_events or [])
    events.append({"code": code, "message": message, "detail": sanitize_value(detail or {}), "at": now.isoformat()})
    session.security_events = events
    session.status = "paused"
    session.paused_at = now
    session.last_activity_at = now
    await add_action(
        db,
        session=session,
        action_type="security_pause",
        target_description=message,
        before_url=session.current_url,
        after_url=session.current_url,
        status="failed",
        error_code=code,
        error_message=message,
    )
    await write_computer_use_audit(
        db,
        tenant_id=session.tenant_id,
        user_id=user_id,
        action="computer_use.security_pause",
        session_id=session.id,
        target_id=session.target_id,
        detail={"code": code, "message": message, **(detail or {})},
        commit=False,
    )
    await db.commit()
    await db.refresh(session)


async def add_action(
    db: AsyncSession,
    *,
    session: ComputerUseSession,
    action_type: str,
    target_description: str | None,
    before_url: str | None,
    after_url: str | None,
    status: str,
    after_screenshot_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ComputerUseAction:
    sequence = await count_session_actions(db, session.id) + 1
    action = ComputerUseAction(
        tenant_id=session.tenant_id,
        session_id=session.id,
        sequence=sequence,
        action_type=action_type,
        target_description=target_description,
        sanitized_input={},
        before_url=before_url,
        after_url=after_url,
        after_screenshot_id=after_screenshot_id,
        status=status,
        risk_level="L1",
        requires_confirmation=False,
        error_code=error_code,
        error_message=error_message,
        completed_at=utcnow(),
    )
    db.add(action)
    await db.flush()
    return action


async def count_session_actions(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(select(func.count(ComputerUseAction.id)).where(ComputerUseAction.session_id == session_id))
    return int(result.scalar() or 0)
