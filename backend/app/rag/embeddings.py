import httpx

from app.core.config import settings


async def embed_texts(*, model: str, texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.maas_base_url.rstrip('/')}/v1/embeddings",
            json={"model": model, "input": texts},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(maas_error_detail(exc)) from exc
        payload = response.json()

    data = sorted(payload["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def maas_error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        payload = exc.response.json()
    except ValueError:
        return "maas_embedding_failed"
    detail = payload.get("detail")
    return detail if isinstance(detail, str) and detail else "maas_embedding_failed"
