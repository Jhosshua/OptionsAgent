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


# ---------------------------------------------------------------------------
# 0DTE ORB scalp rails — a SEPARATE family from the seller's rails above.
# They never touch evaluate_proposal / conviction sizing. Same discipline: hard
# values live here in code, env vars may only TIGHTEN (lower a cap, never raise).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalpRails:
    per_trade_usd_cap: float = 250.0     # hard absolute budget per scalp
    # Conditional replay of archived fills: cutoff<11:30 plus two entries/day
    # retained 23 known trades and improved in-sample P/L to +$345. This remains
    # a hypothesis and must be held unchanged for the next sample.
    max_trades_per_day: int = 2
    daily_loss_stop_usd: float = 0.0     # 0 = DISABLED (operator 2026-07-10, paper account, max
                                         # learning: the two-trade cap is now a research gate).
                                         # Worst-case daily loss is then bounded only by
                                         # max_trades_per_day * per_trade_usd_cap ($500). A positive
                                         # OA_SCALP_DAILY_LOSS_USD re-enables the halt at that value.
    max_concurrent_scalps: int = 1       # one position at a time
    # Historical replay (2026-07-10 through 2026-07-31) found 12/12 realized
    # entries after 11:30 ET were losers. This is deliberately a hard rail: the
    # config copy is documentation only, and an operator can still tighten it
    # in code or by a future explicit policy change.
    entry_cutoff_et: str = "11:30"       # no NEW entries at/after this ET time
    eod_flatten_et: str = "15:50"        # MANDATORY force-close by this ET time


def _tighten_float(base: float, raw: str | None, *, lower_is_tighter: bool = True) -> float:
    """Apply an env override only if it TIGHTENS the base (lower cap). Ignores
    junk/loosening values."""
    if not raw:
        return base
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return base
    if val <= 0:
        return base
    if lower_is_tighter:
        return min(base, val)
    return max(base, val)


def active_scalp_rails() -> ScalpRails:
    """ScalpRails with env overrides that may only TIGHTEN:
    OA_SCALP_PER_TRADE_USD, OA_SCALP_MAX_TRADES, OA_SCALP_DAILY_LOSS_USD."""
    base = ScalpRails()
    per_trade = _tighten_float(base.per_trade_usd_cap, os.environ.get("OA_SCALP_PER_TRADE_USD"))
    # Daily-loss halt is DISABLED by default (base 0.0). A positive env value RE-ENABLES it (a
    # tightening from "no halt at all") — this keeps the escape hatch reversible via Railway env.
    loss = base.daily_loss_stop_usd
    raw_loss = os.environ.get("OA_SCALP_DAILY_LOSS_USD")
    if raw_loss:
        try:
            v = float(raw_loss)
            if v > 0:
                loss = v
        except (TypeError, ValueError):
            pass
    max_trades = base.max_trades_per_day
    raw_mt = os.environ.get("OA_SCALP_MAX_TRADES")
    if raw_mt:
        try:
            mt = int(float(raw_mt))
            if mt > 0:
                max_trades = min(max_trades, mt)
        except (TypeError, ValueError):
            pass
    return replace(
        base,
        per_trade_usd_cap=per_trade,
        daily_loss_stop_usd=loss,
        max_trades_per_day=max_trades,
    )


def scalp_per_trade_budget_ok(intended_usd: float, rails: ScalpRails) -> tuple[bool, str]:
    if intended_usd <= 0:
        return False, "intended budget is non-positive"
    if intended_usd > rails.per_trade_usd_cap:
        return False, f"intended ${intended_usd:.0f} over per-trade cap ${rails.per_trade_usd_cap:.0f}"
    return True, "ok"


def scalp_trade_count_ok(trades_today: int, rails: ScalpRails) -> tuple[bool, str]:
    if trades_today >= rails.max_trades_per_day:
        return False, f"at max trades/day ({rails.max_trades_per_day})"
    return True, "ok"


def scalp_daily_loss_ok(realized_pnl_today: float, rails: ScalpRails) -> tuple[bool, str]:
    """realized_pnl_today is signed ($; negative = loss). Halt when the loss reaches
    the stop. A stop of 0 (or less) means the halt is DISABLED — never halts."""
    if rails.daily_loss_stop_usd <= 0:
        return True, "daily loss halt disabled"
    if realized_pnl_today <= -abs(rails.daily_loss_stop_usd):
        return False, (
            f"daily loss ${realized_pnl_today:.0f} hit stop -${abs(rails.daily_loss_stop_usd):.0f} — halted"
        )
    return True, "ok"


def scalp_one_at_a_time_ok(open_scalp_count: int, rails: ScalpRails) -> tuple[bool, str]:
    if open_scalp_count >= rails.max_concurrent_scalps:
        return False, f"already holding {open_scalp_count} scalp(s) (max {rails.max_concurrent_scalps})"
    return True, "ok"


def scalp_entry_window_ok(now_et_hhmm: str, rails: ScalpRails) -> tuple[bool, str]:
    """now_et_hhmm is 'HH:MM' ET. No NEW entries at/after the cutoff (string compare
    is correct for zero-padded HH:MM)."""
    if now_et_hhmm >= rails.entry_cutoff_et:
        return False, f"past entry cutoff {rails.entry_cutoff_et} ET"
    return True, "ok"


def scalp_must_flatten(now_et_hhmm: str, rails: ScalpRails) -> bool:
    """True once we've reached the mandatory EOD-flatten time. Checked FIRST in the
    exit path, enforced regardless of P&L (0DTE auto-exercise guard)."""
    return now_et_hhmm >= rails.eod_flatten_et
