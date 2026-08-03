from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


CLEANING_VERSION = "m1_v1"
DEFAULT_MAX_REPEATED_LINE_LENGTH = 40
MIN_REPEATED_LINE_COUNT = 3

PAGE_NUMBER_PATTERNS = (
    re.compile(r"^\d{1,4}$"),
    re.compile(r"^-\s*\d{1,4}\s*-$"),
    re.compile(r"^第\s*\d{1,4}\s*页$"),
    re.compile(r"^page\s+\d{1,4}(?:\s+of\s+\d{1,4})?$", re.IGNORECASE),
)


@dataclass(frozen=True)
class CleanTextResult:
    text: str
    raw_chars: int
    cleaned_chars: int
    raw_lines: int
    cleaned_lines: int
    removed_lines: int
    removed_blank_lines: int
    removed_noise_lines: int
    cleaning_version: str


def clean_text(text: str, config: dict | None = None) -> CleanTextResult:
    options = config or {}
    enabled = bool(options.get("enabled", True))
    raw = normalize_newlines(text)
    raw_lines = raw.split("\n")
    if not enabled:
        cleaned = raw.strip()
        cleaned_lines = cleaned.split("\n") if cleaned else []
        return CleanTextResult(
            text=cleaned,
            raw_chars=len(text),
            cleaned_chars=len(cleaned),
            raw_lines=len(raw_lines),
            cleaned_lines=len(cleaned_lines),
            removed_lines=0,
            removed_blank_lines=0,
            removed_noise_lines=0,
            cleaning_version=CLEANING_VERSION,
        )

    remove_page_numbers = bool(options.get("remove_page_numbers", True))
    remove_repeated_headers = bool(options.get("remove_repeated_headers", True))
    max_repeated_line_length = int(
        options.get("max_repeated_line_length", DEFAULT_MAX_REPEATED_LINE_LENGTH)
    )

    without_control_chars = strip_control_chars(raw)
    stripped_lines = [line.strip() for line in without_control_chars.split("\n")]
    repeated_noise_lines = (
        detect_repeated_noise_lines(stripped_lines, max_repeated_line_length)
        if remove_repeated_headers
        else set()
    )

    cleaned_lines: list[str] = []
    removed_blank_lines = 0
    removed_noise_lines = 0
    previous_blank = False
    for line in stripped_lines:
        is_blank = line == ""
        if is_blank:
            if previous_blank:
                removed_blank_lines += 1
                continue
            cleaned_lines.append("")
            previous_blank = True
            continue

        previous_blank = False
        if remove_page_numbers and is_page_number_line(line):
            removed_noise_lines += 1
            continue
        if line in repeated_noise_lines:
            removed_noise_lines += 1
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    if not cleaned and raw.strip():
        cleaned = raw.strip()
        cleaned_lines = cleaned.split("\n")
        removed_blank_lines = 0
        removed_noise_lines = 0

    cleaned_line_count = len(cleaned.split("\n")) if cleaned else 0
    removed_lines = max(len(raw_lines) - cleaned_line_count, 0)
    return CleanTextResult(
        text=cleaned,
        raw_chars=len(text),
        cleaned_chars=len(cleaned),
        raw_lines=len(raw_lines),
        cleaned_lines=cleaned_line_count,
        removed_lines=removed_lines,
        removed_blank_lines=removed_blank_lines,
        removed_noise_lines=removed_noise_lines,
        cleaning_version=CLEANING_VERSION,
    )


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_control_chars(text: str) -> str:
    chars: list[str] = []
    for char in text:
        if char in {"\n", "\t"}:
            chars.append(char)
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        chars.append(char)
    return "".join(chars)


def is_page_number_line(line: str) -> bool:
    compact = " ".join(line.split())
    return any(pattern.match(compact) for pattern in PAGE_NUMBER_PATTERNS)


def detect_repeated_noise_lines(
    lines: list[str], max_repeated_line_length: int
) -> set[str]:
    candidates = [
        line
        for line in lines
        if 0 < len(line) <= max_repeated_line_length and is_repeated_noise_candidate(line)
    ]
    counts = Counter(candidates)
    return {
        line
        for line, count in counts.items()
        if count >= MIN_REPEATED_LINE_COUNT and count >= max(len(lines) // 12, 3)
    }


def is_repeated_noise_candidate(line: str) -> bool:
    if line.startswith(("#", "##")):
        return False
    if re.match(r"^\d+(?:\.\d+)+\s+", line):
        return False
    if re.match(r"^第[一二三四五六七八九十百千\d]+\s*[章节条]", line):
        return False
    if line.endswith(("：", ":")):
        return False
    return True
