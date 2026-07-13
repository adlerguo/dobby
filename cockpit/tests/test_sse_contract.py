import json
from pathlib import Path

from app.services.sse_contract import AssistantStreamCollector


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_assistant_stream_contract_builds_incremental_answer():
    collector = AssistantStreamCollector()
    for line in (FIXTURE_DIR / "assistant_stream_frames.jsonl").read_text().splitlines():
        collector.feed_frame(json.loads(line))

    result = collector.result()

    assert result.answer == "你好，我是测试回答。"
    assert result.frame_count == 2
    assert result.conversation_id == "conv-fixture-001"
    assert result.usage["total_tokens"] == 10
    assert result.error is None


def test_assistant_stream_contract_extracts_error():
    collector = AssistantStreamCollector()
    for line in (FIXTURE_DIR / "assistant_stream_error_frames.jsonl").read_text().splitlines():
        collector.feed_frame(json.loads(line))

    result = collector.result()

    assert result.error == "assistant not found"
    assert result.terminal_frame["code"] == 1001
