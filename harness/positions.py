"""Bridges raw Alpaca account/position data into the shapes risk_rails.py and
exits.py operate on. Kept as a thin adapter so the rails and exit checks stay
pure and testable without a live API call.
"""

from __future__ import annotations

from harness.risk_rails import AccountState


def build_account_state(*, account_raw: dict, positions_raw: list[dict]) -> AccountState:
    """account_raw: output of alpaca_glue.PaperClient.account_state().
    positions_raw: output of alpaca_glue.PaperClient.list_positions() (ALL
    positions — equities and options; build_account_state only aggregates
    the option legs into underlying_exposure/gross_exposure, but the equity
    legs must still be present in the list for covered-call cost-basis reads
    elsewhere).

    Options positions carry a negative market_value convention varies by
    side; this uses abs(cost_basis) as the notional/collateral proxy per
    underlying, which is conservative (never understates exposure)."""
    equity = account_raw["equity_usd"]
    obp = account_raw["options_buying_power_usd"]

    underlying_exposure: dict[str, float] = {}
    gross_exposure = 0.0
    option_positions = 0

    for pos in positions_raw:
        notional = abs(pos["cost_basis"])
        if pos["asset_class"].lower() in ("us_option", "option"):
            option_positions += 1
            underlying = _underlying_from_occ_symbol(pos["symbol"])
        else:
            underlying = pos["symbol"]
        underlying_exposure[underlying] = underlying_exposure.get(underlying, 0.0) + notional
        gross_exposure += notional

    return AccountState(
        equity_usd=equity,
        options_buying_power_usd=obp,
        available_options_buying_power_usd=obp,  # refined once a real BP-used feed exists
        open_positions_count=option_positions,
        underlying_exposure_usd=underlying_exposure,
        gross_exposure_usd=gross_exposure,
    )


def _underlying_from_occ_symbol(occ_symbol: str) -> str:
    """OCC option symbols are ROOT + YYMMDD + C/P + strike*1000, root is
    left-padded to 6 chars but Alpaca's `symbol` field is typically just the
    raw root prefix before the date digits start."""
    for i, ch in enumerate(occ_symbol):
        if ch.isdigit():
            return occ_symbol[:i]
    return occ_symbol
