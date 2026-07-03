import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.contracts import (
    OptionQuote,
    select_credit_spread,
    select_debit_spread,
    select_long_option,
    select_straddle,
)


def q(right, strike, dte, delta, bid, ask=None):
    return OptionQuote(
        symbol=f"TST{dte:03d}{right[0].upper()}{int(strike*1000):08d}",
        underlying="TST",
        right=right,
        strike=strike,
        dte=dte,
        delta=delta,
        bid=bid,
        ask=ask if ask is not None else bid + 0.05,
    )


def make_put_chain():
    # spot ~100; 35 DTE put ladder
    return [
        q("put", 95, 35, -0.25, 1.20),
        q("put", 92, 35, -0.18, 0.80),
        q("put", 90, 35, -0.14, 0.55),
        q("put", 85, 35, -0.08, 0.25),
    ]


def test_credit_spread_bullish_uses_puts_with_defined_width():
    legs = select_credit_spread(
        make_put_chain(), direction="bullish",
        delta_min=0.15, delta_max=0.30, dte_min=30, dte_max=45, max_width=5.0,
    )
    assert legs is not None
    assert legs.short.right == "put"
    assert legs.long.strike < legs.short.strike  # long is further OTM (below)
    assert legs.width <= 5.0
    assert legs.net_credit > 0


def test_credit_spread_bearish_uses_calls():
    chain = [
        q("call", 105, 35, 0.25, 1.10),
        q("call", 108, 35, 0.18, 0.70),
        q("call", 110, 35, 0.14, 0.50),
    ]
    legs = select_credit_spread(
        chain, direction="bearish",
        delta_min=0.15, delta_max=0.30, dte_min=30, dte_max=45, max_width=5.0,
    )
    assert legs is not None
    assert legs.short.right == "call"
    assert legs.long.strike > legs.short.strike  # long is further OTM (above)


def test_credit_spread_returns_none_without_a_long_leg_in_width():
    chain = [q("put", 95, 35, -0.25, 1.20), q("put", 80, 35, -0.05, 0.10)]  # width 15 > 5
    legs = select_credit_spread(
        chain, direction="bullish",
        delta_min=0.15, delta_max=0.30, dte_min=30, dte_max=45, max_width=5.0,
    )
    assert legs is None


def test_credit_spread_rejects_net_debit_combos():
    # long ask >= short bid -> no credit -> skip
    chain = [q("put", 95, 35, -0.25, 0.50, ask=0.55), q("put", 94, 35, -0.22, 0.60, ask=0.80)]
    legs = select_credit_spread(
        chain, direction="bullish",
        delta_min=0.15, delta_max=0.30, dte_min=30, dte_max=45, max_width=5.0,
    )
    assert legs is None


def test_debit_spread_bullish_buys_call_sells_higher_call():
    chain = [
        q("call", 100, 35, 0.55, 4.00, ask=4.20),
        q("call", 105, 35, 0.35, 2.00, ask=2.15),
        q("call", 110, 35, 0.20, 0.90, ask=1.00),
    ]
    legs = select_debit_spread(
        chain, direction="bullish",
        delta_min=0.50, delta_max=0.70, dte_min=30, dte_max=45, max_width=10.0,
    )
    assert legs is not None
    assert legs.long.strike == 100
    assert legs.short.strike > legs.long.strike
    assert (legs.long.ask - legs.short.bid) > 0


def test_long_option_picks_delta_closest_to_target():
    chain = [
        q("call", 100, 35, 0.55, 4.00),
        q("call", 97, 35, 0.62, 5.00),
        q("call", 94, 35, 0.70, 6.00),
    ]
    picked = select_long_option(
        chain, right="call", target_delta=0.60,
        delta_min=0.50, delta_max=0.70, dte_min=30, dte_max=45,
    )
    assert picked.delta == 0.62


def test_long_option_respects_dte_window():
    chain = [q("call", 100, 10, 0.60, 4.00), q("call", 100, 50, 0.60, 5.00)]
    picked = select_long_option(
        chain, right="call", target_delta=0.60,
        delta_min=0.50, delta_max=0.70, dte_min=30, dte_max=45,
    )
    assert picked is None


def test_straddle_pairs_atm_call_with_same_strike_put():
    chain = [
        q("call", 100, 44, 0.51, 3.00, ask=3.10),
        q("call", 105, 44, 0.35, 1.50, ask=1.60),
        q("put", 100, 44, -0.49, 2.90, ask=3.00),
        q("put", 105, 44, -0.65, 5.80, ask=6.00),
    ]
    pair = select_straddle(chain, dte_min=30, dte_max=60, dte_target=45)
    assert pair is not None
    assert pair.strike == 100
    assert pair.call.right == "call" and pair.put.right == "put"
    assert pair.total_debit == 3.10 + 3.00
    assert pair.total_credit == 3.00 + 2.90


def test_straddle_falls_back_to_next_expiry_if_no_matching_put():
    chain = [
        q("call", 100, 44, 0.51, 3.00),   # no 100-strike put at 44 DTE
        q("call", 100, 51, 0.52, 3.30, ask=3.40),
        q("put", 100, 51, -0.48, 3.10, ask=3.20),
    ]
    pair = select_straddle(chain, dte_min=30, dte_max=60, dte_target=45)
    assert pair is not None
    assert pair.call.dte == 51


def test_straddle_returns_none_outside_dte_window():
    chain = [q("call", 100, 10, 0.51, 3.00), q("put", 100, 10, -0.49, 2.90)]
    assert select_straddle(chain, dte_min=30, dte_max=60, dte_target=45) is None
