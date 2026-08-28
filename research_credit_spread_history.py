"""Replay the archived multi-day credit-spread registry.

This is a conditional realized-fill replay: it describes structures that were
recorded, but it does not reconstruct quotes or fills for trades that did not
occur. The winner profile is intentionally in-sample and is implemented as a
hard rail only because the operator explicitly requested an overfit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from harness.risk_rails import credit_spread_overfit_decision

ROOT = Path(__file__).resolve().parent
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class CreditSpreadTrade:
    structure_id: str
    date: str
    opened_et: str
    closed_et: str | None
    underlying: str
    direction: str
    width: float
    entry_net: float
    contracts: int
    pnl_usd: float | None
    reason: str | None

    @property
    def profile_match(self) -> bool:
        return credit_spread_overfit_decision(
            underlying=self.underlying,
            direction=self.direction,
            width=self.width,
            net_credit=self.entry_net,
        )[0]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _et(ts: str) -> tuple[str, str]:
    local = datetime.fromisoformat(ts).astimezone(EASTERN)
    return local.date().isoformat(), local.strftime("%H:%M")


def _direction(legs: list[dict]) -> str:
    short = next(leg for leg in legs if leg.get("side") == "short")
    return "bullish" if short.get("right") == "put" else "bearish"


def load_trades(data_dir: Path = ROOT / "data") -> list[CreditSpreadTrade]:
    rows = _read_jsonl(data_dir / "structures.jsonl")
    opens = {}
    for row in rows:
        if row.get("event") == "opened" and row.get("strategy_type") == "credit_spread":
            # Preserve the first registry record if a crash/retry duplicated
            # an open event for the same structure ID.
            opens.setdefault(row["structure_id"], row)
    closes = {}
    for row in rows:
        if row.get("event") == "closed" and row.get("structure_id") in opens:
            closes.setdefault(row["structure_id"], row)
    trades = []
    for structure_id, row in opens.items():
        date, opened_et = _et(row["opened_ts"])
        close = closes.get(structure_id)
        closed_et = None
        if close and close.get("ts"):
            _, closed_et = _et(close["ts"])
        legs = row["legs"]
        width = abs(float(legs[0]["strike"]) - float(legs[1]["strike"]))
        trades.append(
            CreditSpreadTrade(
                structure_id=structure_id,
                date=date,
                opened_et=opened_et,
                closed_et=closed_et,
                underlying=row["underlying"],
                direction=_direction(legs),
                width=width,
                entry_net=float(row["entry_net"]),
                contracts=int(row["contracts"]),
                pnl_usd=None if close is None else close.get("pnl_usd"),
                reason=None if close is None else close.get("reason"),
            )
        )
    return sorted(trades, key=lambda trade: (trade.date, trade.opened_et, trade.structure_id))


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:,.0f}"


def main() -> None:
    trades = load_trades()
    realized = [trade for trade in trades if trade.pnl_usd not in (None, 0)]
    profile = [trade for trade in realized if trade.profile_match]
    days = sorted({trade.date for trade in trades})
    total = sum(float(trade.pnl_usd) for trade in realized)
    profile_total = sum(float(trade.pnl_usd) for trade in profile)

    print(f"credit-spread records: {len(trades)}")
    print(f"entry days: {len(days)} ({', '.join(days)})")
    print(f"realized non-zero: {len(realized)}, P/L: {_money(total)}")
    print(f"winner-profile replay: {len(profile)}, P/L: {_money(profile_total)}")
    print("date       ET     symbol direction width credit contracts P/L     profile reason")
    for trade in trades:
        print(
            f"{trade.date} {trade.opened_et} {trade.underlying:6} {trade.direction:8} "
            f"{trade.width:5.2f} {trade.entry_net:6.2f} {trade.contracts:9} "
            f"{_money(trade.pnl_usd):>7} {'yes' if trade.profile_match else 'no ':>7} "
            f"{trade.reason or 'open'}"
        )


if __name__ == "__main__":
    main()
