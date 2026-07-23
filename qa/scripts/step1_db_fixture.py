import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Role, Tenant, User, UserRole
from app.services.rbac_service import ensure_roles_for_tenant


ROLE_NAME = {
    "builder": "构建者",
    "member": "普通成员",
}


def now_ts() -> str:
    return os.getenv("STEP1_TS") or str(int(datetime.now(UTC).timestamp()))


async def get_or_create_tenant(db, *, code: str, name: str, tenant_id: str | None = None) -> Tenant:
    tenant = None
    if tenant_id:
        tenant = await db.get(Tenant, UUID(tenant_id))
    if tenant is None:
        result = await db.execute(select(Tenant).where(Tenant.code == code))
        tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=name, code=code, status="active")
        db.add(tenant)
        await db.flush()
    else:
        tenant.name = tenant.name or name
        tenant.status = "active"
    await ensure_roles_for_tenant(db, tenant.id)
    return tenant


async def upsert_user(db, *, tenant: Tenant, username: str, password: str, display_name: str, role_code: str) -> User:
    result = await db.execute(select(User).where(User.tenant_id == tenant.id, User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            tenant_id=tenant.id,
            username=username,
            password_hash=hash_password(password),
            display_name=display_name,
            email=f"{username}@qa.local",
            status="active",
        )
        db.add(user)
        await db.flush()
    else:
        user.password_hash = hash_password(password)
        user.display_name = display_name
        user.email = f"{username}@qa.local"
        user.status = "active"
    await set_single_role(db, user=user, tenant_id=tenant.id, role_code=role_code)
    return user


async def set_single_role(db, *, user: User, tenant_id, role_code: str) -> None:
    result = await db.execute(select(Role).where(Role.tenant_id == tenant_id, Role.code == role_code))
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"role_not_found:{role_code}:{tenant_id}")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()


async def set_user_status(db, *, tenant_code: str, username: str, status: str) -> None:
    result = await db.execute(select(Tenant).where(Tenant.code == tenant_code))
    tenant = result.scalar_one()
    result = await db.execute(select(User).where(User.tenant_id == tenant.id, User.username == username))
    user = result.scalar_one()
    user.status = status
    await db.flush()


async def set_tenant_status(db, *, tenant_code: str, status: str) -> None:
    result = await db.execute(select(Tenant).where(Tenant.code == tenant_code))
    tenant = result.scalar_one()
    tenant.status = status
    await db.flush()


async def main() -> None:
    action = os.getenv("STEP1_ACTION", "upsert")
    async with SessionLocal() as db:
        if action == "upsert":
            ts = now_ts()
            tenant_a_code = os.getenv("STEP1_TENANT_A_CODE") or f"qa-a-{ts}"
            tenant_b_code = os.getenv("STEP1_TENANT_B_CODE") or f"qa-b-{ts}"
            role_code = os.getenv("STEP1_ROLE", "builder")
            alice_password = os.getenv("STEP1_ALICE_PASSWORD") or f"QaAlice{ts}!"
            bob_password = os.getenv("STEP1_BOB_PASSWORD") or f"QaBob{ts}!"
            tenant_a = await get_or_create_tenant(
                db,
                code=tenant_a_code,
                name=f"QA Tenant A {ts}",
                tenant_id=os.getenv("STEP1_TENANT_A_ID"),
            )
            tenant_b = await get_or_create_tenant(db, code=tenant_b_code, name=f"QA Tenant B {ts}")
            alice = await upsert_user(
                db,
                tenant=tenant_a,
                username=f"alice-{ts}",
                password=alice_password,
                display_name="QA Alice",
                role_code=role_code,
            )
            bob = await upsert_user(
                db,
                tenant=tenant_b,
                username=f"bob-{ts}",
                password=bob_password,
                display_name="QA Bob",
                role_code=role_code,
            )
            await db.commit()
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "ts": ts,
                        "initial_role": role_code,
                        "tenants": {
                            "A": {"id": str(tenant_a.id), "code": tenant_a.code, "name": tenant_a.name},
                            "B": {"id": str(tenant_b.id), "code": tenant_b.code, "name": tenant_b.name},
                        },
                        "users": {
                            "alice": {
                                "id": str(alice.id),
                                "tenant_id": str(alice.tenant_id),
                                "username": alice.username,
                                "password": alice_password,
                                "role": role_code,
                            },
                            "bob": {
                                "id": str(bob.id),
                                "tenant_id": str(bob.tenant_id),
                                "username": bob.username,
                                "password": bob_password,
                                "role": role_code,
                            },
                        },
                        "resources": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        tenant_a_code = os.environ["STEP1_TENANT_A_CODE"]
        tenant_b_code = os.environ["STEP1_TENANT_B_CODE"]
        alice_username = os.environ["STEP1_ALICE_USERNAME"]
        bob_username = os.environ["STEP1_BOB_USERNAME"]

        if action in {"set_member", "set_role"}:
            target_role = "member" if action == "set_member" else os.environ["STEP1_ROLE_TARGET"]
            for tenant_code, username in [(tenant_a_code, alice_username), (tenant_b_code, bob_username)]:
                tenant = (await db.execute(select(Tenant).where(Tenant.code == tenant_code))).scalar_one()
                user = (
                    await db.execute(select(User).where(User.tenant_id == tenant.id, User.username == username))
                ).scalar_one()
                await set_single_role(db, user=user, tenant_id=tenant.id, role_code=target_role)
                user.status = "active"
                tenant.status = "active"
            await db.commit()
            print(json.dumps({"status": "roles_set", "role": target_role}, ensure_ascii=False))
            return

        if action == "alice_status":
            await set_user_status(db, tenant_code=tenant_a_code, username=alice_username, status=os.environ["STEP1_STATUS"])
            await db.commit()
            print(json.dumps({"status": "alice_status_set", "value": os.environ["STEP1_STATUS"]}))
            return

        if action == "tenant_b_status":
            await set_tenant_status(db, tenant_code=tenant_b_code, status=os.environ["STEP1_STATUS"])
            await db.commit()
            print(json.dumps({"status": "tenant_b_status_set", "value": os.environ["STEP1_STATUS"]}))
            return

        if action == "restore_active":
            await set_user_status(db, tenant_code=tenant_a_code, username=alice_username, status="active")
            await set_user_status(db, tenant_code=tenant_b_code, username=bob_username, status="active")
            await set_tenant_status(db, tenant_code=tenant_a_code, status="active")
            await set_tenant_status(db, tenant_code=tenant_b_code, status="active")
            await db.commit()
            print(json.dumps({"status": "restored_active"}))
            return

        raise RuntimeError(f"unknown_action:{action}")


if __name__ == "__main__":
    asyncio.run(main())
