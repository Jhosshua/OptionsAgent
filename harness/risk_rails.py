"""Hard risk rails — the DETERMINISTIC decision layer.

Same governing rule as DeterministicAgent: the LLM proposes, this code
disposes. Same proposal + same account/position state always yields the same
accept/veto/size. No LLM ever runs in here. All functions are PURE (no IO) so
they are trivially testable and replayable.

MEDIUM-RISK, HIGH-CONVICTION PROFILE (see ARCHITECTURE.md "Risk profile"):
fewer, more selective trades, each sized meaningfully once taken. A hard
conviction floor gates entry entirely (not just a smaller size below it), and
the portfolio-level caps stay tighter than a high-risk directional stock bot's
would, because options are already leveraged instruments.

These floors are never widened by a proposal, by config JSON, or by the model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os


@dataclass(frozen=True)
class Rails:
    """Hard caps for the medium-risk/high-conviction profile. Config may only
    tighten these via the env overrides below, never loosen them."""

    conviction_floor: float = 0.60        # below this: pass, no trade at all
    conviction_max: float = 0.85          # size scaling saturates at/above this
    min_size_frac: float = 0.30           # size fraction AT the conviction floor (not zero —
                                           # clearing the floor means "take a minimum position",
                                           # never a zero-size no-op trade)
    max_position_frac: float = 0.15       # per-position collateral/notional <= 15% of equity
    max_underlying_frac: float = 0.20     # all positions on one underlying <= 20% of equity
    max_gross_exposure_frac: float = 0.60 # total notional/collateral across ALL positions <= 60%
    max_margin_utilization: float = 0.60  # never use more than 60% of available options buying power
    max_concurrent_positions: int = 6
    dte_mandatory_close: int = 21         # every short-premium leg force-closes at this DTE
    expiration_day_freeze: bool = True    # no new position expiring same-day it's opened
    spread_width_max_pct_of_mid: float = 0.10  # placeholder — untuned, see ARCHITECTURE.md caveat

    # Covered straddle gets a tighter cap than the portfolio default (least-
    # standardized strategy, "surprise capital call" risk on the short put).
    covered_straddle_max_position_frac: float = 0.10


def active_rails() -> Rails:
    """Resolve the rail set. OA_MAX_POSITION_FRAC / OA_MAX_GROSS_EXPOSURE_FRAC
    env vars may only TIGHTEN the corresponding floor, matching the sibling
    bots' convention — never loosen it."""
    base = Rails()
    tighten_map = {
        "OA_MAX_POSITION_FRAC": "max_position_frac",
        "OA_MAX_GROSS_EXPOSURE_FRAC": "max_gross_exposure_frac",
        "OA_MAX_MARGIN_UTILIZATION": "max_margin_utilization",
    }
    updates = {}
    for env_key, field in tighten_map.items():
        raw = os.environ.get(env_key)
        if not raw:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        current = getattr(base, field)
        if 0 < val < current:
            updates[field] = val
    return replace(base, **updates) if updates else base


@dataclass(frozen=True)
class Proposal:
    """What the LLM (right brain) may propose. No strike/delta/DTE fields —
    contract selection is deterministic rail territory (harness/contracts.py)."""

    underlying: str
    strategy_type: str  # csp | covered_call | credit_spread | debit_spread |
                         # long_call | long_put | long_straddle | covered_straddle
    direction: str       # bullish | bearish | neutral | vol_long | vol_short
    conviction: float    # 0-1
    thesis: str


@dataclass(frozen=True)
class AccountState:
    """Alpaca reports only the AVAILABLE options buying power, not a
    used/total pair, so margin utilization is computed against equity:
    utilization = 1 - available/equity (clamped to [0, 1]). A margin account
    whose available BP exceeds equity clamps to 0 (fine — the gross-exposure
    cap is the binding rail there); a missing/zero BP reads as fully
    utilized, which fails SAFE (vetoes everything)."""

    equity_usd: float
    available_options_buying_power_usd: float
    open_positions_count: int
    underlying_exposure_usd: dict  # {symbol: collateral already deployed}
    gross_exposure_usd: float

    def margin_utilization(self) -> float:
        if self.equity_usd <= 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - self.available_options_buying_power_usd / self.equity_usd))


@dataclass(frozen=True)
class RailDecision:
    approved: bool
    reason: str
    size_frac: float = 0.0        # fraction of max_position_frac to actually use
    position_cap_usd: float = 0.0  # dollar ceiling for this specific position


def conviction_to_size_frac(conviction: float, rails: Rails) -> float:
    """Linear scale: conviction_floor -> min_size_frac (clearing the floor
    means a minimum position, never zero), conviction_max+ -> 1.0. Below the
    floor this is never reached because evaluate_proposal() vetoes first."""
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

    utilization = account.margin_utilization()
    if utilization >= rails.max_margin_utilization:
        return RailDecision(
            approved=False,
            reason=f"margin utilization {utilization:.0%} already at/above "
            f"{rails.max_margin_utilization:.0%} buffer cap",
        )

    if account.gross_exposure_usd >= rails.max_gross_exposure_frac * account.equity_usd:
        return RailDecision(
            approved=False,
            reason=f"gross exposure already at/above {rails.max_gross_exposure_frac:.0%} of equity",
        )

    existing_underlying_usd = account.underlying_exposure_usd.get(proposal.underlying, 0.0)
    underlying_cap_usd = rails.max_underlying_frac * account.equity_usd
    if existing_underlying_usd >= underlying_cap_usd:
        return RailDecision(
            approved=False,
            reason=f"{proposal.underlying} already at/above per-underlying cap "
            f"({rails.max_underlying_frac:.0%} of equity)",
        )

    position_frac_cap = (
        rails.covered_straddle_max_position_frac
        if proposal.strategy_type == "covered_straddle"
        else rails.max_position_frac
    )
    size_frac = conviction_to_size_frac(proposal.conviction, rails)
    position_cap_usd = position_frac_cap * account.equity_usd * size_frac

    # Don't let a sized-down position exceed remaining headroom on this
    # underlying or the remaining gross-exposure budget.
    underlying_headroom = underlying_cap_usd - existing_underlying_usd
    gross_headroom = rails.max_gross_exposure_frac * account.equity_usd - account.gross_exposure_usd
    position_cap_usd = max(0.0, min(position_cap_usd, underlying_headroom, gross_headroom))

    if position_cap_usd <= 0:
        return RailDecision(approved=False, reason="no headroom left after cap intersection")

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
    proposals within one cycle are each evaluated against up-to-date
    exposure — evaluating all of them against the beginning-of-cycle
    snapshot lets a single cycle jointly breach every cap (e.g. six 15%
    positions = 90% gross against a 60% cap)."""
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
