"""Regression tests for the broker adapter's normalization helpers.

2026-07-07 incident: list_positions() emitted asset_class as
"AssetClass.US_OPTION" (str() of an alpaca-py enum) instead of "us_option".
Every consumer compares against the plain lowercase value, so the exit
sweep's reconcile saw ZERO live option positions and falsely marked the
day-old MARA long_put as vanished. All enum-ish fields must pass through
_status_str at the adapter boundary.

2026-07-08 incident: the CCL chain snapshot included the ADJUSTED contract
CCL1260821P00022500 (root CCL1, corporate-action rename). Alpaca's market
data returns adjusted contracts but the trading API rejects orders on them
("contract ... is not active"), crashing run_cycle at submit time. The chain
adapter must drop every row whose OCC root differs from the requested
underlying.
"""

from enum import Enum
from types import SimpleNamespace

from harness.alpaca_glue import _adapt_chain, _status_str


class FakeAssetClass(str, Enum):
    US_EQUITY = "us_equity"
    US_OPTION = "us_option"


def test_status_str_unwraps_str_enum_to_plain_value():
    assert _status_str(FakeAssetClass.US_OPTION) == "us_option"
    assert _status_str(FakeAssetClass.US_EQUITY) == "us_equity"


def test_status_str_passes_plain_strings_through_lowercased():
    assert _status_str("us_option") == "us_option"
    assert _status_str("FILLED") == "filled"


def _snap(delta: float = -0.25, bid: float = 1.10, ask: float = 1.20) -> SimpleNamespace:
    """Minimal stand-in for alpaca-py's OptionsSnapshot: only the fields the
    adapter reads (greeks.delta, latest_quote.bid/ask_price)."""
    return SimpleNamespace(
        greeks=SimpleNamespace(delta=delta),
        latest_quote=SimpleNamespace(bid_price=bid, ask_price=ask),
    )


def test_adapt_chain_drops_adjusted_contracts_with_mismatched_root():
    chain = {
        "CCL260821P00022500": _snap(),   # standard CCL contract -> kept
        "CCL1260821P00022500": _snap(),  # adjusted root CCL1 -> dropped
    }
    quotes = _adapt_chain(chain, "CCL")
    assert [q.symbol for q in quotes] == ["CCL260821P00022500"]


def test_adapt_chain_keeps_digit_roots_when_they_match_the_underlying():
    # A root that legitimately contains a digit must survive when it IS the
    # requested underlying (parse-from-the-end already guarantees the parse).
    chain = {"BRKB260821C00500000": _snap(delta=0.30)}
    quotes = _adapt_chain(chain, "brkb ")  # case/whitespace-insensitive match
    assert len(quotes) == 1
    assert quotes[0].strike == 500.0
    assert quotes[0].right == "call"


def test_adapt_chain_skips_rows_missing_greeks_or_quote():
    chain = {
        "CCL260821P00022500": SimpleNamespace(greeks=None, latest_quote=None),
        "CCL260918P00021000": _snap(),
    }
    quotes = _adapt_chain(chain, "CCL")
    assert [q.symbol for q in quotes] == ["CCL260918P00021000"]
