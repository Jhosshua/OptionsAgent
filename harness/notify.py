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


def _bot_credentials() -> tuple[str, str] | None:
    """Bot-token transport, used when no webhook is configured.

    The fleet's other bots page through a Discord BOT (NOTIFY_DISCORD_TOKEN +
    NOTIFY_DISCORD_CHANNEL) rather than a webhook. Supporting both means this
    bot can alert using credentials that already exist, instead of being mute
    until someone creates a webhook — and mute is the failure that matters here,
    because the proposer FAILS CLOSED: no CLI, no trades, all day, quietly.
    """
    token = env("NOTIFY_DISCORD_TOKEN")
    channel = env("NOTIFY_DISCORD_CHANNEL")
    if token and channel:
        return token, channel
    return None


def post(message: str) -> bool:
    """Send to Discord via webhook if configured, else via the bot token.

    Fail-open in both directions: a broken transport logs and returns False, and
    never raises into a trading cycle.
    """
    url = _webhook_url()
    if url:
        try:
            resp = requests.post(url, json={"content": message}, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:  # fail-open — never let Discord break a cycle
            log.error("Discord webhook post failed: %s", e)
            return False

    creds = _bot_credentials()
    if creds:
        token, channel = creds
        try:
            resp = requests.post(
                f"https://discord.com/api/v10/channels/{channel}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": message},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:  # fail-open
            log.error("Discord bot post failed: %s", e)
            return False

    log.warning(
        "no Discord transport (set DISCORD_WEBHOOK_URL, or NOTIFY_DISCORD_TOKEN "
        "+ NOTIFY_DISCORD_CHANNEL) — skipping notification: %s", message
    )
    return False


def transport_status() -> str:
    """Which transport is live. Used at boot so a mute bot is visible on day one."""
    if _webhook_url():
        return "Discord (webhook)"
    if _bot_credentials():
        return "Discord (bot token)"
    return "NO DISCORD TRANSPORT — alerts are log-only"


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
