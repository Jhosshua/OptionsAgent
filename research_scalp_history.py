#!/usr/bin/env python3
"""Audit and conditional-replay the archived 0DTE scalp history.

This is intentionally a research report, not a live trading component. It
replays only fills that actually occurred in the archived log, so a filtered
P/L is conditional on the old signal/contract selector having produced that
fill. It is not a complete options backtest and must not be read as one.

Usage:
    python3 research_scalp_history.py
    python3 research_scalp_history.py --data-dir data
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Trade:
    scalp_id: str
    date: str
    opened_et: str
    closed_et: str
    underlying: str
    direction: str
    rvol: float | None
    qty: int
    entry_price: float
    exit_price: float | None
    pnl_usd: float | None
    reason: str

    @property
    def entry_minutes(self) -> int:
        hour, minute = (int(part) for part in self.opened_et.split(":"))
        return hour * 60 + minute


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def _et(iso_ts: str) -> datetime:
    value = datetime.fromisoformat(iso_ts)
    if value.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {iso_ts}")
    return value.astimezone(ET)


def load_trades(data_dir: Path) -> list[Trade]:
    positions = _read_jsonl(data_dir / "scalp_positions.jsonl")
    decisions = _read_jsonl(data_dir / "scalp_decisions.jsonl")
    metadata = {
        row["decision_id"]: row
        for row in decisions
        if row.get("kind") == "scalp_open" and row.get("decision_id")
    }
    opened: dict[str, dict] = {}
    trades: list[Trade] = []
    for row in positions:
        scalp_id = row.get("scalp_id")
        if row.get("event") == "opened" and scalp_id:
            opened[scalp_id] = row
            continue
        if row.get("event") != "closed" or scalp_id not in opened:
            continue
        opening = opened.pop(scalp_id)
        opened_at = _et(opening["opened_ts"])
        closed_at = _et(row["ts"])
        meta = metadata.get(scalp_id, {})
        rvol = meta.get("rvol")
        trades.append(
            Trade(
                scalp_id=scalp_id,
                date=opened_at.date().isoformat(),
                opened_et=opened_at.strftime("%H:%M"),
                closed_et=closed_at.strftime("%H:%M"),
                underlying=opening["underlying"],
                direction=opening["direction"],
                rvol=float(rvol) if rvol is not None else None,
                qty=int(opening["qty"]),
                entry_price=float(opening["entry_price"]),
                exit_price=(float(row["exit_price"]) if row.get("exit_price") is not None else None),
                pnl_usd=(float(row["pnl_usd"]) if row.get("pnl_usd") is not None else None),
                reason=str(row.get("reason", "unknown")),
            )
        )
    return trades


def _stats(trades: list[Trade]) -> str:
    realized = [trade.pnl_usd for trade in trades if trade.pnl_usd is not None]
    if not realized:
        return "n=0"
    wins = sum(value > 0 for value in realized)
    return (
        f"n={len(realized)} pnl=${sum(realized):.0f} "
        f"win={wins}/{len(realized)} ({100 * wins / len(realized):.1f}%) "
        f"avg=${sum(realized) / len(realized):.1f}"
    )


def _filtered(
    trades: list[Trade], cutoff_et: int, min_rvol: float, max_per_day: int | None = None
) -> list[Trade]:
    selected = [
        trade
        for trade in trades
        if trade.entry_minutes < cutoff_et
        # Unknown entry metadata must not be treated as satisfying an RVOL
        # threshold; otherwise a partial/corrupt log can inflate a filtered
        # result while appearing to have strong confirmation.
        and trade.rvol is not None
        and trade.rvol >= min_rvol
    ]
    if max_per_day is None:
        return [trade for trade in selected if trade.pnl_usd is not None]
    counts: dict[str, int] = defaultdict(int)
    limited: list[Trade] = []
    # Cap by chronological entry order. Unknown-P/L entries still occupied a
    # live trade slot, even though their P/L is excluded from reported totals.
    for trade in sorted(selected, key=lambda item: (item.date, item.entry_minutes, item.scalp_id)):
        if counts[trade.date] >= max_per_day:
            continue
        counts[trade.date] += 1
        limited.append(trade)
    return limited


def _fmt_cutoff(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def report(trades: list[Trade]) -> None:
    realized = [trade for trade in trades if trade.pnl_usd is not None]
    unknown = [trade for trade in trades if trade.pnl_usd is None]
    print("OptionsAgent scalp history audit")
    print(f"trades={len(trades)} realized={len(realized)} unknown_pnl={len(unknown)}")
    print(f"overall: {_stats(trades)}")
    if unknown:
        print("unknown P/L: " + ", ".join(trade.scalp_id[:8] for trade in unknown))

    print("\nPer day")
    by_day: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        by_day[trade.date].append(trade)
    for date in sorted(by_day):
        print(f"{date}  {_stats(by_day[date])}")

    print("\nPer trade")
    for trade in trades:
        pnl = "?" if trade.pnl_usd is None else f"${trade.pnl_usd:.0f}"
        rvol = "?" if trade.rvol is None else f"{trade.rvol:.2f}"
        print(
            f"{trade.date} {trade.opened_et}-{trade.closed_et} {trade.underlying} "
            f"{trade.direction} rvol={rvol} qty={trade.qty} pnl={pnl} {trade.reason}"
        )

    print("\nConditional cutoff grid (realized fills only; in-sample)")
    grid: list[tuple[float, int, int, str]] = []
    for cutoff in range(10 * 60, 14 * 60 + 31, 30):
        for min_rvol in (1.5, 2.0, 2.5, 3.0, 4.0):
            selected = _filtered(trades, cutoff, min_rvol)
            pnl = sum(trade.pnl_usd or 0.0 for trade in selected)
            grid.append((pnl, len(selected), cutoff, f"rvol>={min_rvol:.1f}"))
    for pnl, count, cutoff, rvol in sorted(grid, reverse=True)[:8]:
        print(f"cutoff<{_fmt_cutoff(cutoff)} {rvol}: n={count} pnl=${pnl:.0f}")

    best = max(grid, key=lambda item: (item[0], -item[1]))
    print(
        "\nBest observed grid cell (not a deployment recommendation): "
        f"cutoff<{_fmt_cutoff(best[2])}, {best[3]}, n={best[1]}, pnl=${best[0]:.0f}"
    )
    before = _filtered(trades, 11 * 60 + 30, 1.5)
    after = [
        trade
        for trade in realized
        if trade.entry_minutes >= 11 * 60 + 30
    ]
    print(
        "Evidence for the implemented hard cutoff: "
        f"before={_stats(before)}; after={_stats(after)}"
    )
    capped = _filtered(trades, 11 * 60 + 30, 1.5, max_per_day=2)
    print(
        "Evidence for the implemented two-entry cap: "
        f"cutoff+cap={_stats(capped)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    report(load_trades(args.data_dir))


if __name__ == "__main__":
    main()
