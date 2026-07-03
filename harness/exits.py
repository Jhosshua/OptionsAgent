"""The LLM-free rails sweep. Exits never need the model — this is pure
deterministic monitoring, checked on its own schedule (every 15-30 min during
market hours), separate from the once-daily entry cycle. Mirrors the "boring
and predictable execution layer" posture from DeterministicAgent.

Two structure families, different exit semantics:
- SHORT PREMIUM (csp, covered_call, credit_spread, covered_straddle):
  entry_credit received, cost_to_close to buy back. Exits: profit target
  (% of credit captured), stop loss (% of credit LOST beyond what was
  received), 21 DTE mandatory close, dividend-assignment check on any
  structure containing a short call.
- LONG (long_call, long_put, debit_spread, long_straddle): entry_debit
  paid, current_value now. Exits: profit target (% gain on debit), stop
  loss (% of debit lost), 21 DTE close.

All functions are pure (no IO) so they're trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass

SHORT_PREMIUM_TYPES = ("csp", "covered_call", "credit_spread", "covered_straddle")
LONG_TYPES = ("long_call", "long_put", "debit_spread", "long_straddle")
HAS_SHORT_CALL = ("covered_call", "covered_straddle")


@dataclass(frozen=True)
class OpenPosition:
    """One open structure (single- or multi-leg, netted). For multi-leg
    structures the credit/debit/value fields are the NET across legs."""

    underlying: str
    strategy_type: str
    strike: float           # short strike (short premium) / long strike (long)
    dte: int
    entry_credit: float = 0.0    # short premium: net credit received, per share
    cost_to_close: float = 0.0   # short premium: current net buy-back cost, per share
    entry_debit: float = 0.0     # long structures: net debit paid, per share
    current_value: float = 0.0   # long structures: current net liquidation value, per share
    same_strike_opposite_price: float | None = None  # for short calls: the
        # same-strike PUT's price, used for the dividend-assignment check
    dividend_amount: float | None = None  # upcoming dividend per share, if any
    is_ex_dividend_within_dte: bool = False


@dataclass(frozen=True)
class ExitRules:
    """Per-strategy exit thresholds, mapped from config by the caller."""

    dte_close: int
    profit_target_pct: float
    stop_loss_pct: float | None = None  # None = no stop (wheel CSP convention)


@dataclass(frozen=True)
class ExitDecision:
    should_close: bool
    reason: str


def check_dte_close(position: OpenPosition, *, dte_close: int) -> ExitDecision | None:
    """Every position force-closes at this DTE regardless of P&L. Best-
    supported numeric rule across all three research passes."""
    if position.dte <= dte_close:
        return ExitDecision(True, f"DTE {position.dte} <= mandatory close threshold {dte_close}")
    return None


def check_short_premium_profit(position: OpenPosition, *, profit_target_pct: float) -> ExitDecision | None:
    """Close once cost-to-close has dropped to (1 - target) of the credit."""
    if position.entry_credit <= 0:
        return None
    threshold = position.entry_credit * (1 - profit_target_pct)
    if position.cost_to_close <= threshold:
        captured = 1 - (position.cost_to_close / position.entry_credit)
        return ExitDecision(True, f"profit target reached ({captured:.0%} of credit captured)")
    return None


def check_short_premium_stop(position: OpenPosition, *, stop_loss_pct: float) -> ExitDecision | None:
    """Close once the buy-back cost exceeds credit x (1 + stop): the position
    has lost stop_loss_pct of the credit received beyond breakeven."""
    if position.entry_credit <= 0:
        return None
    if position.cost_to_close >= position.entry_credit * (1 + stop_loss_pct):
        loss = position.cost_to_close - position.entry_credit
        return ExitDecision(
            True,
            f"stop loss: cost to close ${position.cost_to_close:.2f} is "
            f"${loss:.2f} beyond the ${position.entry_credit:.2f} credit received",
        )
    return None


def check_long_profit(position: OpenPosition, *, profit_target_pct: float) -> ExitDecision | None:
    if position.entry_debit <= 0:
        return None
    if position.current_value >= position.entry_debit * (1 + profit_target_pct):
        gain = (position.current_value / position.entry_debit) - 1
        return ExitDecision(True, f"profit target reached (+{gain:.0%} on debit paid)")
    return None


def check_long_stop(position: OpenPosition, *, stop_loss_pct: float) -> ExitDecision | None:
    if position.entry_debit <= 0:
        return None
    if position.current_value <= position.entry_debit * (1 - stop_loss_pct):
        loss = 1 - (position.current_value / position.entry_debit)
        return ExitDecision(True, f"stop loss: position down {loss:.0%} of debit paid")
    return None


def check_dividend_assignment_risk(position: OpenPosition) -> ExitDecision | None:
    """Any structure with a SHORT CALL: early assignment is likely once the
    dividend exceeds the same-strike put's price (holder exercises, buys the
    offsetting put, locks in the dividend). If an ex-dividend date falls
    within the position's remaining DTE, close/roll pre-emptively."""
    if position.strategy_type not in HAS_SHORT_CALL:
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


def evaluate_exit(position: OpenPosition, rules: ExitRules) -> ExitDecision:
    """Runs the checks for the position's structure family in priority
    order — dividend-assignment first (time-sensitive, the broker won't warn
    you), then stop loss, then DTE, then profit target. First trigger wins."""
    if position.strategy_type in SHORT_PREMIUM_TYPES:
        checks = [
            check_dividend_assignment_risk(position),
            (
                check_short_premium_stop(position, stop_loss_pct=rules.stop_loss_pct)
                if rules.stop_loss_pct is not None
                else None
            ),
            check_dte_close(position, dte_close=rules.dte_close),
            check_short_premium_profit(position, profit_target_pct=rules.profit_target_pct),
        ]
    elif position.strategy_type in LONG_TYPES:
        checks = [
            (
                check_long_stop(position, stop_loss_pct=rules.stop_loss_pct)
                if rules.stop_loss_pct is not None
                else None
            ),
            check_dte_close(position, dte_close=rules.dte_close),
            check_long_profit(position, profit_target_pct=rules.profit_target_pct),
        ]
    else:
        return ExitDecision(False, f"unknown strategy_type {position.strategy_type!r} — holding, flag this")

    for decision in checks:
        if decision is not None:
            return decision
    return ExitDecision(False, "no exit condition met")
