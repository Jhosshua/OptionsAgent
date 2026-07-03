import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.exits import ExitRules, OpenPosition, evaluate_exit

WHEEL_RULES = ExitRules(dte_close=21, profit_target_pct=0.50, stop_loss_pct=None)
SPREAD_RULES = ExitRules(dte_close=21, profit_target_pct=0.50, stop_loss_pct=1.00)
LONG_RULES = ExitRules(dte_close=21, profit_target_pct=1.00, stop_loss_pct=0.50)
STRADDLE_RULES = ExitRules(dte_close=21, profit_target_pct=0.50, stop_loss_pct=0.50)


def make_short(**overrides):
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


def make_long(**overrides):
    base = dict(
        underlying="AAPL",
        strategy_type="long_call",
        strike=150.0,
        dte=35,
        entry_debit=4.00,
        current_value=4.50,
    )
    base.update(overrides)
    return OpenPosition(**base)


# -- short premium ---------------------------------------------------------

def test_short_holds_when_nothing_triggers():
    assert not evaluate_exit(make_short(), WHEEL_RULES).should_close


def test_short_dte_close_triggers_at_threshold():
    decision = evaluate_exit(make_short(dte=21), WHEEL_RULES)
    assert decision.should_close
    assert "DTE" in decision.reason


def test_short_profit_target_triggers_at_50_percent():
    decision = evaluate_exit(make_short(entry_credit=1.20, cost_to_close=0.60), WHEEL_RULES)
    assert decision.should_close
    assert "profit target" in decision.reason


def test_short_stop_loss_triggers_for_credit_spread():
    # credit 1.00, stop 100% -> close once buy-back cost >= 2.00
    decision = evaluate_exit(
        make_short(strategy_type="credit_spread", entry_credit=1.00, cost_to_close=2.10),
        SPREAD_RULES,
    )
    assert decision.should_close
    assert "stop loss" in decision.reason


def test_wheel_has_no_stop_loss():
    # same loss situation, but wheel rules (stop=None) hold instead
    decision = evaluate_exit(make_short(entry_credit=1.00, cost_to_close=2.10), WHEEL_RULES)
    assert not decision.should_close


def test_dividend_assignment_triggers_for_covered_call():
    position = make_short(
        strategy_type="covered_call",
        dte=30,
        entry_credit=1.20,
        cost_to_close=1.10,
        is_ex_dividend_within_dte=True,
        dividend_amount=0.72,
        same_strike_opposite_price=0.44,
    )
    decision = evaluate_exit(position, WHEEL_RULES)
    assert decision.should_close
    assert "dividend" in decision.reason


def test_dividend_assignment_triggers_for_covered_straddle():
    position = make_short(
        strategy_type="covered_straddle",
        dte=30,
        entry_credit=4.00,
        cost_to_close=3.80,
        is_ex_dividend_within_dte=True,
        dividend_amount=0.80,
        same_strike_opposite_price=0.30,
    )
    decision = evaluate_exit(position, STRADDLE_RULES)
    assert decision.should_close
    assert "dividend" in decision.reason


def test_dividend_check_does_not_apply_to_csp():
    position = make_short(
        strategy_type="csp",
        is_ex_dividend_within_dte=True,
        dividend_amount=5.0,
        same_strike_opposite_price=0.10,
    )
    assert not evaluate_exit(position, WHEEL_RULES).should_close


# -- long structures ---------------------------------------------------------

def test_long_holds_when_nothing_triggers():
    assert not evaluate_exit(make_long(), LONG_RULES).should_close


def test_long_profit_target_at_100_percent():
    decision = evaluate_exit(make_long(entry_debit=4.00, current_value=8.00), LONG_RULES)
    assert decision.should_close
    assert "profit target" in decision.reason


def test_long_stop_loss_at_50_percent():
    decision = evaluate_exit(make_long(entry_debit=4.00, current_value=1.90), LONG_RULES)
    assert decision.should_close
    assert "stop loss" in decision.reason


def test_long_dte_close():
    decision = evaluate_exit(make_long(dte=21), LONG_RULES)
    assert decision.should_close
    assert "DTE" in decision.reason


def test_long_straddle_profit_at_50_percent_of_debit():
    decision = evaluate_exit(
        make_long(strategy_type="long_straddle", entry_debit=6.00, current_value=9.00),
        STRADDLE_RULES,
    )
    assert decision.should_close
    assert "profit target" in decision.reason


def test_unknown_strategy_type_holds_and_flags():
    decision = evaluate_exit(make_short(strategy_type="mystery"), WHEEL_RULES)
    assert not decision.should_close
    assert "unknown" in decision.reason
