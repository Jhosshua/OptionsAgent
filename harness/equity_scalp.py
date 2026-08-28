"""Pure signal + exit logic for the equity intraday scalper (rules mined
2026-08-28, see harness/risk_rails.py EquityScalpRails docstring). No IO, no
broker: unit-testable on synthetic bars, mirrors signals_intraday.py style.

Signals are evaluated on the LAST CLOSED bar of the session slice, exactly like
the 0DTE scalper evaluates its breakouts, and fire at most once per rule per
symbol per day (the runner enforces that via day state).
"""
from __future__ import annotations

from dataclasses import dataclass

SESSION_OPEN = "09:30"
SESSION_CLOSE = "16:00"


def session_bars(bars: list[dict], et_date: str) -> list[dict]:
    return [b for b in bars
            if b.get("et_date") == et_date and SESSION_OPEN <= b.get("et_time", "") < SESSION_CLOSE]


def per_bar_vwap(session: list[dict]) -> list[float]:
    """Causal running session VWAP (typical price x volume)."""
    num = den = 0.0
    out = []
    for b in session:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        num += tp * b["v"]
        den += b["v"]
        out.append(num / den if den > 0 else b["c"])
    return out


@dataclass(frozen=True)
class Signal:
    rule: str        # "morning_fade" | "gap_follow"
    side: str        # "long" | "short"
    bar_et_time: str


def morning_fade_signal(session: list[dict], *, at_or_after: str = "10:15") -> Signal | None:
    """Rule A. On the first closed bar at/after at_or_after: if close is above
    BOTH session VWAP and the 15-minute opening range high -> SHORT (fade the
    extension). Below both -> LONG. Otherwise no trade."""
    if len(session) < 46:  # need the 09:30-09:45 range plus bars through 10:15
        return None
    vwap = per_bar_vwap(session)
    hi15 = max(b["h"] for b in session[:15])
    lo15 = min(b["l"] for b in session[:15])
    for i, b in enumerate(session):
        if b["et_time"] >= at_or_after:
            c = b["c"]
            if c > vwap[i] and c > hi15:
                return Signal("morning_fade", "short", b["et_time"])
            if c < vwap[i] and c < lo15:
                return Signal("morning_fade", "long", b["et_time"])
            return None  # first eligible bar decides: in the middle = no trade
    return None


def gap_follow_signal(session: list[dict], *, prev_close: float, open_px: float,
                      gap_pct_min: float = 0.8, at_or_after: str = "13:00") -> Signal | None:
    """Rule C. QQQ only (enforced by the runner). When the day gapped more than
    gap_pct_min at the open, on the first closed bar at/after at_or_after hold
    WITH the gap direction. No gap or gap too small -> None."""
    if prev_close <= 0:
        return None
    gap = (open_px / prev_close - 1) * 100.0
    if abs(gap) <= gap_pct_min:
        return None
    for b in session:
        if b["et_time"] >= at_or_after:
            return Signal("gap_follow", "long" if gap > 0 else "short", b["et_time"])
    return None


@dataclass(frozen=True)
class ExitDecision:
    should_close: bool
    reason: str  # "stop_loss" | "time_exit" | "eod_flatten"


def evaluate_equity_exit(*, side: str, entry_price: float, last_price: float,
                         entry_bar_index: int, last_bar_index: int, now_et_hhmm: str,
                         rails, bar_low: float | None = None,
                         bar_high: float | None = None) -> ExitDecision:
    """Priority: EOD flatten first (always), then stop, then time exit.

    The stop triggers on INTRABAR adverse extremes (low for a long, high for a
    short) when provided, matching the research replay — a bar that spikes
    through the stop and closes back inside still stops out."""
    if now_et_hhmm >= rails.eod_flatten_et:
        return ExitDecision(True, "eod_flatten")
    if entry_price > 0 and last_price > 0:
        adverse = (bar_low if side == "long" else bar_high) if \
            (bar_low is not None and bar_high is not None) else last_price
        if adverse > 0:
            move = (adverse / entry_price - 1) * (-1.0 if side == "short" else 1.0)
            if move <= -rails.stop_loss_pct:
                return ExitDecision(True, "stop_loss")
    if last_bar_index - entry_bar_index >= rails.time_exit_minutes:
        return ExitDecision(True, "time_exit")
    return ExitDecision(False, "")


def orphan_equity_positions(broker_positions: list[dict], state: dict,
                            *, symbols=("SPY", "QQQ")) -> list[dict]:
    """Broker equity positions in our symbols that the day state does NOT track.
    A crash between the entry fill and the state save would otherwise leave a
    live position unmanaged (no stop, no 15:50 flatten). The runner adopts these
    conservatively; anything unexpected still gets the EOD flatten."""
    tracked = {sym.upper() for sym, blk in state.get("symbols", {}).items()
               if isinstance(blk, dict) and blk.get("qty")}
    out = []
    for p in broker_positions or []:
        sym = str(p.get("symbol", "")).upper()
        ac = str(p.get("asset_class", "")).lower()
        if ac and ac != "us_equity":
            continue
        if sym in symbols and sym not in tracked:
            out.append({"symbol": sym, "qty": float(p.get("qty") or 0.0),
                        "side": "short" if float(p.get("qty") or 0) < 0 else "long"})
    return out
