from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any


DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "assistant_stream_contract.json"
)


@dataclass(frozen=True)
class AssistantStreamContract:
    code_field: str
    message_field: str
    content_field: str
    finish_field: str
    conversation_id_field: str
    usage_field: str
    success_code: int
    terminal_finish_values: set[int]
    content_mode: str
    error_fields: list[str]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONTRACT_PATH) -> "AssistantStreamContract":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        fields = data["fields"]
        return cls(
            code_field=fields["code"],
            message_field=fields["message"],
            content_field=fields["content"],
            finish_field=fields["finish"],
            conversation_id_field=fields["conversation_id"],
            usage_field=fields["usage"],
            success_code=int(data["success_code"]),
            terminal_finish_values={int(v) for v in data["terminal_finish_values"]},
            content_mode=data["content_mode"],
            error_fields=list(data["error_fields"]),
        )


@dataclass
class AssistantStreamResult:
    answer: str
    first_frame_latency_ms: int | None
    total_latency_ms: int
    frame_count: int
    conversation_id: str | None
    usage: dict[str, Any] | None
    raw_frames: list[dict[str, Any]]
    terminal_frame: dict[str, Any] | None
    error: str | None = None


@dataclass
class AssistantStreamCollector:
    contract: AssistantStreamContract = field(default_factory=AssistantStreamContract.load)
    started_at: float = field(default_factory=perf_counter)
    first_frame_at: float | None = None
    frames: list[dict[str, Any]] = field(default_factory=list)
    answer_parts: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    usage: dict[str, Any] | None = None
    terminal_frame: dict[str, Any] | None = None
    error: str | None = None

    def feed_sse_data(self, raw_data: str) -> dict[str, Any] | None:
        raw_data = raw_data.strip()
        if not raw_data:
            return None
        if raw_data == "[DONE]":
            self.terminal_frame = {"event": "[DONE]"}
            return self.terminal_frame

        frame = json.loads(raw_data)
        self.feed_frame(frame)
        return frame

    def feed_frame(self, frame: dict[str, Any]) -> None:
        now = perf_counter()
        if self.first_frame_at is None:
            self.first_frame_at = now
        self.frames.append(frame)

        code = frame.get(self.contract.code_field)
        if code != self.contract.success_code:
            self.error = self._extract_error(frame)
            self.terminal_frame = frame
            return

        content = frame.get(self.contract.content_field)
        if isinstance(content, str) and content:
            if self.contract.content_mode == "full":
                self.answer_parts = [content]
            else:
                self.answer_parts.append(content)

        conversation_id = frame.get(self.contract.conversation_id_field)
        if conversation_id:
            self.conversation_id = str(conversation_id)

        usage = frame.get(self.contract.usage_field)
        if isinstance(usage, dict) and usage:
            self.usage = usage

        finish = frame.get(self.contract.finish_field)
        if isinstance(finish, int) and finish in self.contract.terminal_finish_values:
            self.terminal_frame = frame

    def result(self) -> AssistantStreamResult:
        total_latency_ms = int((perf_counter() - self.started_at) * 1000)
        first_latency = None
        if self.first_frame_at is not None:
            first_latency = int((self.first_frame_at - self.started_at) * 1000)
        return AssistantStreamResult(
            answer="".join(self.answer_parts),
            first_frame_latency_ms=first_latency,
            total_latency_ms=total_latency_ms,
            frame_count=len(self.frames),
            conversation_id=self.conversation_id,
            usage=self.usage,
            raw_frames=self.frames,
            terminal_frame=self.terminal_frame,
            error=self.error,
        )

    def _extract_error(self, frame: dict[str, Any]) -> str:
        for field_name in self.contract.error_fields:
            value = frame.get(field_name)
            if value:
                return str(value)
        return "wanwu_stream_error"
