from run_cycle import _select_and_price
from harness.contracts import OptionQuote
from harness.env import config
from harness.risk_rails import Proposal


def _q(right, strike, delta, bid, ask):
    return OptionQuote(
        symbol=f"CCL{strike}",
        underlying="CCL",
        right=right,
        strike=strike,
        dte=35,
        delta=delta,
        bid=bid,
        ask=ask,
    )


def _proposal(**overrides):
    values = dict(
        underlying="CCL",
        strategy_type="credit_spread",
        direction="bullish",
        conviction=0.75,
        thesis="test",
    )
    values.update(overrides)
    return Proposal(**values)


def test_run_cycle_gate_allows_an_archived_winner_shape():
    result = _select_and_price(
        _proposal(),
        [_q("put", 24.0, -0.25, 0.40, 0.45), _q("put", 22.5, -0.15, 0.10, 0.11)],
        config(),
        [],
        0.5,
    )
    assert result[-1] is None
    assert result[2].__name__ == "execute_credit_spread"


def test_run_cycle_gate_skips_a_known_loser_shape():
    result = _select_and_price(
        _proposal(),
        [_q("put", 24.0, -0.25, 0.28, 0.33), _q("put", 23.0, -0.15, 0.10, 0.11)],
        config(),
        [],
        0.5,
    )
    assert result[0] is None
    assert result[-1].startswith("overfit_profile")
