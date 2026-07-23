from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    AgentTemplate,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
)
from app.services.agent_templates import AGENT_TEMPLATES, default_config

PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("tenant:view", "查看租户", "tenant"),
    ("tenant:create", "创建租户", "tenant"),
    ("tenant:update", "更新租户", "tenant"),
    ("user:view", "查看用户", "user"),
    ("user:create", "创建用户", "user"),
    ("user:update", "更新用户", "user"),
    ("user:assign_role", "授予角色", "user"),
    ("role:view", "查看角色", "role"),
    ("permission:view", "查看权限", "permission"),
    ("kb:create", "创建知识库", "kb"),
    ("agent:publish", "发布智能体", "agent"),
    ("maas:admin", "管理模型渠道", "maas"),
    ("dashboard:view", "查看驾驶舱", "dashboard"),
    ("audit:view", "查看审计", "audit"),
)

ROLE_NAMES: dict[str, str] = {
    "super_admin": "平台管理员",
    "tenant_admin": "租户管理员",
    "builder": "构建者",
    "member": "普通成员",
}

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "super_admin": tuple(code for code, _, _ in PERMISSIONS),
    "tenant_admin": (
        "tenant:view",
        "user:view",
        "user:create",
        "user:update",
        "user:assign_role",
        "role:view",
        "permission:view",
        "kb:create",
        "agent:publish",
        "dashboard:view",
        "audit:view",
    ),
    "builder": ("kb:create", "agent:publish", "dashboard:view"),
    "member": ("dashboard:view",),
}


async def get_by_code(
    db: AsyncSession, model: type, code: str, tenant_id: UUID | None = None
):
    stmt = select(model).where(model.code == code)
    if tenant_id is not None:
        stmt = stmt.where(model.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_permissions(db: AsyncSession) -> dict[str, Permission]:
    permissions: dict[str, Permission] = {}
    for code, name, module in PERMISSIONS:
        permission = await get_by_code(db, Permission, code)
        if permission is None:
            permission = Permission(code=code, name=name, module=module)
            db.add(permission)
            await db.flush()
        permissions[code] = permission
    return permissions


async def ensure_roles_for_tenant(db: AsyncSession, tenant_id: UUID) -> dict[str, Role]:
    permissions = await ensure_permissions(db)
    roles: dict[str, Role] = {}

    for code, name in ROLE_NAMES.items():
        role = await get_by_code(db, Role, code, tenant_id)
        if role is None:
            role = Role(tenant_id=tenant_id, code=code, name=name)
            db.add(role)
            await db.flush()
        roles[code] = role

        await ensure_role_permissions(
            db, role.id, permissions_for_codes(permissions, ROLE_PERMISSIONS[code])
        )

    return roles


def permissions_for_codes(
    permissions: dict[str, Permission], codes: Iterable[str]
) -> list[Permission]:
    return [permissions[code] for code in codes]


async def ensure_role_permissions(
    db: AsyncSession, role_id: UUID, permissions: Iterable[Permission]
) -> None:
    for permission in permissions:
        stmt = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission.id,
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            db.add(RolePermission(role_id=role_id, permission_id=permission.id))


async def assign_role_codes(
    db: AsyncSession, user_id: UUID, tenant_id: UUID, role_codes: list[str]
) -> list[str]:
    assigned: list[str] = []
    for role_code in role_codes:
        role = await get_by_code(db, Role, role_code, tenant_id)
        if role is None:
            raise ValueError(f"role_not_found:{role_code}")

        stmt = select(UserRole).where(
            UserRole.user_id == user_id, UserRole.role_id == role.id
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            db.add(UserRole(user_id=user_id, role_id=role.id))
        assigned.append(role.code)

    await db.flush()
    return assigned


async def ensure_default_seed(db: AsyncSession) -> None:
    tenant = await get_by_code(db, Tenant, "default")
    if tenant is None:
        tenant = Tenant(name="默认租户", code="default", status="active")
        db.add(tenant)
        await db.flush()

    roles = await ensure_roles_for_tenant(db, tenant.id)

    stmt = select(User).where(User.tenant_id == tenant.id, User.username == "admin")
    result = await db.execute(stmt)
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = User(
            tenant_id=tenant.id,
            username="admin",
            password_hash=hash_password("Admin123!"),
            display_name="平台管理员",
            email="admin@example.local",
            status="active",
        )
        db.add(admin)
        await db.flush()

    await assign_role_codes(db, admin.id, tenant.id, [roles["super_admin"].code])
    await ensure_agent_templates(db)


async def ensure_agent_templates(db: AsyncSession) -> None:
    for template in AGENT_TEMPLATES:
        stmt = select(AgentTemplate).where(AgentTemplate.type == template["type"])
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(
                AgentTemplate(
                    type=template["type"],
                    name=template["name"],
                    default_config=default_config(template),
                    builtin=True,
                )
            )
