"""Chain-snapshot capture — the backtesting prerequisite (BotResearch run
20260708-0015, "parked" section).

The bot captures an option-chain snapshot every cycle and used to throw it
away, which is why no backtester can exist. This module persists one snapshot
per underlying per entry cycle to the Railway volume so a chain-replay harness
/ IV-rank signal becomes possible later. Fields are provider-specific: the
Alpaca adapter includes its available Greeks, while the optional Public raw
chain capture provides chain quotes and contract metadata without the
selector's per-contract quote/Greeks enrichment.

Layout: data/chain_snapshots/YYYY-MM-DD/<UNDERLYING>.jsonl.gz — one JSON row
per contract. Written atomically (tmp then rename). Always on (NOT gated on
EXPERIMENT_FLAG — it's approved standalone maintenance, not experiment
behavior). FAIL-OPEN: a capture error is logged and reported, never crashes
the entry cycle. Roughly ~1 MB/day gzipped across the 13-name watchlist; the
volume has ~48 GB free.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("optionsagent.chain_capture")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SNAPSHOT_ROOT = os.path.join(_DATA_DIR, "chain_snapshots")


def snapshot_path(underlying: str, day: str) -> str:
    return os.path.join(SNAPSHOT_ROOT, day, f"{underlying.upper()}.jsonl.gz")


def write_snapshot(underlying: str, rows: list[dict], day: str | None = None) -> str:
    """Write one underlying's chain rows for the day. Atomic: tmp + rename.
    Re-running the same day overwrites (last snapshot of the day wins)."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = snapshot_path(underlying, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    os.replace(tmp, path)
    return path


def capture_universe(client, symbols: list[str]) -> dict[str, int]:
    """Capture the full raw chain for every watchlist name. Per-symbol
    fail-open: one bad chain never blocks the others or the cycle.
    Returns {symbol: row_count} for the log (error -> -1)."""
    captured_at = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {}
    for sym in symbols:
        try:
            rows = client.option_chain_raw(sym)
            for row in rows:
                row["captured_at"] = captured_at
            write_snapshot(sym, rows)
            counts[sym] = len(rows)
        except Exception:
            log.exception("chain snapshot capture failed for %s (fail-open)", sym)
            counts[sym] = -1
    return counts
