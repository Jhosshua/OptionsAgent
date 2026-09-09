"""Wingspan Discord Components V2 cards. Notification failures never stop trading."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests

from harness.env import env

log = logging.getLogger("wingspan.notify")
DEFAULT_DASHBOARD_URL = "https://optionsagent-production.up.railway.app"


def _webhook_url() -> str | None:
    return env("DISCORD_WEBHOOK_URL")


def _bot_credentials() -> tuple[str, str] | None:
    token, channel = env("NOTIFY_DISCORD_TOKEN"), env("NOTIFY_DISCORD_CHANNEL")
    return (token, channel) if token and channel else None


def dashboard_url() -> str:
    url = (env("OA_DASHBOARD_URL") or DEFAULT_DASHBOARD_URL).strip()
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname and not parsed.username else DEFAULT_DASHBOARD_URL


def card_payload(message: str) -> dict:
    """Exactly one container, with its dashboard button inside the card."""
    message = str(message).replace("OptionsAgent", "Wingspan")
    color = 0xD95846 if "⚠" in message or "error" in message.lower() else 0xD34836
    return {
        "flags": 1 << 15,
        "allowed_mentions": {"parse": []},
        "components": [{"type": 17, "accent_color": color, "components": [
            {"type": 10, "content": "## Wingspan\n-# Paper trading"},
            {"type": 14, "divider": True, "spacing": 1},
            {"type": 10, "content": message[:3500]},
            {"type": 1, "components": [{"type": 2, "style": 5,
                "label": "Open dashboard", "url": dashboard_url()}]},
        ]}],
    }


def post(message: str) -> bool:
    payload = card_payload(message)
    url = _webhook_url()
    kwargs = {"json": payload, "timeout": 10}
    if url:
        kwargs["params"] = {"with_components": "true", "wait": "true"}
    else:
        creds = _bot_credentials()
        if not creds:
            log.warning("no Discord transport — notification skipped")
            return False
        token, channel = creds
        url = f"https://discord.com/api/v10/channels/{channel}/messages"
        kwargs["headers"] = {"Authorization": f"Bot {token}"}
    try:
        resp = requests.post(url, **kwargs)
        resp.raise_for_status()
        return True
    except Exception as exc:
        # Exception text may contain a webhook URL (including its secret token).
        log.error("Discord card delivery failed (%s)", type(exc).__name__)
        return False


def transport_status() -> str:
    if _webhook_url():
        return "Discord (webhook)"
    if _bot_credentials():
        return "Discord (bot token)"
    return "NO DISCORD TRANSPORT — alerts are log-only"


def trade_opened(*, underlying: str, strategy_type: str, strike: float, dte: int,
                 credit_or_debit: float, thesis: str, contracts: int | None = None,
                 legs: list | None = None) -> None:
    detail = f"Strike **${strike:g}** · **{dte} days** to expiration"
    if legs:
        detail = " / ".join(f"${leg.strike:g}" for leg in legs) + f" {legs[0].right} spread · **{dte} days** to expiration"
    size = f"**{contracts} spreads** · " if contracts is not None and strategy_type == "credit_spread" else ""
    total = f" · **${abs(credit_or_debit) * 100 * contracts:,.2f} total**" if contracts else ""
    post(f"### {underlying} · Trade opened\n{size}{strategy_type.replace('_', ' ').title()}\n"
         f"{detail}\n{'Credit received' if credit_or_debit >= 0 else 'Debit paid'}: "
         f"**${abs(credit_or_debit):.2f} per share**{total}\n\n**Why this trade**\n{thesis}")


def trade_vetoed(*, underlying: str, strategy_type: str, reason: str) -> None:
    match = re.search(r"already at max_concurrent_positions \((\d+)\)", reason)
    if match:
        cap = int(match.group(1))
        reason = (f"All {cap} option-leg slots are in use. Each credit spread uses two slots "
                  f"({cap // 2} spreads at this limit). Waiting for an existing position to close.")
    post(f"### {underlying} · No new trade\n{reason}")


def trade_closed(*, underlying: str, strategy_type: str, reason: str,
                 pnl_usd: float | None, contracts: int | None = None,
                 remaining: int = 0, estimated: bool = False) -> None:
    status = "Partially closed" if remaining else "Trade closed"
    pnl = "Awaiting broker fill price" if pnl_usd is None else f"**{'+' if pnl_usd >= 0 else '-'}${abs(pnl_usd):,.2f}**"
    count = f"{contracts} spreads filled. " if contracts is not None else ""
    rest = f"{remaining} spreads remain open. " if remaining else ""
    post(f"### {underlying} · {status}\n{count}{rest}{strategy_type.replace('_', ' ').title()}\n"
         f"{'Estimated ' if estimated else ''}P&L before fees: {pnl}\n**Reason:** {reason}")


def exit_pending(*, underlying: str, contracts: int, limit_price: float, reason: str) -> None:
    post(f"### {underlying} · Profit-taking order working\n"
         f"Closing **{contracts} spreads** with a limit of **${limit_price:.2f} per share**.\n"
         "The broker has not filled the entire order yet. It stays active for the trading day; "
         "Wingspan tracks it and continues checking risk limits. P&L is reported after confirmed fills.")


def equity_update(message: str) -> None:
    message = message.replace("morning_fade", "morning reversal").replace("time_exit", "holding-time limit")
    message = message.replace("gap_follow", "gap continuation").replace("rule=", "Strategy: ")
    post("### Stock strategy\n" + message)


def error(message: str) -> None:
    post(f"### ⚠️ Attention needed\n{message}")
