"""Small persistent state for multi-sweep exit confirmation.

Option-spread quotes can be temporarily wide, especially just after the open.
This file remembers consecutive stop observations across the 20-minute cron
processes so one noisy quote cannot liquidate a multi-day structure.
"""

from __future__ import annotations

import json
import os
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EXIT_STATE_PATH = os.path.join(_DATA_DIR, "exit_state.json")


def load(path: str | None = None) -> dict[str, Any]:
    path = path or EXIT_STATE_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save(state: dict[str, Any], path: str | None = None) -> None:
    path = path or EXIT_STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, sort_keys=True)
    os.replace(tmp, path)


def observe_stop(
    state: dict[str, Any],
    *,
    structure_id: str,
    triggered: bool,
    required: int,
    observed_at: str,
) -> bool:
    """Record one sweep and return True once consecutive evidence is enough."""
    if not triggered:
        state.pop(structure_id, None)
        return False
    previous = state.get(structure_id) or {}
    count = int(previous.get("count", 0)) + 1
    state[structure_id] = {"count": count, "observed_at": observed_at}
    return count >= max(1, int(required))

