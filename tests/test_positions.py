import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.positions import _underlying_from_occ_symbol, build_account_state


def test_underlying_from_occ_symbol():
    assert _underlying_from_occ_symbol("AAPL250117C00150000") == "AAPL"
    assert _underlying_from_occ_symbol("SPY250117P00500000") == "SPY"
    assert _underlying_from_occ_symbol("AAPL") == "AAPL"  # no digits -> whole string


def test_build_account_state_aggregates_by_underlying():
    account_raw = {"equity_usd": 100_000.0, "options_buying_power_usd": 50_000.0}
    positions_raw = [
        {"symbol": "AAPL250117P00150000", "qty": -1, "asset_class": "us_option", "cost_basis": 500.0, "market_value": -520.0},
        {"symbol": "AAPL250117C00160000", "qty": -1, "asset_class": "us_option", "cost_basis": 300.0, "market_value": -290.0},
        {"symbol": "SPY250117P00500000", "qty": -1, "asset_class": "us_option", "cost_basis": 1000.0, "market_value": -980.0},
    ]
    state = build_account_state(account_raw=account_raw, positions_raw=positions_raw)
    assert state.equity_usd == 100_000.0
    assert state.open_positions_count == 3
    assert state.underlying_exposure_usd["AAPL"] == 800.0
    assert state.underlying_exposure_usd["SPY"] == 1000.0
    assert state.gross_exposure_usd == 1800.0
