"""Shared market-data publisher — makes the SIP SPY/QQQ data + computed signals
this bot fetches available to the rest of the fleet (operator ask 2026-07-10).

Every minute during RTH it fetches 1-min bars for the configured underlyings and
appends ONE snapshot row per symbol to data/marketdata/<ET-date>.jsonl on the
Railway volume. A sibling relay (harness/marketdata_relay.py) serves that file over
a token-gated HTTPS GET so bots on OTHER Railway services can pull it — the same
proven pattern DTA uses for its orderflow relay.

Independent of the trading scalper: this runs whenever OA_MARKETDATA_ENABLED=true
(publishing the data is useful even when OA_SCALP_ENABLED is off). Fail-open per
symbol — one bad fetch never blocks the others.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from harness.signals_intraday import (
    breakout_check,
    latest_rvol,
    opening_range,
    regular_session_bars,
    session_vwap,
)

log = logging.getLogger("optionsagent.marketdata_publish")

ET = ZoneInfo("America/New_York")
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MARKETDATA_ROOT = os.path.join(_DATA_DIR, "marketdata")


def feed_path(et_date: str) -> str:
    return os.path.join(MARKETDATA_ROOT, f"{et_date}.jsonl")


def snapshot_row(bars: list[dict], et_date: str, symbol: str, *, rvol_min: float = 1.5) -> dict | None:
    """Build one shareable snapshot from a symbol's 1-min bars: the latest closed
    bar (raw Alpaca OHLCV) plus the computed signals (session VWAP, opening range,
    latest RVOL, and the current breakout direction if any). None if there are no
    regular-session bars yet."""
    session = regular_session_bars(bars, et_date)
    if not session:
        return None
    last = session[-1]
    rng = opening_range(bars, et_date, minutes=3)
    breakout = None
    if rng is not None:
        bo = breakout_check(bars, et_date, range_high=rng.high, range_low=rng.low, rvol_min=rvol_min)
        breakout = bo.direction if bo is not None else None
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "et_date": et_date,
        "et_time": last["et_time"],
        "symbol": symbol,
        "bar": {"o": last["o"], "h": last["h"], "l": last["l"], "c": last["c"], "v": last["v"]},
        "vwap": session_vwap(bars, et_date),
        "opening_range": ({"high": rng.high, "low": rng.low} if rng is not None else None),
        "rvol_latest": latest_rvol(bars, et_date),
        "breakout": breakout,
        "source": "optionsagent",
        "feed": "sip",
    }


def publish(client, symbols: list[str], *, rvol_min: float = 1.5, feed: str = "sip") -> dict[str, int]:
    """Fetch bars + append a snapshot row per symbol to today's feed file. Per-symbol
    fail-open. Returns {symbol: 1 written / 0 skipped / -1 error} for the log."""
    now_et = datetime.now(ET)
    et_date = now_et.strftime("%Y-%m-%d")
    path = feed_path(et_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    counts: dict[str, int] = {}
    for sym in symbols:
        try:
            bars = client.stock_minute_bars(sym, lookback_minutes=420, feed=feed)
            row = snapshot_row(bars, et_date, sym, rvol_min=rvol_min)
            if row is None:
                counts[sym] = 0
                continue
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            counts[sym] = 1
        except Exception:
            log.exception("marketdata publish failed for %s (fail-open)", sym)
            counts[sym] = -1
    return counts
