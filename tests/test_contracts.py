import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.contracts import OptionQuote, roll_strike_cap, select_covered_call, select_csp


def make_put(strike, dte, delta, bid):
    return OptionQuote(
        symbol=f"TEST_P{strike}",
        underlying="TEST",
        right="put",
        strike=strike,
        dte=dte,
        delta=delta,  # puts carry negative delta by convention
        bid=bid,
        ask=bid + 0.05,
    )


def make_call(strike, dte, delta, bid):
    return OptionQuote(
        symbol=f"TEST_C{strike}",
        underlying="TEST",
        right="call",
        strike=strike,
        dte=dte,
        delta=delta,
        bid=bid,
        ask=bid + 0.05,
    )


def test_select_csp_filters_by_delta_and_dte():
    chain = [
        make_put(strike=95, dte=30, delta=-0.25, bid=1.20),   # in range
        make_put(strike=90, dte=30, delta=-0.15, bid=0.60),   # delta too low
        make_put(strike=100, dte=60, delta=-0.28, bid=2.00),  # dte too far out
        make_put(strike=98, dte=10, delta=-0.22, bid=0.80),   # dte too close
    ]
    picked = select_csp(chain, delta_min=0.20, delta_max=0.30, dte_min=21, dte_max=45)
    assert picked is not None
    assert picked.strike == 95


def test_select_csp_picks_highest_score_among_valid():
    chain = [
        make_put(strike=95, dte=30, delta=-0.25, bid=1.20),
        make_put(strike=90, dte=25, delta=-0.22, bid=1.50),  # better yield, similar delta/dte
    ]
    picked = select_csp(chain, delta_min=0.20, delta_max=0.30, dte_min=21, dte_max=45)
    assert picked.strike == 90


def test_select_csp_returns_none_when_no_candidates():
    chain = [make_put(strike=95, dte=30, delta=-0.50, bid=3.00)]
    picked = select_csp(chain, delta_min=0.20, delta_max=0.30, dte_min=21, dte_max=45)
    assert picked is None


def test_select_covered_call_enforces_cost_basis_floor():
    chain = [
        make_call(strike=95, dte=30, delta=0.35, bid=1.00),   # below cost basis, excluded
        make_call(strike=105, dte=30, delta=0.35, bid=1.50),  # at/above cost basis
    ]
    picked = select_covered_call(
        chain, cost_basis=100.0, delta_min=0.30, delta_max=0.50, dte_min=21, dte_max=45
    )
    assert picked is not None
    assert picked.strike == 105


def test_roll_strike_cap():
    assert roll_strike_cap(old_strike=95.0, premium_received=1.50) == 96.5
