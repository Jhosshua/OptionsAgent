"""Bridges raw Alpaca account/position data into the shapes risk_rails.py and
exits.py operate on. Kept as a thin adapter so the rails and exit checks stay
pure and testable without a live API call.
"""

from __future__ import annotations

from harness.occ import parse_occ_symbol
from harness.risk_rails import AccountState


def build_account_state(*, account_raw: dict, positions_raw: list[dict]) -> AccountState:
    """account_raw: output of alpaca_glue.PaperClient.account_state().
    positions_raw: output of alpaca_glue.PaperClient.list_positions() (ALL
    positions — equities and options).

    Exposure convention (deliberately conservative — must NEVER understate):
    - SHORT option (qty < 0): strike x 100 x |qty| — the collateral the
      position can demand, NOT the small premium credit (using cost_basis
      here understated CSP exposure ~100x and silently disabled the
      portfolio caps).
    - Long option / equity: abs(cost_basis).
    A covered call's short leg therefore double-counts with its shares —
    conservative by design, never permissive."""
    equity = account_raw["equity_usd"]
    available_obp = account_raw["available_options_buying_power_usd"]

    underlying_exposure: dict[str, float] = {}
    gross_exposure = 0.0
    option_positions = 0

    for pos in positions_raw:
        qty = pos["qty"]
        if pos["asset_class"].lower() in ("us_option", "option"):
            option_positions += 1
            try:
                parts = parse_occ_symbol(pos["symbol"])
                underlying = parts.underlying
                if qty < 0:
                    notional = parts.strike * 100 * abs(qty)
                else:
                    notional = abs(pos["cost_basis"])
            except ValueError:
                underlying = pos["symbol"]
                notional = abs(pos["cost_basis"])
        else:
            underlying = pos["symbol"]
            notional = abs(pos["cost_basis"])
        underlying_exposure[underlying] = underlying_exposure.get(underlying, 0.0) + notional
        gross_exposure += notional

    return AccountState(
        equity_usd=equity,
        available_options_buying_power_usd=available_obp,
        open_positions_count=option_positions,
        underlying_exposure_usd=underlying_exposure,
        gross_exposure_usd=gross_exposure,
    )
