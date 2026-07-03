"""The LLM-free rails sweep. Exits never need the model — this is pure
deterministic monitoring, checked on its own schedule (every 15-30 min during
market hours), separate from the once-daily entry cycle. Mirrors the "boring
and predictable execution layer" posture from DeterministicAgent.

All functions are pure (no IO) so they're trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenPosition:
    """One open short-premium wheel leg (CSP or covered call short side)."""

    underlying: str
    strategy_type: str  # "csp" | "covered_call"
    strike: float
    dte: int
    entry_credit: float          # premium received when opened, per share
    cost_to_close: float         # current mark to buy-to-close, per share
    same_strike_opposite_price: float | None = None  # for covered_call: the
        # same-strike PUT's price, used for the dividend-assignment check
    dividend_amount: float | None = None  # upcoming dividend per share, if any
    is_ex_dividend_within_dte: bool = False


@dataclass(frozen=True)
class ExitDecision:
    should_close: bool
    reason: str


def check_dte_close(position: OpenPosition, *, dte_close: int) -> ExitDecision | None:
    """Every short-premium position force-closes at this DTE regardless of
    P&L. Best-supported numeric rule across all three research passes."""
    if position.dte <= dte_close:
        return ExitDecision(True, f"DTE {position.dte} <= mandatory close threshold {dte_close}")
    return None


def check_profit_target(position: OpenPosition, *, profit_target_pct: float) -> ExitDecision | None:
    """Close once cost-to-close has dropped to (1 - profit_target_pct) of the
    original credit received — e.g. 50% target means close once it costs half
    of what was collected to buy it back."""
    if position.entry_credit <= 0:
        return None
    threshold = position.entry_credit * (1 - profit_target_pct)
    if position.cost_to_close <= threshold:
        captured_pct = 1 - (position.cost_to_close / position.entry_credit)
        return ExitDecision(
            True, f"profit target reached ({captured_pct:.0%} of credit captured)"
        )
    return None


def check_dividend_assignment_risk(position: OpenPosition) -> ExitDecision | None:
    """Covered-call-specific: early assignment on a short ITM call is likely
    once the dividend exceeds the same-strike put's price (holder can
    exercise, buy the offsetting put, and lock in the dividend). If an
    ex-dividend date falls within the position's remaining DTE, force close
    or roll pre-emptively rather than risk assignment."""
    if position.strategy_type != "covered_call":
        return None
    if not position.is_ex_dividend_within_dte:
        return None
    if position.dividend_amount is None or position.same_strike_opposite_price is None:
        return None
    if position.dividend_amount > position.same_strike_opposite_price:
        return ExitDecision(
            True,
            f"dividend ${position.dividend_amount:.2f} exceeds same-strike put "
            f"${position.same_strike_opposite_price:.2f} ahead of ex-dividend date — "
            f"early assignment risk, closing/rolling pre-emptively",
        )
    return None


def evaluate_exit(position: OpenPosition, *, dte_close: int, profit_target_pct: float) -> ExitDecision:
    """Runs all exit checks in priority order — dividend-assignment risk
    first (time-sensitive, broker won't warn you), then DTE, then profit
    target. First trigger wins; if none fire, hold."""
    for check in (
        lambda p: check_dividend_assignment_risk(p),
        lambda p: check_dte_close(p, dte_close=dte_close),
        lambda p: check_profit_target(p, profit_target_pct=profit_target_pct),
    ):
        decision = check(position)
        if decision is not None:
            return decision
    return ExitDecision(False, "no exit condition met")
