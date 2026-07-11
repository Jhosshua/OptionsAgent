"""Exit decision for an open 0DTE scalp — pure, priority-ordered, unit-testable.

The runner marks the option at the current BID (what we can sell for) and calls
`evaluate_scalp_exit` every minute. Priority (first trigger wins):

    EOD flatten  ->  thesis-aware hard stop  ->  profit target  ->  theta time-cut

EOD flatten is checked FIRST and enforced regardless of P&L: an ITM 0DTE left to
expiry auto-exercises into 100 shares (~$75k on SPY on a $5k account). The order
placement + fill confirmation live in the runner; this module only decides.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScalpExitRules:
    stop_loss_pct: float = 0.30       # premium down this fraction -> exit
    thesis_intact_stop_loss_pct: float = 0.60  # catastrophic stop while price structure still holds
    profit_target_pct: float = 0.50   # premium up this fraction -> exit
    theta_cut_minutes: int = 15       # not in our favor within N min -> exit


@dataclass(frozen=True)
class ScalpExitDecision:
    should_close: bool
    reason: str  # "eod_flatten" | "stop_loss" | "profit_target" | "theta_cut" | "hold"


def evaluate_scalp_exit(
    *,
    entry_price: float,
    current_bid: float,
    minutes_held: float,
    must_flatten: bool,
    thesis_intact: bool = False,
    rules: ScalpExitRules,
) -> ScalpExitDecision:
    """entry_price / current_bid are per-share option premiums. `must_flatten` is the
    EOD guard (from risk_rails.scalp_must_flatten). Returns the first trigger in
    priority order, else hold."""
    if must_flatten:
        return ScalpExitDecision(True, "eod_flatten")
    if entry_price <= 0:
        # Defensive: unknown entry -> flatten conservatively rather than hold blind.
        return ScalpExitDecision(True, "stop_loss")
    # A 0DTE premium can whip around even while the underlying breakout remains
    # valid (July 10 replay).  While structure holds, suppress the ordinary
    # premium stop/time cut but retain a wider catastrophic loss limit.
    effective_stop_pct = (
        rules.thesis_intact_stop_loss_pct if thesis_intact else rules.stop_loss_pct
    )
    stop_price = entry_price * (1.0 - effective_stop_pct)
    target_price = entry_price * (1.0 + rules.profit_target_pct)
    if current_bid <= stop_price:
        return ScalpExitDecision(True, "stop_loss")
    if current_bid >= target_price:
        return ScalpExitDecision(True, "profit_target")
    # theta time-cut: held long enough and NOT in our favor (bid still <= entry)
    if not thesis_intact and minutes_held >= rules.theta_cut_minutes and current_bid <= entry_price:
        return ScalpExitDecision(True, "theta_cut")
    return ScalpExitDecision(False, "hold")
