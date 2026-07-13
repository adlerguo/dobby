import asyncio

from app.core.database import SessionLocal
from app.services import ensure_default_seed


async def main() -> None:
    async with SessionLocal() as db:
        await ensure_default_seed(db)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
