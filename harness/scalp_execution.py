"""Order placement for the 0DTE ORB scalper. SEPARATE from the seller's
harness/execution.py. Every order carries the `oas-` client_order_id prefix
(scalp_registry.SCALP_ORDER_PREFIX) so it is attributable to the scalper broker-side
and the seller's sweep can skip it. Only the pure order primitive
(submit_single_leg_order) is shared with the seller — it has no position awareness,
so sharing it is safe.

Fill confirmation: after submit we poll get_order briefly. The runner NEVER marks a
position opened/closed on an unconfirmed order (the run_exits.py discipline).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from harness.scalp_registry import SCALP_ORDER_PREFIX

_POLL_TRIES = 5
_POLL_SLEEP_S = 1.0
_MIN_TICK = 0.01


@dataclass(frozen=True)
class ScalpFill:
    option_symbol: str
    qty: int
    fill_price: float   # per-share premium actually paid/received
    order_id: str


def _confirm_fill(client, order_id: str) -> tuple[float, float] | None:
    """Poll get_order until filled. Returns (filled_qty, filled_avg_price) or None if
    it never confirms a fill within the window (caller leaves it working / retries)."""
    for _ in range(_POLL_TRIES):
        info = client.get_order(order_id)
        status = info.get("status")
        fq = float(info.get("filled_qty") or 0)
        if status == "filled" and fq > 0:
            price = info.get("filled_avg_price")
            return fq, float(price) if price is not None else 0.0
        if status in ("canceled", "cancelled", "expired", "rejected", "done_for_day"):
            return None
        time.sleep(_POLL_SLEEP_S)
    return None


def submit_scalp_entry(client, *, contract, budget_usd: float, decision_id: str) -> ScalpFill | None:
    """Marketable-limit BUY of the chosen 0DTE ATM contract, sized to the fixed
    per-trade budget. Re-quotes first (don't trust a possibly-stale chain ask). Returns
    a confirmed ScalpFill, or None if: no valid quote, budget < 1 contract, or the order
    doesn't confirm a fill (then it's cancelled so nothing is left working)."""
    quotes = client.option_quotes([contract.symbol])
    q = quotes.get(contract.symbol) or {}
    ask = float(q.get("ask") or 0.0)
    if ask <= 0:
        ask = contract.ask  # fall back to the chain ask if the re-quote is empty
    if ask <= 0:
        return None
    qty = int(budget_usd / (ask * 100.0))
    if qty < 1:
        return None
    res = client.submit_single_leg_order(
        option_symbol=contract.symbol,
        side="buy",
        qty=qty,
        limit_price=round(ask, 2),
        decision_id=decision_id,
        prefix=SCALP_ORDER_PREFIX,
    )
    order_id = res["id"]
    confirmed = _confirm_fill(client, order_id)
    if confirmed is None:
        client.cancel_order(order_id)  # never leave a working entry we didn't confirm
        return None
    filled_qty, fill_price = confirmed
    return ScalpFill(
        option_symbol=contract.symbol,
        qty=int(filled_qty),
        fill_price=fill_price if fill_price > 0 else round(ask, 2),
        order_id=order_id,
    )


@dataclass(frozen=True)
class ScalpCloseResult:
    filled: bool
    exit_price: float | None
    order_id: str | None


def submit_scalp_close(
    client, *, option_symbol: str, qty: int, decision_id: str, aggressive: bool
) -> ScalpCloseResult:
    """SELL to close. Normal exit -> marketable limit at the current bid. A blown stop
    or the mandatory EOD flatten -> `aggressive=True` prices a deep marketable limit
    THROUGH the bid (bid*0.90, floored to a tick) so it behaves like a market order and
    we never let a 0DTE ride toward expiry. Returns filled + the exit fill price; an
    unconfirmed close is reported filled=False so the runner keeps the position IN_TRADE
    and retries next minute."""
    quotes = client.option_quotes([option_symbol])
    q = quotes.get(option_symbol) or {}
    bid = float(q.get("bid") or 0.0)
    if bid <= 0:
        # No two-sided quote — still must exit (esp. at EOD). Price at the tick floor.
        limit_price = _MIN_TICK
    elif aggressive:
        limit_price = max(_MIN_TICK, round(bid * 0.90, 2))
    else:
        limit_price = round(bid, 2)
    res = client.submit_single_leg_order(
        option_symbol=option_symbol,
        side="sell",
        qty=qty,
        limit_price=limit_price,
        decision_id=decision_id,
        prefix=SCALP_ORDER_PREFIX,
    )
    order_id = res["id"]
    confirmed = _confirm_fill(client, order_id)
    if confirmed is None:
        return ScalpCloseResult(filled=False, exit_price=None, order_id=order_id)
    _filled_qty, exit_price = confirmed
    return ScalpCloseResult(filled=True, exit_price=exit_price, order_id=order_id)
