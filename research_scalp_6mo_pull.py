"""Pull ~6 months of 1-minute bars for SPY + QQQ into data/research_scalp_6mo/.

Uses the SIP-entitled read-only data key (OA_DATA_*), NOT the trading key.
One parquet-style CSV per symbol: ts_utc,et_date,et_time,o,h,l,c,v.
Idempotent: skips symbols already pulled with full coverage.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

ET = ZoneInfo("America/New_York")
OUT = Path(__file__).parent / "data" / "research_scalp_6mo"
OUT.mkdir(parents=True, exist_ok=True)
START = datetime(2026, 3, 1, tzinfo=timezone.utc)   # ~6 months back
END = datetime(2026, 8, 28, tzinfo=timezone.utc)


def rows_from(resp, sym):
    out = []
    bars = resp[sym] if hasattr(resp, "__getitem__") else resp
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        et = ts.astimezone(ET)
        out.append((
            ts.isoformat(), et.strftime("%Y-%m-%d"), et.strftime("%H:%M"),
            float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume),
        ))
    return out


def pull(sym: str) -> None:
    dest = OUT / f"{sym}.csv"
    if dest.exists() and os.path.getsize(dest) > 1_000_000:
        print(f"{sym}: already pulled, skipping")
        return
    env = dict(os.environ)
    # fall back to .env if the shell did not export the data key
    if not env.get("OA_DATA_KEY_ID"):
        for line in open(Path(__file__).parent / ".env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    client = StockHistoricalDataClient(env["OA_DATA_KEY_ID"], env["OA_DATA_SECRET_KEY"])
    all_rows: list[tuple] = []
    cursor_start = START
    while cursor_start < END:
        req = StockBarsRequest(
            symbol_or_symbols=sym, timeframe=TimeFrame.Minute,
            start=cursor_start, end=END, feed=DataFeed.SIP, limit=10000,
        )
        try:
            resp = client.get_stock_bars(req)
        except Exception as e:
            print(f"{sym}: error {e}; retry in 5s", flush=True)
            time.sleep(5)
            continue
        rows = rows_from(resp, sym)
        if not rows:
            break
        all_rows.extend(rows)
        newest = datetime.fromisoformat(rows[-1][0])
        print(f"{sym}: {len(all_rows)} bars, through {rows[-1][1]} {rows[-1][2]}", flush=True)
        if newest >= END - timedelta(minutes=1) or len(rows) < 10000:
            break
        cursor_start = newest + timedelta(minutes=1)
        time.sleep(0.4)
    # dedupe + sort
    seen, uniq = set(), []
    for r in all_rows:
        if r[0] not in seen:
            seen.add(r[0])
            uniq.append(r)
    uniq.sort(key=lambda r: r[0])
    with open(dest, "w") as f:
        f.write("ts_utc,et_date,et_time,o,h,l,c,v\n")
        for r in uniq:
            f.write(",".join(str(x) for x in r) + "\n")
    days = len({r[1] for r in uniq})
    print(f"{sym}: wrote {len(uniq)} bars over {days} days -> {dest}")


if __name__ == "__main__":
    for s in ("SPY", "QQQ"):
        pull(s)
