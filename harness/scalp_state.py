"""Per-trading-day state for the 0DTE ORB scalper.

Separate cron invocations (one per minute) share state through ONE mutable JSON
file per ET date on the Railway volume: data/scalp_state/<YYYY-MM-DD>.json. Written
atomically (tmp + os.replace). This is the seller-independent analogue of how the
seller shares data/structures.jsonl — the scalper never reads or writes the seller's
files, and vice versa.

State machine (per underlying):
  WAITING_FOR_RANGE -> RANGE_SET -> WATCHING_FOR_BREAK -> IN_TRADE
    -> (back to WATCHING_FOR_BREAK for re-entry, or DONE) ; account-level HALTED
"""

from __future__ import annotations

import json
import os
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STATE_ROOT = os.path.join(_DATA_DIR, "scalp_state")


def state_path(et_date: str) -> str:
    return os.path.join(STATE_ROOT, f"{et_date}.json")


def _fresh(et_date: str, underlyings: list[str]) -> dict[str, Any]:
    return {
        "date": et_date,
        "trades_today": 0,
        "realized_pnl_usd": 0.0,
        "halted": False,
        "halt_reason": None,
        "underlyings": {
            u: {
                "state": "WAITING_FOR_RANGE",
                "range_high": None,
                "range_low": None,
                "last_evaluated_bar_ts": None,
                "pending_breakout": None,
                "traded_directions": [],
                "position": None,
            }
            for u in underlyings
        },
    }


def load_state(et_date: str, underlyings: list[str]) -> dict[str, Any]:
    """Load the day's state, or a fresh skeleton if missing/corrupt (fail-open — a
    live position is re-adopted from the broker by the runner's reconcile, never
    from a trusted-but-missing file). Ensures every configured underlying has a
    block even if the file predates a config change."""
    path = state_path(et_date)
    if not os.path.exists(path):
        return _fresh(et_date, underlyings)
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except Exception:
        return _fresh(et_date, underlyings)
    st.setdefault("date", et_date)
    st.setdefault("trades_today", 0)
    st.setdefault("realized_pnl_usd", 0.0)
    st.setdefault("halted", False)
    st.setdefault("halt_reason", None)
    ul = st.setdefault("underlyings", {})
    for u in underlyings:
        ul.setdefault(
            u,
            {
                "state": "WAITING_FOR_RANGE",
                "range_high": None,
                "range_low": None,
                "last_evaluated_bar_ts": None,
                "pending_breakout": None,
                "traded_directions": [],
                "position": None,
            },
        )
        ul[u].setdefault("pending_breakout", None)
        ul[u].setdefault("traded_directions", [])
    return st


def save_state(state: dict[str, Any]) -> None:
    """Atomic write: tmp + os.replace, so a crash mid-write never corrupts the file."""
    et_date = state["date"]
    path = state_path(et_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, default=str)
    os.replace(tmp, path)


def open_scalp_count(state: dict[str, Any]) -> int:
    """How many underlyings currently hold a scalp position."""
    return sum(1 for blk in state.get("underlyings", {}).values() if blk.get("position"))
