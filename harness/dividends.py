"""Upcoming-dividend lookup for the dividend-assignment exit check.

yfinance-based, FAIL-OPEN: if yfinance is missing, errors, or has no data,
returns None and the dividend check simply doesn't fire (documented posture —
same as the sibling bots' fail-open data adapters). The check this feeds is
a pre-emptive safety close, so a missing feed degrades to "no early warning",
never to a crash or a phantom signal.
"""

from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger("optionsagent.dividends")


def upcoming_dividend(symbol: str) -> tuple[date, float] | None:
    """Returns (ex_dividend_date, amount_per_share) if one is known and in
    the future, else None."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed — dividend-assignment check disabled")
        return None
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar or {}
        ex_date = cal.get("Ex-Dividend Date")
        if ex_date is None:
            return None
        if hasattr(ex_date, "date"):
            ex_date = ex_date.date()
        if not isinstance(ex_date, date) or ex_date < date.today():
            return None
        info = ticker.info or {}
        amount = info.get("dividendRate")
        if amount:
            amount = float(amount) / 4  # dividendRate is annualized; approximate quarterly
        else:
            divs = ticker.dividends
            amount = float(divs.iloc[-1]) if divs is not None and len(divs) else None
        if not amount:
            return None
        return ex_date, amount
    except Exception as e:
        log.warning("dividend lookup failed for %s (fail-open): %s", symbol, e)
        return None
