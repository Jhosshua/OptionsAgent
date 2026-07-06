"""Market-context builder for the LLM proposer.

run_cycle historically sent the proposer an empty context ({}) for every
ticker, so the model had nothing to reason on and returned zero proposals every
single cycle (root cause of the "bot did nothing" investigation 2026-07-06).
This fills that gap with the Alpaca stock data the bot already pays for — no new
dependency, stack stays locked.

Per ticker it computes: latest price, 1/5/20-day % change, 20-day high/low and
where price sits in that range, and recent-vs-20-day-average volume. Everything
is derived from daily closes, so it's DATA the proposer reasons on, never an
instruction (the proposer's system prompt already treats context as data only).

FAIL-OPEN per ticker: a name with too-thin or missing data gets
{"data": "unavailable"} instead of crashing the cycle, and the rest of the
watchlist still builds. A broker-wide error degrades every ticker to
unavailable rather than raising — a blind cycle proposes nothing, it never
guesses.
"""

from __future__ import annotations

from typing import Any


def _pct(now: float, then: float) -> float | None:
    if not then or now is None:
        return None
    return round((now - then) / then * 100, 2)


def context_from_bars(bars: list[dict[str, float]]) -> dict[str, Any]:
    """Build one ticker's context from its daily bars (oldest-first,
    [{"c": close, "v": volume}, ...]). Needs at least 2 closes to say
    anything; below that it's {"data": "unavailable"}."""
    closes = [b["c"] for b in bars if b.get("c")]
    vols = [b.get("v", 0.0) for b in bars]
    if len(closes) < 2:
        return {"data": "unavailable"}

    last = closes[-1]
    ctx: dict[str, Any] = {
        "price": round(last, 2),
        "change_1d_pct": _pct(last, closes[-2]),
    }
    if len(closes) >= 6:
        ctx["change_5d_pct"] = _pct(last, closes[-6])
    if len(closes) >= 21:
        ctx["change_20d_pct"] = _pct(last, closes[-21])

    window = closes[-20:]
    hi, lo = max(window), min(window)
    ctx["high_20d"] = round(hi, 2)
    ctx["low_20d"] = round(lo, 2)
    if hi > lo:
        ctx["pct_of_20d_range"] = round((last - lo) / (hi - lo) * 100, 1)

    vol_window = vols[-20:]
    if len(vol_window) >= 2 and sum(vol_window) > 0:
        avg_v = sum(vol_window) / len(vol_window)
        if avg_v > 0:
            ctx["volume_vs_20d_avg"] = round(vols[-1] / avg_v, 2)
    return ctx


def has_data(ctx: dict[str, Any]) -> bool:
    """True when the context carries a real price (i.e. not the
    unavailable marker) — used to log data coverage per cycle."""
    return "price" in ctx


def build_context(client, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch daily bars and build per-symbol context. Fail-open: any broker
    error yields {"data": "unavailable"} for every symbol rather than
    raising, so a data outage means "propose nothing", never a crashed
    cycle."""
    try:
        bars_by_symbol = client.stock_daily_bars(symbols)
    except Exception:
        bars_by_symbol = {}
    return {sym: context_from_bars(bars_by_symbol.get(sym, [])) for sym in symbols}
