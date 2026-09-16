"""Storage contract used by the application service."""
from __future__ import annotations

from typing import Protocol


class MemoryStore(Protocol):
    """Minimal persistence interface implemented by storage backends."""

    def add(self, observation: dict) -> bool:
        """Persist an observation and report whether it was newly added."""
        ...

    def all(self) -> list[dict]:
        """Return a snapshot of all observations."""
        ...

    def clear(self) -> None:
        """Remove all observations."""
        ...
