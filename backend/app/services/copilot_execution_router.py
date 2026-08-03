from dataclasses import dataclass
from typing import Literal

from app.services.copilot_service import COPILOT_TOOL_REGISTRY

ExecutionMode = Literal["tool", "ui_command", "form_adapter", "browser_dom", "computer_use", "unsupported"]


@dataclass(frozen=True)
class ExecutionRoute:
    execution_mode: ExecutionMode
    reason: str
    matched_capability: str | None
    requires_user_consent: bool
    risk_level: str


class CopilotExecutionRouter:
    def resolve(
        self,
        *,
        intent: str,
        available_tools: list[str] | None = None,
        ui_commands: list[str] | None = None,
        form_adapters: list[str] | None = None,
        allow_browser_dom: bool = False,
        allow_computer_use: bool = False,
    ) -> ExecutionRoute:
        tool_names = set(available_tools or COPILOT_TOOL_REGISTRY.keys())
        if intent in tool_names:
            return ExecutionRoute("tool", "命中 Tool Registry 标准工具", intent, False, "L1")
        if intent in set(ui_commands or []):
            return ExecutionRoute("ui_command", "当前页面提供 UI Command", intent, False, "L1")
        if intent in set(form_adapters or []):
            return ExecutionRoute("form_adapter", "当前页面提供 Form Adapter", intent, False, "L2")
        if allow_browser_dom:
            return ExecutionRoute("browser_dom", "可通过受控 DOM 自动化完成", None, True, "L2")
        if allow_computer_use:
            return ExecutionRoute("computer_use", "标准工具、UI Command 和 Form Adapter 均不可用，进入浏览器操作模式兜底", None, True, "L1")
        return ExecutionRoute("unsupported", "没有匹配的可执行能力", None, False, "prohibited")
