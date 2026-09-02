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
import math
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


# Historical credit-spread replay (2026-07-08 through 2026-07-31) found three
# realized winners: CCL bullish put width >= $1.50 for >= $0.29 credit, SOFI
# bullish put width >= $1.00 for >= $0.23 credit, and F bearish call width <=
# $0.50 for >= $0.06 credit. This is intentionally an IN-SAMPLE overfit, not
# a claim of a durable edge. It is hard-coded here so config edits cannot
# silently broaden the live candidate set. The bot is retired until a new
# deployment is explicitly created.
_CREDIT_SPREAD_OVERFIT_RULES = (
    ("CCL", "bullish", 0.29, 1.50, None),
    ("SOFI", "bullish", 0.23, 1.00, None),
    ("F", "bearish", 0.06, None, 0.50),
)


# Which gate judges a credit spread after the contract picker (delta / DTE /
# width) has already accepted it:
#   winner_profile  — the frozen in-sample table above (default, the research
#                     posture since 2026-07-27: collect OOS evidence on 3 shapes).
#   research_rules  — skip the table; any universe name whose spread passed the
#                     picker's research rules (short delta 0.15-0.30, DTE 30-45,
#                     width <= $2) may open. Operator decision 2026-09-01 for the
#                     Alpaca hackathon window; MUST ship with OA_MAX_POSITION_USD
#                     set, because sizing is a % of buying power and the account
#                     is $100k (see MEMORY.md 2026-09-01).
# Unknown values fall back to the STRICT mode, so a typo can never open the gate.
CREDIT_SPREAD_GATE_ENV = "OA_CREDIT_SPREAD_GATE"
CREDIT_SPREAD_GATE_MODES = ("winner_profile", "research_rules")


def active_credit_spread_gate() -> str:
    raw = (os.environ.get(CREDIT_SPREAD_GATE_ENV) or "winner_profile").strip().lower()
    return raw if raw in CREDIT_SPREAD_GATE_MODES else "winner_profile"


# research_rules liquidity filter. Entry credit is short.BID - long.ASK and the
# exit sweep prices the unwind at short.ASK - long.BID, so the round-trip
# bid/ask is paid twice and the 2x-credit stop (config spreads.stop_loss_pct)
# fires at t=0 on any spread whose quoted width exceeds its credit. Replay of
# the 2026-09-01 chain snapshots: 8 of 22 pickable shapes were already past
# the stop on the quotes they were picked from. The winner table's credit
# minimums used to hide this; research_rules needs its own floor.
RESEARCH_RULES_MIN_CREDIT = 0.10          # $ per share
RESEARCH_RULES_MAX_CLOSE_COST_X = 1.5     # unwind-now cost <= 1.5x credit (25% under the 2x stop)


def credit_spread_gate_decision(
    *,
    underlying: str,
    direction: str,
    width: float,
    net_credit: float,
    close_cost_now: float | None = None,
    mode: str | None = None,
) -> tuple[bool, str]:
    """Route a picker-approved credit spread through the active gate mode.

    research_rules fails closed on a non-positive width or credit, on a credit
    below RESEARCH_RULES_MIN_CREDIT, and on a spread whose cost to unwind at
    the same quotes (short.ask - long.bid) already sits at or past 1.5x the
    credit — that spread would be stopped out by the first confirmed sweep.
    `close_cost_now` is REQUIRED in research_rules mode; None fails closed."""
    mode = mode or active_credit_spread_gate()
    if mode == "winner_profile":
        return credit_spread_overfit_decision(
            underlying=underlying, direction=direction, width=width, net_credit=net_credit
        )
    if not math.isfinite(width) or width <= 0:
        return False, f"research_rules invalid width {width!r}"
    if not math.isfinite(net_credit) or net_credit <= 0:
        return False, f"research_rules invalid net credit {net_credit!r}"
    if net_credit < RESEARCH_RULES_MIN_CREDIT:
        return False, (
            f"research_rules credit {net_credit:.2f} below minimum {RESEARCH_RULES_MIN_CREDIT:.2f}"
        )
    if close_cost_now is None or not math.isfinite(close_cost_now):
        return False, "research_rules missing unwind quote (close_cost_now); fail closed"
    if close_cost_now >= net_credit * RESEARCH_RULES_MAX_CLOSE_COST_X:
        return False, (
            f"research_rules illiquid: unwind now costs {close_cost_now:.2f} vs credit "
            f"{net_credit:.2f} (>= {RESEARCH_RULES_MAX_CLOSE_COST_X}x; the 2x stop would fire on entry)"
        )
    return True, (
        f"research_rules gate: winner profile bypassed for {str(underlying).upper()} "
        f"{str(direction).lower()} (width {width:.2f}, credit {net_credit:.2f}, "
        f"unwind-now {close_cost_now:.2f})"
    )


def research_rules_missing_cap(gate_mode: str, rails: Rails) -> bool:
    """The open gate and the dollar cap are coupled: on a $100k account the
    %-of-BP sizer alone yields ~178 contracts per idea. A cycle must refuse to
    run in research_rules mode when OA_MAX_POSITION_USD is unset or unparsable
    (active_rails() silently drops a bad value, e.g. '3,000')."""
    return gate_mode == "research_rules" and rails.max_position_abs_usd is None


def credit_spread_overfit_decision(
    *, underlying: str, direction: str, width: float, net_credit: float
) -> tuple[bool, str]:
    """Apply the deliberately overfit historical winner profile.

    Returns (approved, reason). Unknown symbols, directions, widths, and
    credits fail closed. The caller should run this only for credit spreads;
    other strategy families are unaffected.
    """
    symbol = str(underlying).upper()
    side = str(direction).lower()
    if not math.isfinite(width) or width <= 0:
        return False, f"overfit_profile invalid width {width!r}"
    if not math.isfinite(net_credit) or net_credit <= 0:
        return False, f"overfit_profile invalid net credit {net_credit!r}"
    for rule_symbol, rule_side, min_credit, min_width, max_width in _CREDIT_SPREAD_OVERFIT_RULES:
        if symbol != rule_symbol or side != rule_side:
            continue
        if net_credit < min_credit:
            return False, (
                f"overfit_profile credit {net_credit:.2f} below {rule_symbol} minimum "
                f"{min_credit:.2f}"
            )
        if min_width is not None and width < min_width:
            return False, (
                f"overfit_profile width {width:.2f} below {rule_symbol} minimum "
                f"{min_width:.2f}"
            )
        if max_width is not None and width > max_width:
            return False, (
                f"overfit_profile width {width:.2f} above {rule_symbol} maximum "
                f"{max_width:.2f}"
            )
        return True, f"overfit_profile matched {rule_symbol} {rule_side}"

    return False, f"overfit_profile no historical winner rule for {symbol} {side}"


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
    account: AccountState, *, underlying: str, collateral_usd: float, positions_opened: int = 1
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
        # The broker counts LEGS (a spread = 2 positions), so count what the
        # broker will count or the intra-cycle cap admits twice as many spreads
        # as the next day's read would.
        open_positions_count=account.open_positions_count + max(1, int(positions_opened)),
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


# ---------------------------------------------------------------------------
# Equity intraday scalp rails — the share-based rules mined 2026-08-28 from
# 125 sessions of SPY/QQQ minute bars (research_scalp_mine/stage3, deliberate
# IN-SAMPLE overfit, frozen to collect live out-of-sample evidence).
#   Rule A "morning fade": at 10:15 ET, if the last close is above BOTH the
#     session VWAP and the 15-minute opening range high, go SHORT; below both,
#     go LONG. Exit after 120 minutes, on stop, or at the 15:50 flatten.
#   Rule C "gap follow": QQQ only, at 13:00 ET, when the day gapped > 0.8% at
#     the open, hold WITH the gap direction until ~15:00 (time exit), stop, or
#     the 15:50 flatten.
# Same discipline as above: hard values live HERE, env may only TIGHTEN.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquityScalpRails:
    notional_per_trade_usd: float = 20_000.0  # operator 2026-08-28 ("$20k equity positions")
    max_trades_per_day: int = 2               # one morning fade + one gap follow
    max_concurrent: int = 2
    stop_loss_pct: float = 0.007              # 0.7% adverse move from entry
    daily_loss_stop_usd: float = 300.0        # halt after ~2 full stop-outs
    entry_windows: tuple = (("morning_fade", "10:15", "10:26"),   # fire once inside the window
                            ("gap_follow", "13:00", "13:11"))
    time_exit_minutes: int = 120
    eod_flatten_et: str = "15:50"             # MANDATORY flat by close


def active_equity_scalp_rails() -> EquityScalpRails:
    """EquityScalpRails with tighten-only env overrides:
    OA_EQUITY_NOTIONAL_USD (lower), OA_EQUITY_MAX_TRADES (lower),
    OA_EQUITY_DAILY_LOSS_USD (lower), OA_EQUITY_STOP_PCT (lower)."""
    base = EquityScalpRails()
    notional = _tighten_float(base.notional_per_trade_usd, os.environ.get("OA_EQUITY_NOTIONAL_USD"))
    stop = _tighten_float(base.stop_loss_pct, os.environ.get("OA_EQUITY_STOP_PCT"))
    loss = _tighten_float(base.daily_loss_stop_usd, os.environ.get("OA_EQUITY_DAILY_LOSS_USD"))
    max_trades = base.max_trades_per_day
    raw_mt = os.environ.get("OA_EQUITY_MAX_TRADES")
    if raw_mt:
        try:
            mt = int(float(raw_mt))
            if mt > 0:
                max_trades = min(max_trades, mt)
        except (TypeError, ValueError):
            pass
    return replace(base, notional_per_trade_usd=notional, stop_loss_pct=stop,
                   daily_loss_stop_usd=loss, max_trades_per_day=max_trades)
