import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.positions import build_account_state


def make_account_raw():
    return {"equity_usd": 100_000.0, "available_options_buying_power_usd": 50_000.0}


def test_short_option_exposure_uses_strike_collateral_not_premium():
    # A short put's cost_basis is the small premium credit; exposure must be
    # the strike*100 collateral or the portfolio caps are ~100x too permissive.
    positions_raw = [
        {"symbol": "AAPL250117P00150000", "qty": -1.0, "asset_class": "us_option", "cost_basis": 500.0, "market_value": -520.0},
    ]
    state = build_account_state(account_raw=make_account_raw(), positions_raw=positions_raw)
    assert state.underlying_exposure_usd["AAPL"] == 15_000.0  # 150 strike x 100
    assert state.gross_exposure_usd == 15_000.0


def test_multiple_short_contracts_scale_by_qty():
    positions_raw = [
        {"symbol": "SPY250117P00500000", "qty": -2.0, "asset_class": "us_option", "cost_basis": 1000.0, "market_value": -980.0},
    ]
    state = build_account_state(account_raw=make_account_raw(), positions_raw=positions_raw)
    assert state.underlying_exposure_usd["SPY"] == 100_000.0  # 500 x 100 x 2


def test_long_option_exposure_uses_premium_paid():
    # A long option's max loss IS the premium paid — cost_basis is correct there.
    positions_raw = [
        {"symbol": "AAPL250117C00160000", "qty": 1.0, "asset_class": "us_option", "cost_basis": 800.0, "market_value": 850.0},
    ]
    state = build_account_state(account_raw=make_account_raw(), positions_raw=positions_raw)
    assert state.underlying_exposure_usd["AAPL"] == 800.0


def test_aggregates_by_underlying_and_counts_option_positions():
    positions_raw = [
        {"symbol": "AAPL250117P00150000", "qty": -1.0, "asset_class": "us_option", "cost_basis": 500.0, "market_value": -520.0},
        {"symbol": "AAPL250117C00160000", "qty": -1.0, "asset_class": "us_option", "cost_basis": 300.0, "market_value": -290.0},
        {"symbol": "AAPL", "qty": 100.0, "asset_class": "us_equity", "cost_basis": 15_500.0, "market_value": 15_800.0},
    ]
    state = build_account_state(account_raw=make_account_raw(), positions_raw=positions_raw)
    # 15000 (short put collateral) + 16000 (short call collateral) + 15500 (shares)
    assert state.underlying_exposure_usd["AAPL"] == 46_500.0
    assert state.open_positions_count == 2  # equities don't count as option positions
    assert state.equity_usd == 100_000.0
    assert state.available_options_buying_power_usd == 50_000.0
