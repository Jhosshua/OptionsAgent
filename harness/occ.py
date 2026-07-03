"""OCC option-symbol parsing. One shared, tested parser — alpaca-py's chain
snapshots don't expose strike/expiry/right as fields (verified against
alpaca-py 0.43.4: OptionsSnapshot has only symbol/quotes/trade/IV/greeks), so
everything must be parsed from the OCC symbol itself.

Format: ROOT + YYMMDD + C|P + 8-digit strike*1000, e.g.
AAPL250117C00150000 -> AAPL, 2025-01-17, call, 150.0. Parsed from the END,
never by scanning for the first digit, so roots containing digits stay safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OccParts:
    underlying: str
    expiry: date
    right: str  # "call" | "put"
    strike: float


def parse_occ_symbol(symbol: str) -> OccParts:
    symbol = symbol.strip().upper()
    if len(symbol) < 16:
        raise ValueError(f"not an OCC option symbol (too short): {symbol!r}")
    strike_part = symbol[-8:]
    right_ch = symbol[-9]
    date_part = symbol[-15:-9]
    root = symbol[:-15]
    if not (strike_part.isdigit() and date_part.isdigit() and right_ch in "CP" and root):
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    expiry = date(2000 + int(date_part[:2]), int(date_part[2:4]), int(date_part[4:6]))
    return OccParts(
        underlying=root,
        expiry=expiry,
        right="call" if right_ch == "C" else "put",
        strike=int(strike_part) / 1000.0,
    )
