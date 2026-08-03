from dataclasses import dataclass


SUSPICIOUS_PHRASES = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disable safety",
    "upload all files",
    "send your secret",
    "send secrets",
    "copy cookie",
    "copy cookies",
    "execute javascript",
    "run shell",
    "打开其他网站",
    "忽略之前的指令",
    "上传所有文件",
    "发送密钥",
    "禁用安全策略",
    "执行 javascript",
    "复制 cookie",
    "修改权限",
    "下载并运行文件",
)


@dataclass(frozen=True)
class PromptInjectionFinding:
    risk: bool
    flags: list[str]


def inspect_untrusted_page_text(text: str | None) -> PromptInjectionFinding:
    if not text:
        return PromptInjectionFinding(risk=False, flags=[])
    normalized = text.lower()
    flags = [phrase for phrase in SUSPICIOUS_PHRASES if phrase.lower() in normalized]
    return PromptInjectionFinding(risk=bool(flags), flags=flags)
