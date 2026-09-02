from harness.contracts import OptionQuote, select_credit_spread
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


# -- 2026-09-02: the long leg is chosen by unwind-to-credit ratio, not nearest strike --

def _tq(strike, delta, bid, ask, dte=44):
    return OptionQuote(symbol=f"T{strike}", underlying="T", right="call", strike=strike, dte=dte,
                       delta=delta, bid=bid, ask=ask)


def test_credit_spread_prefers_the_pair_with_the_best_unwind_ratio_inside_max_width():
    """Today's real T chain shape: short 28C bid 0.33/ask 0.41; long 29C bid 0.23/ask 0.22 -> $1
    pair credit 0.11 unwind 0.18 (1.64x); long 30C bid 0.18/ask 0.16 -> $2 pair credit 0.17
    unwind 0.23 (1.35x). The old picker took the 29C (nearest); the exit rule would have stopped
    that pair out on entry."""
    chain = [
        _tq(28.0, 0.22, 0.33, 0.41),
        _tq(29.0, 0.14, 0.23, 0.22),
        _tq(30.0, 0.09, 0.18, 0.16),
    ]
    pair = select_credit_spread(chain, direction="bearish", delta_min=0.15, delta_max=0.30,
                                dte_min=30, dte_max=45, max_width=2.0)
    assert pair is not None
    assert pair.long.strike == 30.0
    assert abs(pair.net_credit - 0.17) < 1e-9
    assert (pair.short.ask - pair.long.bid) / pair.net_credit < 1.5


def test_credit_spread_still_respects_max_width():
    chain = [
        _tq(28.0, 0.22, 0.33, 0.41),
        _tq(29.0, 0.14, 0.23, 0.22),
        _tq(30.0, 0.09, 0.18, 0.16),
        _tq(31.0, 0.05, 0.10, 0.08),   # $3 wide: better ratio, but outside max_width
    ]
    pair = select_credit_spread(chain, direction="bearish", delta_min=0.15, delta_max=0.30,
                                dte_min=30, dte_max=45, max_width=2.0)
    assert pair.long.strike == 30.0


def test_credit_spread_takes_nearest_when_it_is_also_the_best_ratio():
    chain = [
        _tq(28.0, 0.22, 0.40, 0.44),
        _tq(29.0, 0.14, 0.10, 0.12),   # $1: credit 0.28, unwind 0.34 -> 1.21x
        _tq(30.0, 0.09, 0.02, 0.04),   # $2: credit 0.36, unwind 0.42 -> 1.17x (better ratio, wider)
    ]
    pair = select_credit_spread(chain, direction="bearish", delta_min=0.15, delta_max=0.30,
                                dte_min=30, dte_max=45, max_width=2.0)
    assert pair.long.strike == 30.0  # lower ratio wins even when the nearest is fine
