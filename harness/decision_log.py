"""Append-only decision log. Every decision is fully replayable.

Each line of data/decisions.jsonl is one decision: the LLM proposal, the
deterministic rail trace, the contract selected (if any), and the final
order(s). Mirrors DeterministicAgent's decision_log.py.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DECISIONS_PATH = os.path.join(_DATA_DIR, "decisions.jsonl")


def new_decision_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(decision: dict[str, Any], path: str | None = None) -> None:
    """Append one decision record as a JSON line. Creates data/ if needed."""
    p = path or DECISIONS_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(decision, default=str) + "\n")


def record_cycle_start(phase: str, path: str | None = None) -> str:
    cycle_id = f"{phase}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    record({"kind": "cycle_start", "cycle_id": cycle_id, "ts": now_iso(), "phase": phase}, path)
    return cycle_id


def read_all(path: str | None = None) -> list[dict[str, Any]]:
    p = path or DECISIONS_PATH
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
