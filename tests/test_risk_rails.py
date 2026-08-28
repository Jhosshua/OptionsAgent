import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.risk_rails import (
    AccountState,
    Proposal,
    Rails,
    active_rails,
    apply_opened_position,
    conviction_to_size_frac,
    credit_spread_overfit_decision,
    evaluate_proposal,
)


def make_account(**overrides):
    base = dict(
        equity_usd=5_000.0,
        available_options_buying_power_usd=5_000.0,
        open_positions_count=0,
        underlying_exposure_usd={},
        gross_exposure_usd=0.0,
    )
    base.update(overrides)
    return AccountState(**base)


def make_proposal(**overrides):
    base = dict(
        underlying="AAPL",
        strategy_type="csp",
        direction="bullish",
        conviction=0.75,
        thesis="test",
    )
    base.update(overrides)
    return Proposal(**base)


def test_below_conviction_floor_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(conviction=0.55), make_account(), allowed_strategies=["csp"]
    )
    assert not decision.approved
    assert "conviction" in decision.reason


def test_at_conviction_floor_gets_min_fraction_of_available_bp():
    decision = evaluate_proposal(
        make_proposal(conviction=0.60), make_account(), allowed_strategies=["csp"]
    )
    assert decision.approved
    assert decision.position_cap_usd == 5_000.0 * Rails().min_size_frac


def test_max_conviction_may_take_all_available_bp():
    # full-deploy policy (operator 2026-07-03): no percentage caps —
    # a max-conviction idea is allowed to use ALL remaining buying power
    decision = evaluate_proposal(
        make_proposal(conviction=0.90), make_account(), allowed_strategies=["csp"]
    )
    assert decision.approved
    assert decision.position_cap_usd == 5_000.0


def test_strategy_not_in_phase_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(strategy_type="long_straddle"), make_account(), allowed_strategies=["csp"]
    )
    assert not decision.approved
    assert "strategy_type" in decision.reason


def test_max_concurrent_positions_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(), make_account(open_positions_count=6), allowed_strategies=["csp"]
    )
    assert not decision.approved
    assert "max_concurrent_positions" in decision.reason


def test_zero_buying_power_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(), make_account(available_options_buying_power_usd=0.0), allowed_strategies=["csp"]
    )
    assert not decision.approved
    assert "buying power" in decision.reason


def test_conviction_scaling_saturates_at_max():
    rails = Rails()
    assert conviction_to_size_frac(0.85, rails) == 1.0
    assert conviction_to_size_frac(0.95, rails) == 1.0
    assert conviction_to_size_frac(0.60, rails) == rails.min_size_frac
    mid = conviction_to_size_frac(0.725, rails)
    assert rails.min_size_frac < mid < 1.0


def test_env_absolute_ceiling_tightens(monkeypatch):
    monkeypatch.setenv("OA_MAX_POSITION_USD", "1000")
    rails = active_rails()
    decision = evaluate_proposal(
        make_proposal(conviction=0.90), make_account(), allowed_strategies=["csp"], rails=rails
    )
    assert decision.approved
    assert decision.position_cap_usd == 1_000.0  # ceiling wins over full BP


def test_apply_opened_position_shrinks_next_budget():
    account = make_account()
    updated = apply_opened_position(account, underlying="AAPL", collateral_usd=3_000.0)
    assert updated.available_options_buying_power_usd == 2_000.0
    assert updated.open_positions_count == 1
    assert updated.underlying_exposure_usd["AAPL"] == 3_000.0
    assert account.open_positions_count == 0  # frozen semantics


def test_max_conviction_first_fill_exhausts_bp_for_the_cycle():
    # literal consequence of "no cap": a 0.85+ conviction first proposal takes
    # everything; the second proposal in the same cycle vetoes on zero BP
    account = make_account()
    d1 = evaluate_proposal(make_proposal(conviction=0.90), account, allowed_strategies=["csp"])
    assert d1.approved and d1.position_cap_usd == 5_000.0
    account = apply_opened_position(account, underlying="AAPL", collateral_usd=d1.position_cap_usd)
    d2 = evaluate_proposal(
        make_proposal(underlying="MSFT", conviction=0.90), account, allowed_strategies=["csp"]
    )
    assert not d2.approved
    assert "buying power" in d2.reason


def test_floor_conviction_fills_leave_room_for_more():
    # at the floor each fill takes 30% of what REMAINS, so several trades fit
    account = make_account()
    approved = 0
    for i in range(4):
        d = evaluate_proposal(
            make_proposal(underlying=f"SYM{i}", conviction=0.60), account, allowed_strategies=["csp"]
        )
        if not d.approved:
            break
        approved += 1
        account = apply_opened_position(account, underlying=f"SYM{i}", collateral_usd=d.position_cap_usd)
    assert approved == 4
    assert account.available_options_buying_power_usd > 0


def test_credit_spread_overfit_accepts_archived_winner_profiles():
    assert credit_spread_overfit_decision(
        underlying="CCL", direction="bullish", width=1.5, net_credit=0.29
    )[0]
    assert credit_spread_overfit_decision(
        underlying="SOFI", direction="bullish", width=1.0, net_credit=0.23
    )[0]
    assert credit_spread_overfit_decision(
        underlying="F", direction="bearish", width=0.5, net_credit=0.06
    )[0]


def test_credit_spread_overfit_rejects_archived_loser_profiles_and_unknowns():
    assert not credit_spread_overfit_decision(
        underlying="CCL", direction="bullish", width=1.0, net_credit=0.17
    )[0]
    assert not credit_spread_overfit_decision(
        underlying="AAL", direction="bullish", width=1.0, net_credit=0.19
    )[0]
    assert not credit_spread_overfit_decision(
        underlying="SOFI", direction="bullish", width=0.5, net_credit=0.11
    )[0]
    assert not credit_spread_overfit_decision(
        underlying="F", direction="bullish", width=0.5, net_credit=0.06
    )[0]


def test_credit_spread_overfit_fails_closed_on_non_finite_inputs():
    assert not credit_spread_overfit_decision(
        underlying="CCL", direction="bullish", width=float("nan"), net_credit=0.29
    )[0]
    assert not credit_spread_overfit_decision(
        underlying="CCL", direction="bullish", width=1.5, net_credit=float("inf")
    )[0]
    assert not credit_spread_overfit_decision(
        underlying="SOFI", direction="bullish", width=0.0, net_credit=0.23
    )[0]
