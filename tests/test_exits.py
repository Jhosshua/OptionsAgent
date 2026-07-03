import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.exits import OpenPosition, evaluate_exit


def make_position(**overrides):
    base = dict(
        underlying="AAPL",
        strategy_type="csp",
        strike=95.0,
        dte=30,
        entry_credit=1.20,
        cost_to_close=1.00,
    )
    base.update(overrides)
    return OpenPosition(**base)


def test_holds_when_nothing_triggers():
    decision = evaluate_exit(make_position(), dte_close=21, profit_target_pct=0.50)
    assert not decision.should_close


def test_dte_close_triggers_at_threshold():
    decision = evaluate_exit(make_position(dte=21), dte_close=21, profit_target_pct=0.50)
    assert decision.should_close
    assert "DTE" in decision.reason


def test_dte_close_does_not_trigger_above_threshold():
    decision = evaluate_exit(make_position(dte=22), dte_close=21, profit_target_pct=0.50)
    assert not decision.should_close


def test_profit_target_triggers_at_50_percent():
    # entry credit 1.20, 50% target -> close at cost_to_close <= 0.60
    decision = evaluate_exit(
        make_position(dte=30, entry_credit=1.20, cost_to_close=0.60),
        dte_close=21,
        profit_target_pct=0.50,
    )
    assert decision.should_close
    assert "profit target" in decision.reason


def test_profit_target_does_not_trigger_above_threshold():
    decision = evaluate_exit(
        make_position(dte=30, entry_credit=1.20, cost_to_close=0.70),
        dte_close=21,
        profit_target_pct=0.50,
    )
    assert not decision.should_close


def test_dividend_assignment_risk_triggers_before_dte_or_profit_checks():
    position = make_position(
        strategy_type="covered_call",
        dte=30,  # would NOT trigger DTE close
        entry_credit=1.20,
        cost_to_close=1.10,  # would NOT trigger profit target
        is_ex_dividend_within_dte=True,
        dividend_amount=0.72,
        same_strike_opposite_price=0.44,  # dividend > put price -> assignment likely
    )
    decision = evaluate_exit(position, dte_close=21, profit_target_pct=0.50)
    assert decision.should_close
    assert "dividend" in decision.reason


def test_dividend_assignment_risk_does_not_trigger_when_dividend_below_put_price():
    position = make_position(
        strategy_type="covered_call",
        dte=30,
        is_ex_dividend_within_dte=True,
        dividend_amount=0.20,
        same_strike_opposite_price=0.44,  # dividend < put price -> assignment unlikely
    )
    decision = evaluate_exit(position, dte_close=21, profit_target_pct=0.50)
    assert not decision.should_close


def test_dividend_check_only_applies_to_covered_call():
    position = make_position(
        strategy_type="csp",
        is_ex_dividend_within_dte=True,
        dividend_amount=5.0,
        same_strike_opposite_price=0.10,
    )
    decision = evaluate_exit(position, dte_close=21, profit_target_pct=0.50)
    assert not decision.should_close  # dividend-assignment risk is call-specific
