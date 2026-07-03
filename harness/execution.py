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

from harness.contracts import OptionQuote


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    reason: str
    orders: list[dict[str, Any]]


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
