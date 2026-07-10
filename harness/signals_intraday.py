"""Intraday 1-minute signals for the 0DTE Opening-Range-Breakout scalper.

Pure functions over the bar dicts produced by
`alpaca_glue.PaperClient.stock_minute_bars` (each: {"ts_utc","et_date","et_time",
"o","h","l","c","v"}, oldest-first, timestamps already in America/New_York). No
network, no broker — unit-testable with synthetic bars. Adapted from the proven
DTA engine (harness/data/ohlcv.extract_opening_range + triggers ORB/RVOL logic),
kept minimal and self-contained per OptionsAgent's small-pure-module style.

The strategy (doc "Opening Drive Momentum Break", disciplined):
  - Mark the first N minutes' high/low (09:30-09:33 ET opening range).
  - On a 1-min candle CLOSE outside that range WITH a volume surge, signal a
    breakout in that direction (up -> buy calls, down -> buy puts).
Everything works in ET regular-hours (09:30-16:00); pre/post-market bars that SIP
returns are filtered out first (the fleet's known SIP-includes-extended-hours gotcha).
"""

from __future__ import annotations

from dataclasses import dataclass

SESSION_OPEN = "09:30"
SESSION_CLOSE = "16:00"


def regular_session_bars(bars: list[dict], et_date: str) -> list[dict]:
    """Bars on et_date within 09:30 <= et_time < 16:00 (regular hours only)."""
    return [
        b
        for b in bars
        if b.get("et_date") == et_date and SESSION_OPEN <= b.get("et_time", "") < SESSION_CLOSE
    ]


def _range_end_time(minutes: int) -> str:
    """The exclusive upper bound for the opening range, e.g. minutes=3 -> '09:33'."""
    total = 9 * 60 + 30 + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


@dataclass(frozen=True)
class OpeningRange:
    high: float
    low: float
    bars: int  # how many 1-min bars formed the range


def opening_range(bars: list[dict], et_date: str, *, minutes: int = 3) -> OpeningRange | None:
    """High/low of the first `minutes` regular-session bars (09:30 .. 09:30+minutes,
    exclusive). Returns None until at least `minutes` bars have closed (so the range
    is only 'set' once 09:30, 09:31, 09:32 are all in for minutes=3)."""
    end = _range_end_time(minutes)
    rng = [b for b in regular_session_bars(bars, et_date) if b["et_time"] < end]
    if len(rng) < minutes:
        return None
    return OpeningRange(
        high=max(b["h"] for b in rng),
        low=min(b["l"] for b in rng),
        bars=len(rng),
    )


@dataclass(frozen=True)
class Breakout:
    direction: str  # "up" | "down"
    bar_et_time: str
    bar_ts_utc: str
    close: float
    rvol: float


def _avg_prior_volume(session: list[dict], idx: int) -> float | None:
    """Average 1-min volume of regular-session bars strictly before index idx.
    None if fewer than 2 prior bars (can't establish a baseline -> fail closed)."""
    prior = [b["v"] for b in session[:idx] if b.get("v", 0) > 0]
    if len(prior) < 2:
        return None
    return sum(prior) / len(prior)


def breakout_check(
    bars: list[dict],
    et_date: str,
    *,
    range_high: float,
    range_low: float,
    rvol_min: float,
) -> Breakout | None:
    """Evaluate the LAST CLOSED regular-session bar for a confirmed breakout:
    close beyond the opening range AND a volume surge (bar volume >= rvol_min x the
    session's average 1-min volume so far). Returns None if no breakout, if the last
    bar is still inside the range, or if the volume baseline is too thin. The caller
    is responsible for once-per-bar idempotency (via the bar timestamp)."""
    session = regular_session_bars(bars, et_date)
    if not session:
        return None
    idx = len(session) - 1
    bar = session[idx]
    avg = _avg_prior_volume(session, idx)
    if avg is None or avg <= 0:
        return None
    rvol = bar["v"] / avg
    if rvol < rvol_min:
        return None  # no volume surge -> not a confirmed breakout (a trap)
    if bar["c"] > range_high:
        direction = "up"
    elif bar["c"] < range_low:
        direction = "down"
    else:
        return None
    return Breakout(
        direction=direction,
        bar_et_time=bar["et_time"],
        bar_ts_utc=bar["ts_utc"],
        close=bar["c"],
        rvol=round(rvol, 2),
    )


def session_vwap(bars: list[dict], et_date: str) -> float | None:
    """Session VWAP over regular-hours bars (typical price * volume / volume).
    For logging / the shared market-data feed, not a gate. None if no volume."""
    session = regular_session_bars(bars, et_date)
    num = 0.0
    den = 0.0
    for b in session:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        num += tp * b["v"]
        den += b["v"]
    return round(num / den, 4) if den > 0 else None
