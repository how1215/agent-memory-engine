"""Environment-based configuration shared by the engine and adapters."""
from __future__ import annotations

import os
from pathlib import Path


def env(name: str, legacy_name: str | None = None, default: str | None = None) -> str | None:
    """Read a setting, accepting a deprecated Pi-specific alias during migration."""
    value = os.environ.get(name)
    if value is not None:
        return value
    if legacy_name is not None:
        value = os.environ.get(legacy_name)
        if value is not None:
            return value
    return default


def default_store_path() -> str:
    """Return the framework-neutral default path for the local JSON backend."""
    configured = env("AGENT_MEMORY_PATH", "PI_MEMORY_PATH")
    return configured or str(Path.home() / ".agent-memory.json")
