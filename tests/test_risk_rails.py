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
    evaluate_proposal,
)


def make_account(**overrides):
    base = dict(
        equity_usd=100_000.0,
        available_options_buying_power_usd=100_000.0,
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
        make_proposal(conviction=0.55),
        make_account(),
        allowed_strategies=["csp"],
    )
    assert not decision.approved
    assert "conviction" in decision.reason


def test_at_conviction_floor_is_approved():
    decision = evaluate_proposal(
        make_proposal(conviction=0.60),
        make_account(),
        allowed_strategies=["csp"],
    )
    assert decision.approved


def test_strategy_not_in_phase_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(strategy_type="long_straddle"),
        make_account(),
        allowed_strategies=["csp", "covered_call"],
    )
    assert not decision.approved
    assert "strategy_type" in decision.reason


def test_max_concurrent_positions_is_vetoed():
    decision = evaluate_proposal(
        make_proposal(),
        make_account(open_positions_count=6),
        allowed_strategies=["csp"],
    )
    assert not decision.approved
    assert "max_concurrent_positions" in decision.reason


def test_margin_utilization_buffer_is_vetoed():
    account = make_account(
        available_options_buying_power_usd=39_000.0,  # 1 - 39k/100k = 61% used > 60% cap
    )
    decision = evaluate_proposal(make_proposal(), account, allowed_strategies=["csp"])
    assert not decision.approved
    assert "margin utilization" in decision.reason


def test_margin_utilization_fails_safe_on_zero_buying_power():
    # A None/0 buying-power read from the broker must veto, never trade blind.
    account = make_account(available_options_buying_power_usd=0.0)
    decision = evaluate_proposal(make_proposal(), account, allowed_strategies=["csp"])
    assert not decision.approved
    assert "margin utilization" in decision.reason


def test_margin_utilization_clamps_when_bp_exceeds_equity():
    # Margin accounts can report BP > equity; utilization clamps to 0, no veto here.
    account = make_account(available_options_buying_power_usd=180_000.0)
    assert account.margin_utilization() == 0.0


def test_apply_opened_position_updates_all_caps_inputs():
    account = make_account()
    updated = apply_opened_position(account, underlying="AAPL", collateral_usd=15_000.0)
    assert updated.open_positions_count == 1
    assert updated.underlying_exposure_usd["AAPL"] == 15_000.0
    assert updated.gross_exposure_usd == 15_000.0
    assert updated.available_options_buying_power_usd == 85_000.0
    # original snapshot untouched (frozen semantics)
    assert account.open_positions_count == 0


def test_sequential_fills_within_one_cycle_hit_the_gross_cap():
    # Six 15% positions against a 60% gross cap: with per-fill state updates
    # the 5th proposal must be vetoed (4 x 15% = 60% already deployed).
    account = make_account()
    approved = 0
    for i in range(6):
        symbol = f"SYM{i}"  # one distinct symbol per iteration, used for BOTH
        # the proposal and the fill — attributing the fill to a different
        # symbol than was proposed lets the per-underlying cap shrink later
        # fills and masks the gross-cap behavior under test
        decision = evaluate_proposal(
            make_proposal(underlying=symbol, conviction=0.85),
            account,
            allowed_strategies=["csp"],
        )
        if not decision.approved:
            break
        approved += 1
        account = apply_opened_position(
            account, underlying=symbol, collateral_usd=decision.position_cap_usd
        )
    assert approved == 4  # 4 x 15% = 60% gross -> 5th vetoed


def test_gross_exposure_cap_is_vetoed():
    account = make_account(gross_exposure_usd=60_000.0)  # at 60% of 100k equity
    decision = evaluate_proposal(make_proposal(), account, allowed_strategies=["csp"])
    assert not decision.approved
    assert "gross exposure" in decision.reason


def test_per_underlying_cap_is_vetoed():
    account = make_account(underlying_exposure_usd={"AAPL": 20_000.0})  # at 20% cap
    decision = evaluate_proposal(make_proposal(underlying="AAPL"), account, allowed_strategies=["csp"])
    assert not decision.approved
    assert "AAPL" in decision.reason


def test_conviction_scaling_saturates_at_max():
    rails = Rails()
    assert conviction_to_size_frac(0.85, rails) == 1.0
    assert conviction_to_size_frac(0.95, rails) == 1.0
    # clearing the floor gets the MINIMUM size, never zero (a zero-size trade
    # would be a silent no-op masquerading as an approved decision)
    assert conviction_to_size_frac(0.60, rails) == rails.min_size_frac
    mid = conviction_to_size_frac(0.725, rails)
    assert rails.min_size_frac < mid < 1.0  # strictly between floor and max scaling


def test_covered_straddle_gets_tighter_position_cap():
    rails = Rails()
    account = make_account()
    decision = evaluate_proposal(
        make_proposal(strategy_type="covered_straddle", conviction=0.85),
        account,
        allowed_strategies=["covered_straddle"],
        rails=rails,
    )
    assert decision.approved
    # 10% covered-straddle cap vs 15% default, both at full conviction (size_frac=1.0)
    assert decision.position_cap_usd == rails.covered_straddle_max_position_frac * 100_000.0


def test_env_override_can_only_tighten(monkeypatch):
    monkeypatch.setenv("OA_MAX_GROSS_EXPOSURE_FRAC", "0.30")
    rails = active_rails()
    assert rails.max_gross_exposure_frac == 0.30

    monkeypatch.setenv("OA_MAX_GROSS_EXPOSURE_FRAC", "0.90")  # attempt to loosen
    rails = active_rails()
    assert rails.max_gross_exposure_frac == 0.60  # unchanged — loosening is ignored
