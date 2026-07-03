import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.risk_rails import (
    AccountState,
    Proposal,
    Rails,
    active_rails,
    conviction_to_size_frac,
    evaluate_proposal,
)


def make_account(**overrides):
    base = dict(
        equity_usd=100_000.0,
        options_buying_power_usd=100_000.0,
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
        options_buying_power_usd=100_000.0,
        available_options_buying_power_usd=39_000.0,  # 61% used > 60% cap
    )
    decision = evaluate_proposal(make_proposal(), account, allowed_strategies=["csp"])
    assert not decision.approved
    assert "margin utilization" in decision.reason


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
