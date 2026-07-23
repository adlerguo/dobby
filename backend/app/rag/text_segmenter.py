import logging
import re
from collections.abc import Iterable

logger = logging.getLogger(__name__)

_jieba = None
_jieba_checked = False
_jieba_warning_logged = False


def segment_for_search(text: str) -> str:
    if not text:
        return ""
    if contains_cjk(text):
        return " ".join(tokenize_cjk(text))
    return " ".join(text.split())


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def tokenize_cjk(text: str) -> list[str]:
    jieba = load_jieba()
    if jieba is not None:
        return normalize_tokens(jieba.cut(text, cut_all=False))
    return normalize_tokens(re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", text))


def normalize_tokens(tokens: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for token in tokens:
        item = token.strip()
        if not item or re.fullmatch(r"\W+", item):
            continue
        normalized.append(item)
    return normalized


def load_jieba():
    global _jieba, _jieba_checked, _jieba_warning_logged
    if _jieba_checked:
        return _jieba
    _jieba_checked = True
    try:
        import jieba
    except Exception as exc:
        if not _jieba_warning_logged:
            logger.warning(
                "jieba unavailable; falling back to basic CJK tokenization: %s", exc
            )
            _jieba_warning_logged = True
        return None
    _jieba = jieba
    return _jieba
