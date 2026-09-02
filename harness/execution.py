"""Turns an approved (contract, size) into actual Alpaca order(s).

CSP: a single order, cash-secured, Alpaca enforces the buying-power gate.

Covered call: Alpaca disallows an equity leg inside an order with an option
leg (RESEARCH.md Pass 1), so this is two separate orders — buy the shares,
CONFIRM the fill, then sell the call. The confirm step is not optional: if
the share order fails or only partially fills, the call leg must never be
submitted, or the bot ends up with an accidental naked call.

Status-string contract: this module compares against plain lowercase values
("filled", "canceled", ...) — alpaca_glue._status_str() normalizes the
alpaca-py enums (str(OrderStatus.FILLED) == 'OrderStatus.FILLED', .value ==
'filled') at the source, so every status that reaches here is already plain.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from harness.contracts import OptionQuote, SpreadLegs, StraddleLegs


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    reason: str
    orders: list[dict[str, Any]]


TERMINAL_STATUSES = ("filled", "canceled", "cancelled", "expired", "rejected", "done_for_day")


def confirm_fill(
    client, order_id: str, *, requested: int, tries: int = 15, sleep_s: float = 2.0,
    cancel_unfilled: bool = True,
) -> dict[str, Any]:
    """Poll one order until it is filled or the window ends; if it is still
    working, cancel the remainder so nothing untracked can fill later, then
    read the final filled quantity once more.

    Returns {"order_id", "status", "filled_qty", "filled_avg_price", "requested",
    "cancelled_remainder"}. filled_qty is the number of contracts (spreads for
    an mleg order) that actually filled; 0 means nothing did. A structure must
    be recorded with THIS count, never the requested one (2026-09-01 review:
    partial fills were booked as full and exits then tried to close contracts
    that were never opened)."""
    info: dict[str, Any] = {}
    for _ in range(max(1, tries)):
        info = client.get_order(order_id)
        status = str(info.get("status") or "").lower()
        fq = int(float(info.get("filled_qty") or 0))
        if status == "filled" or fq >= requested:
            return {
                "order_id": order_id, "status": status or "filled", "filled_qty": min(fq, requested),
                "filled_avg_price": info.get("filled_avg_price"), "requested": requested,
                "cancelled_remainder": False,
            }
        if status in TERMINAL_STATUSES:
            return {
                "order_id": order_id, "status": status, "filled_qty": fq,
                "filled_avg_price": info.get("filled_avg_price"), "requested": requested,
                "cancelled_remainder": False,
            }
        time.sleep(sleep_s)
    cancelled = False
    if cancel_unfilled:
        client.cancel_order(order_id)
        cancelled = True
        time.sleep(min(sleep_s, 1.0))
        info = client.get_order(order_id)
    fq = int(float(info.get("filled_qty") or 0))
    return {
        "order_id": order_id, "status": str(info.get("status") or "").lower(), "filled_qty": fq,
        "filled_avg_price": info.get("filled_avg_price"), "requested": requested,
        "cancelled_remainder": cancelled,
    }


def execute_csp(client, *, quote: OptionQuote, contracts: int, decision_id: str) -> ExecutionResult:
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    order = client.submit_single_leg_order(
        option_symbol=quote.symbol,
        side="sell",
        qty=contracts,
        limit_price=quote.bid,  # sell at bid: get filled, don't chase the ask
        decision_id=decision_id,
    )
    return ExecutionResult(True, "csp order submitted", [order])


def execute_credit_spread(
    client, *, legs: SpreadLegs, contracts: int, decision_id: str
) -> ExecutionResult:
    """Single mleg order — sell short leg, buy long leg. Net-credit limit
    price is NEGATIVE per Alpaca's mleg convention."""
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    order = client.submit_mleg_order(
        legs=[
            {"symbol": legs.short.symbol, "side": "sell", "ratio_qty": 1},
            {"symbol": legs.long.symbol, "side": "buy", "ratio_qty": 1},
        ],
        qty=contracts,
        limit_price=-legs.net_credit,  # negative = net credit
        decision_id=decision_id,
    )
    return ExecutionResult(True, "credit spread mleg submitted", [order])


def execute_debit_spread(
    client, *, legs: SpreadLegs, contracts: int, decision_id: str
) -> ExecutionResult:
    """Single mleg order — buy long leg, sell short leg. Net-debit limit is
    positive."""
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    net_debit = legs.long.ask - legs.short.bid
    if net_debit <= 0:
        return ExecutionResult(False, f"debit spread has non-positive net debit {net_debit}", [])
    order = client.submit_mleg_order(
        legs=[
            {"symbol": legs.long.symbol, "side": "buy", "ratio_qty": 1},
            {"symbol": legs.short.symbol, "side": "sell", "ratio_qty": 1},
        ],
        qty=contracts,
        limit_price=net_debit,
        decision_id=decision_id,
    )
    return ExecutionResult(True, "debit spread mleg submitted", [order])


def execute_long_option(
    client, *, quote: OptionQuote, contracts: int, decision_id: str
) -> ExecutionResult:
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    order = client.submit_single_leg_order(
        option_symbol=quote.symbol,
        side="buy",
        qty=contracts,
        limit_price=quote.ask,  # buy at ask: get filled
        decision_id=decision_id,
    )
    return ExecutionResult(True, "long option submitted", [order])


def execute_long_straddle(
    client, *, legs: StraddleLegs, contracts: int, decision_id: str
) -> ExecutionResult:
    """Both legs LONG -> allowed in one mleg order (no short leg to cover)."""
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    order = client.submit_mleg_order(
        legs=[
            {"symbol": legs.call.symbol, "side": "buy", "ratio_qty": 1},
            {"symbol": legs.put.symbol, "side": "buy", "ratio_qty": 1},
        ],
        qty=contracts,
        limit_price=legs.total_debit,
        decision_id=decision_id,
    )
    return ExecutionResult(True, "long straddle mleg submitted", [order])


def execute_covered_straddle(
    client, *, legs: StraddleLegs, contracts: int, decision_id: str
) -> ExecutionResult:
    """Covered straddle = short ATM call (covered by ALREADY-OWNED shares,
    verified by the caller) + short ATM put (cash-secured; the rails already
    required full cash backing). CANNOT be one mleg order: Alpaca requires
    every short leg in an mleg order to be covered WITHIN that order, and
    the covering shares can't be a leg — so this is two sequential
    single-leg orders. If the second leg fails, the first is reported so the
    caller/exit-sweep sees a partial structure rather than silence."""
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    call_order = client.submit_single_leg_order(
        option_symbol=legs.call.symbol,
        side="sell",
        qty=contracts,
        limit_price=legs.call.bid,
        decision_id=decision_id,
    )
    try:
        put_order = client.submit_single_leg_order(
            option_symbol=legs.put.symbol,
            side="sell",
            qty=contracts,
            limit_price=legs.put.bid,
            decision_id=decision_id,
        )
    except Exception as e:
        return ExecutionResult(
            False,
            f"covered straddle PARTIAL: call leg submitted but put leg failed ({e}) — "
            f"structure is incomplete, manual attention or next sweep must reconcile",
            [call_order],
        )
    return ExecutionResult(True, "covered straddle submitted (2 legs)", [call_order, put_order])


def execute_covered_call_on_owned_shares(
    client, *, quote: OptionQuote, contracts: int, decision_id: str
) -> ExecutionResult:
    """Sells calls against shares the account ALREADY owns — the caller is
    responsible for having verified ownership of contracts*100 shares (the
    wheel's normal covered-call path: shares came from a CSP assignment).
    For a from-scratch buy-write, use execute_covered_call instead."""
    if contracts <= 0:
        return ExecutionResult(False, "contracts must be > 0", [])
    order = client.submit_single_leg_order(
        option_symbol=quote.symbol,
        side="sell",
        qty=contracts,
        limit_price=quote.bid,
        decision_id=decision_id,
    )
    return ExecutionResult(True, "covered call (owned shares) submitted", [order])


def execute_covered_call(
    client,
    *,
    underlying: str,
    shares_needed: int,
    quote: OptionQuote,
    contracts: int,
    decision_id: str,
    poll_interval_secs: float = 2.0,
    poll_timeout_secs: float = 60.0,
) -> ExecutionResult:
    """Two-order sequence with an explicit fill check between them. Never
    submits the call leg unless the share order confirms FILLED for the full
    requested quantity."""
    if shares_needed <= 0 or contracts <= 0:
        return ExecutionResult(False, "shares_needed and contracts must be > 0", [])
    if shares_needed != contracts * 100:
        return ExecutionResult(
            False,
            f"shares_needed ({shares_needed}) must equal contracts*100 ({contracts * 100})",
            [],
        )

    share_order = client.submit_equity_order(
        symbol=underlying, side="buy", qty=shares_needed, decision_id=decision_id
    )

    deadline = time.monotonic() + poll_timeout_secs
    filled = False
    last_status = share_order.get("status")
    while time.monotonic() < deadline:
        status = client.get_order(share_order["id"])
        last_status = status["status"]
        if last_status == "filled" and status["filled_qty"] >= shares_needed:
            filled = True
            break
        if last_status in ("canceled", "expired", "rejected"):
            break
        time.sleep(poll_interval_secs)

    if not filled:
        return ExecutionResult(
            False,
            f"share order did not confirm filled before submitting the call leg "
            f"(last status: {last_status}) — call leg NOT submitted to avoid an orphaned naked call",
            [share_order],
        )

    call_order = client.submit_single_leg_order(
        option_symbol=quote.symbol,
        side="sell",
        qty=contracts,
        limit_price=quote.bid,
        decision_id=decision_id,
    )
    return ExecutionResult(True, "covered call sequence complete", [share_order, call_order])
