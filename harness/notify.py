"""Discord notifications. Fail-open: a broken webhook must never crash a
trading cycle — log the error locally and move on. Mirrors the sibling bots'
notify.py posture (plain-language, no unexplained jargon, per operator
preference logged in cross-bot memory)."""

from __future__ import annotations

import logging

import requests

from harness.env import env

log = logging.getLogger("optionsagent.notify")


def _webhook_url() -> str | None:
    return env("DISCORD_WEBHOOK_URL")


def post(message: str) -> bool:
    url = _webhook_url()
    if not url:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping notification: %s", message)
        return False
    try:
        resp = requests.post(url, json={"content": message}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:  # fail-open — never let Discord break a trading cycle
        log.error("Discord post failed: %s", e)
        return False


def trade_opened(*, underlying: str, strategy_type: str, strike: float, dte: int, credit_or_debit: float, thesis: str) -> None:
    post(
        f"**Opened {strategy_type.replace('_', ' ')}** on {underlying}\n"
        f"Strike {strike}, {dte} days to expiration\n"
        f"{'Credit' if credit_or_debit >= 0 else 'Debit'}: ${abs(credit_or_debit):.2f}\n"
        f"Why: {thesis}"
    )


def trade_vetoed(*, underlying: str, strategy_type: str, reason: str) -> None:
    post(f"**Passed** on {underlying} ({strategy_type.replace('_', ' ')}): {reason}")


def trade_closed(*, underlying: str, strategy_type: str, reason: str, pnl_usd: float) -> None:
    sign = "+" if pnl_usd >= 0 else "-"
    post(
        f"**Closed {strategy_type.replace('_', ' ')}** on {underlying}\n"
        f"Reason: {reason}\n"
        f"P&L: {sign}${abs(pnl_usd):.2f}"
    )


def error(message: str) -> None:
    post(f":warning: **OptionsAgent error:** {message}")
