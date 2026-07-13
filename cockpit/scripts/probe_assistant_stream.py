#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@localhost/probe")
os.environ.setdefault("JWT_SIGNING_KEY", "probe-only")

from app.clients.wanwu_bff import WanwuBFFClient  # noqa: E402
from app.services.sse_contract import AssistantStreamCollector  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="探测 wanwu assistant SSE 契约")
    parser.add_argument("--assistant-id", required=True, help="wanwu assistantId")
    parser.add_argument("--prompt", default="请用一句话回答：今天是一个测试吗？")
    parser.add_argument("--org-id", default=None)
    parser.add_argument("--sample-out", default="docs/integration/samples/assistant_stream_probe.jsonl")
    args = parser.parse_args()

    base_url = os.getenv("WANWU_BASE_URL", "http://localhost:8081")
    client = WanwuBFFClient(base_url=base_url, api_prefix="/service/api/v1")
    collector = AssistantStreamCollector()
    sample_path = Path(args.sample_out)
    sample_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = perf_counter()
    first_frame_at = None
    print(f"POST {base_url}/service/api/v1/assistant/stream/draft")
    print("登录接口源码证据：wanwu/internal/bff-service/server/http/handler/router/v1/guest.go")
    print("流式接口源码证据：wanwu/internal/bff-service/server/http/handler/router/v1/assistant.go")

    with sample_path.open("w", encoding="utf-8") as sample_file:
        async for data in client.stream_draft_assistant(args.assistant_id, args.prompt, args.org_id):
            if first_frame_at is None:
                first_frame_at = perf_counter()
            print(data)
            sample_file.write(data + "\n")
            sample_file.flush()
            try:
                collector.feed_sse_data(data)
            except json.JSONDecodeError:
                print(f"非 JSON 帧：{data}", file=sys.stderr)

    result = collector.result()
    total = perf_counter() - started_at
    summary = {
        "first_frame_latency_ms": int((first_frame_at - started_at) * 1000) if first_frame_at else None,
        "total_latency_ms": int(total * 1000),
        "frame_count": result.frame_count,
        "answer": result.answer,
        "conversation_id": result.conversation_id,
        "terminal_frame": result.terminal_frame,
        "error": result.error,
        "usage": result.usage,
        "sample_out": str(sample_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
