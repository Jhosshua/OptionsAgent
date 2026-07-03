import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.occ import parse_occ_symbol


def test_parse_call():
    parts = parse_occ_symbol("AAPL250117C00150000")
    assert parts.underlying == "AAPL"
    assert parts.expiry == date(2025, 1, 17)
    assert parts.right == "call"
    assert parts.strike == 150.0


def test_parse_put_with_fractional_strike():
    parts = parse_occ_symbol("SPY250620P00512500")
    assert parts.underlying == "SPY"
    assert parts.expiry == date(2025, 6, 20)
    assert parts.right == "put"
    assert parts.strike == 512.5


def test_parse_root_containing_digits():
    # Roots can contain digits (e.g. class shares) — parsing must anchor from
    # the END, never scan for the first digit.
    parts = parse_occ_symbol("BRKB1250117C05000000")
    assert parts.underlying == "BRKB1"
    assert parts.strike == 5000.0


def test_rejects_plain_equity_symbol():
    with pytest.raises(ValueError):
        parse_occ_symbol("AAPL")


def test_rejects_malformed_symbol():
    with pytest.raises(ValueError):
        parse_occ_symbol("AAPL250117X00150000")  # X is not C/P
