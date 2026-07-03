"""Hard risk rails — the DETERMINISTIC decision layer.

Same governing rule as DeterministicAgent: the LLM proposes, this code
disposes. Same proposal + same account state always yields the same
accept/veto/size. No LLM ever runs in here. All functions are PURE (no IO).

FULL-DEPLOY / HIGH-CONVICTION PROFILE (operator 2026-07-03, supersedes the
original medium-risk percentage caps): position size is a CONVICTION-SCALED
FRACTION OF AVAILABLE OPTIONS BUYING POWER, with no per-position, per-
underlying, or gross-exposure percentage caps. "Use all the cash, not
necessarily all at once": a floor-conviction idea takes min_size_frac of
what's available, a max-conviction idea may take all of it. Alpaca's own
buying-power rejection is the hard broker-side backstop.

What still gates every trade (these are NOT sizing caps and never left):
  - the 0.60 conviction floor (below it: no trade at all)
  - max 6 concurrent positions
  - rollout-phase strategy allowlist
  - available buying power must actually cover the position
The env override OA_MAX_POSITION_USD may only TIGHTEN (an absolute dollar
ceiling per position, same pattern as DA's DA_MAX_ORDER_USD kill knob).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os


@dataclass(frozen=True)
class Rails:
    conviction_floor: float = 0.60   # below this: pass, no trade at all
    conviction_max: float = 0.85     # size scaling saturates at/above this
    min_size_frac: float = 0.30      # fraction of available BP AT the floor
    max_concurrent_positions: int = 6
    dte_mandatory_close: int = 21    # short-premium force-close backstop
    expiration_day_freeze: bool = True
    spread_width_max_pct_of_mid: float = 0.10  # placeholder — untuned
    max_position_abs_usd: float | None = None  # optional absolute ceiling (env, tighten-only)


def active_rails() -> Rails:
    """OA_MAX_POSITION_USD (if set, > 0) becomes an absolute per-position
    dollar ceiling — a tighten-only operator kill knob."""
    base = Rails()
    raw = os.environ.get("OA_MAX_POSITION_USD")
    if raw:
        try:
            cap = float(raw)
            if cap > 0:
                base = replace(base, max_position_abs_usd=cap)
        except ValueError:
            pass
    return base


@dataclass(frozen=True)
class Proposal:
    """What the LLM (right brain) may propose. No strike/delta/DTE fields —
    contract selection is deterministic rail territory (harness/contracts.py)."""

    underlying: str
    strategy_type: str
    direction: str
    conviction: float
    thesis: str


@dataclass(frozen=True)
class AccountState:
    """available_options_buying_power_usd comes straight from the broker and
    is the sizing base. equity/exposure fields are kept for logging and the
    reconcile/report paths, not for percentage-cap vetoes (removed by the
    2026-07-03 full-deploy decision)."""

    equity_usd: float
    available_options_buying_power_usd: float
    open_positions_count: int
    underlying_exposure_usd: dict
    gross_exposure_usd: float


@dataclass(frozen=True)
class RailDecision:
    approved: bool
    reason: str
    size_frac: float = 0.0
    position_cap_usd: float = 0.0  # this position's budget (fraction of available BP)


def conviction_to_size_frac(conviction: float, rails: Rails) -> float:
    """Linear scale: conviction_floor -> min_size_frac of available BP,
    conviction_max+ -> 1.0 (may take ALL remaining buying power — that is
    the operator-chosen policy, not an accident)."""
    if conviction >= rails.conviction_max:
        return 1.0
    span = rails.conviction_max - rails.conviction_floor
    if span <= 0:
        return 1.0
    frac = rails.min_size_frac + (1.0 - rails.min_size_frac) * (
        (conviction - rails.conviction_floor) / span
    )
    return max(rails.min_size_frac, min(1.0, frac))


def evaluate_proposal(
    proposal: Proposal,
    account: AccountState,
    *,
    allowed_strategies: list[str],
    rails: Rails | None = None,
) -> RailDecision:
    """The single funnel every proposal passes through before contract
    selection or execution. Returns approved=False with a reason on any veto."""
    rails = rails or active_rails()

    if proposal.strategy_type not in allowed_strategies:
        return RailDecision(
            approved=False,
            reason=f"strategy_type {proposal.strategy_type!r} not in current rollout "
            f"phase ({allowed_strategies})",
        )

    if proposal.conviction < rails.conviction_floor:
        return RailDecision(
            approved=False,
            reason=f"conviction {proposal.conviction:.2f} below floor "
            f"{rails.conviction_floor:.2f} — no trade",
        )

    if account.open_positions_count >= rails.max_concurrent_positions:
        return RailDecision(
            approved=False,
            reason=f"already at max_concurrent_positions ({rails.max_concurrent_positions})",
        )

    if account.available_options_buying_power_usd <= 0:
        return RailDecision(approved=False, reason="no options buying power available")

    size_frac = conviction_to_size_frac(proposal.conviction, rails)
    position_cap_usd = account.available_options_buying_power_usd * size_frac
    if rails.max_position_abs_usd is not None:
        position_cap_usd = min(position_cap_usd, rails.max_position_abs_usd)

    if position_cap_usd <= 0:
        return RailDecision(approved=False, reason="position budget computed to zero")

    return RailDecision(
        approved=True,
        reason="approved",
        size_frac=size_frac,
        position_cap_usd=position_cap_usd,
    )


def apply_opened_position(
    account: AccountState, *, underlying: str, collateral_usd: float
) -> AccountState:
    """Returns the account state AFTER a position opens, so multiple
    proposals within one cycle are each sized against the REMAINING buying
    power, not the beginning-of-cycle snapshot. This is what makes
    "use all the cash, not necessarily all at once" true across a cycle:
    each fill shrinks the base the next proposal is sized from."""
    exposure = dict(account.underlying_exposure_usd)
    exposure[underlying] = exposure.get(underlying, 0.0) + collateral_usd
    return replace(
        account,
        open_positions_count=account.open_positions_count + 1,
        underlying_exposure_usd=exposure,
        gross_exposure_usd=account.gross_exposure_usd + collateral_usd,
        available_options_buying_power_usd=max(
            0.0, account.available_options_buying_power_usd - collateral_usd
        ),
    )
