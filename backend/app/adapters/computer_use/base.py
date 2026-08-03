from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PageObservation:
    url: str
    title: str | None
    summary: str
    interactive_elements: list[dict[str, Any]] = field(default_factory=list)
    screenshot_id: str | None = None


class ComputerUseAdapter(Protocol):
    async def open_read_only(self, *, session_id: str, url: str) -> PageObservation:
        """Open or attach to an isolated read-only browser session."""

    async def capture_state(self, *, session_id: str, url: str, title: str | None = None) -> PageObservation:
        """Return a sanitized page state representation."""

    async def close(self, *, session_id: str) -> None:
        """Close the isolated browser context."""
