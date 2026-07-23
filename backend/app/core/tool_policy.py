from app.core.config import settings
from app.models import Tool


def is_code_tool(tool: Tool) -> bool:
    config = tool.config or {}
    builtin = str(config.get("builtin") or "").lower()
    return tool.type == "code" or builtin in {"code", "python", "shell", "sandbox"}


def is_code_tool_allowed(tool: Tool) -> bool:
    if settings.enable_auto_code_tools:
        return True
    allowlist = {
        item.strip() for item in settings.code_tool_allowlist.split(",") if item.strip()
    }
    return tool.name in allowlist or str(tool.id) in allowlist
