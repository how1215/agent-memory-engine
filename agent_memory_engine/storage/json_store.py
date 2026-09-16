"""Small, durable JSON store for memory observations."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path


def _is_observation(value: object) -> bool:
    """Return whether a decoded value has the fields retrieval requires."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("summary"), str)
        and isinstance(value.get("tags", []), list)
    )


class JsonStore:
    def __init__(self, path: str):
        self.path = str(Path(path).expanduser())
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        """Load observations, treating missing or malformed files as empty."""
        self.items = []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(data, list):
            self.items = [item for item in data if _is_observation(item)]

    def _persist(self) -> None:
        """Atomically replace the store so interrupted writes cannot corrupt it."""
        destination = Path(self.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self.items, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, destination)
        except BaseException:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise

    def add(self, obs: dict) -> bool:
        """Persist an observation unless another item already has its ID."""
        if "id" not in obs:
            raise ValueError("observation must contain an 'id'")
        if any(o.get("id") == obs["id"] for o in self.items):
            return False
        self.items.append(obs)
        self._persist()
        return True

    def all(self) -> list[dict]:
        """Return a shallow snapshot of all observations."""
        return list(self.items)

    def clear(self) -> None:
        """Remove all observations and persist the empty store."""
        self.items = []
        self._persist()
