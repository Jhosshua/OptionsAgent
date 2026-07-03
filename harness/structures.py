"""Open-structure registry — the exit sweep's source of truth for WHAT each
open position is (a bare Alpaca position list is just flat legs; it can't
tell a credit spread from two unrelated options).

Append-only events in data/structures.jsonl (same auditability convention as
decisions.jsonl): an "opened" event when run_cycle executes, a "closed" event
when the sweep exits (or detects assignment/manual close). load_open()
replays the events; reconcile() cross-checks against live broker positions.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STRUCTURES_PATH = os.path.join(_DATA_DIR, "structures.jsonl")


@dataclass(frozen=True)
class Leg:
    symbol: str      # OCC symbol
    side: str        # "short" | "long"
    right: str       # "call" | "put"
    strike: float
    expiry: str      # ISO date


@dataclass(frozen=True)
class Structure:
    structure_id: str  # == the decision_id that opened it
    underlying: str
    strategy_type: str
    contracts: int
    entry_net: float   # per-share: credit received (short premium) or debit paid (long)
    legs: list[Leg] = field(default_factory=list)
    opened_ts: str = ""


def _append(event: dict[str, Any], path: str | None = None) -> None:
    p = path or STRUCTURES_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def record_opened(structure: Structure, path: str | None = None) -> None:
    _append({"event": "opened", "ts": _now(), **asdict(structure)}, path)


def record_closed(structure_id: str, *, reason: str, pnl_usd: float | None, path: str | None = None) -> None:
    _append(
        {"event": "closed", "ts": _now(), "structure_id": structure_id, "reason": reason, "pnl_usd": pnl_usd},
        path,
    )


def load_open(path: str | None = None) -> list[Structure]:
    p = path or STRUCTURES_PATH
    if not os.path.exists(p):
        return []
    opened: dict[str, Structure] = {}
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event["event"] == "opened":
                opened[event["structure_id"]] = Structure(
                    structure_id=event["structure_id"],
                    underlying=event["underlying"],
                    strategy_type=event["strategy_type"],
                    contracts=int(event["contracts"]),
                    entry_net=float(event["entry_net"]),
                    legs=[Leg(**leg) for leg in event.get("legs", [])],
                    opened_ts=event.get("opened_ts") or event.get("ts", ""),
                )
            elif event["event"] == "closed":
                opened.pop(event["structure_id"], None)
    return list(opened.values())


def reconcile(
    structures: list[Structure], live_option_symbols: set[str]
) -> tuple[list[Structure], list[Structure]]:
    """Splits (intact, vanished). A structure is vanished if ANY of its legs
    is no longer a live broker position — assignment, expiration, or a
    manual close happened outside the bot. Vanished structures need an alert
    and a closed event, never silent removal."""
    intact, vanished = [], []
    for s in structures:
        if all(leg.symbol in live_option_symbols for leg in s.legs):
            intact.append(s)
        else:
            vanished.append(s)
    return intact, vanished


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
