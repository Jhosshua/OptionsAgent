"""Append-only registry of 0DTE scalp positions — the scalper's OWN source of
truth, structurally like harness/structures.py but a SEPARATE file
(data/scalp_positions.jsonl) that the seller's run_exits.py never reads. This is
the primary isolation mechanism: the seller keys off structures.jsonl and can
never see a scalp leg; the scalper keys off this file (+ the per-day state) and
never touches structures.jsonl.

Scalp orders also carry the client_order_id prefix `oas-` (vs the seller's `oa-`)
as a belt-and-suspenders broker-side tag.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SCALP_POSITIONS_PATH = os.path.join(_DATA_DIR, "scalp_positions.jsonl")

SCALP_ORDER_PREFIX = "oas-"


@dataclass(frozen=True)
class ScalpPosition:
    scalp_id: str          # == the decision_id that opened it
    underlying: str
    option_symbol: str     # OCC
    right: str             # "call" | "put"
    direction: str         # "up" | "down"
    qty: int
    entry_price: float     # per-share option premium actually paid
    opened_ts: str = ""
    entry_order_id: str = ""


def _append(event: dict[str, Any], path: str | None = None) -> None:
    p = path or SCALP_POSITIONS_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_opened(pos: ScalpPosition, path: str | None = None) -> None:
    _append({"event": "opened", "ts": _now(), **asdict(pos)}, path)


def record_closed(
    scalp_id: str, *, reason: str, exit_price: float | None, pnl_usd: float | None,
    path: str | None = None,
) -> None:
    _append(
        {
            "event": "closed",
            "ts": _now(),
            "scalp_id": scalp_id,
            "reason": reason,
            "exit_price": exit_price,
            "pnl_usd": pnl_usd,
        },
        path,
    )


def load_open(path: str | None = None) -> list[ScalpPosition]:
    """Replay events -> the set of scalp positions still open."""
    p = path or SCALP_POSITIONS_PATH
    if not os.path.exists(p):
        return []
    opened: dict[str, ScalpPosition] = {}
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev["event"] == "opened":
                opened[ev["scalp_id"]] = ScalpPosition(
                    scalp_id=ev["scalp_id"],
                    underlying=ev["underlying"],
                    option_symbol=ev["option_symbol"],
                    right=ev["right"],
                    direction=ev["direction"],
                    qty=int(ev["qty"]),
                    entry_price=float(ev["entry_price"]),
                    opened_ts=ev.get("opened_ts") or ev.get("ts", ""),
                    entry_order_id=ev.get("entry_order_id", ""),
                )
            elif ev["event"] == "closed":
                opened.pop(ev["scalp_id"], None)
    return list(opened.values())


def exclude_scalp_symbols(live_option_symbols: set[str], path: str | None = None) -> set[str]:
    """Drop any currently-open scalp option symbol from a set of live broker option
    symbols, so the seller's run_exits.py reconcile can never reason about a scalp
    leg. Fail-open: any error returns the input set unchanged (the structural
    isolation — separate registry + disjoint symbols — already holds without this)."""
    try:
        scalp_symbols = {p.option_symbol for p in load_open(path=path)}
        return set(live_option_symbols) - scalp_symbols
    except Exception:
        return set(live_option_symbols)


def is_scalp_order(client_order_id: str | None) -> bool:
    """True if an order's client_order_id belongs to the scalper (prefix oas-).
    Used by run_exits.py as a belt-and-suspenders guard so the seller sweep never
    acts on a scalp leg even if one somehow appeared in its position list."""
    return bool(client_order_id) and str(client_order_id).startswith(SCALP_ORDER_PREFIX)
