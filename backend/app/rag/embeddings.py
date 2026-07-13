import httpx

from app.core.config import settings


async def embed_texts(*, model: str, texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.maas_base_url.rstrip('/')}/v1/embeddings",
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()

    data = sorted(payload["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]
