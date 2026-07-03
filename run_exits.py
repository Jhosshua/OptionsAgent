"""Exit sweep. Run every 20 min during market hours (cron). LLM-free —
pure deterministic monitoring of open structures against exits.py's checks.

Flow: load open structures (data/structures.jsonl) -> reconcile against live
broker positions (vanished legs = assignment/expiry/manual close -> alert +
close event, never silent) -> fetch quotes -> compute net cost-to-close /
current value per structure -> evaluate the family's exit rules -> close via
the matching order shape -> log + Discord with estimated P&L.
"""

from __future__ import annotations

import logging
from datetime import date

from harness import decision_log, notify, structures
from harness.alpaca_glue import make_client
from harness.dividends import upcoming_dividend
from harness.env import config
from harness.exits import (
    HAS_SHORT_CALL,
    LONG_TYPES,
    ExitRules,
    OpenPosition,
    evaluate_exit,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_exits")


def _rules_for(strategy_type: str, cfg: dict) -> ExitRules:
    if strategy_type in ("csp", "covered_call"):
        w = cfg["wheel"]
        return ExitRules(dte_close=w["dte_close"], profit_target_pct=w["profit_target_pct"], stop_loss_pct=None)
    if strategy_type == "credit_spread":
        s = cfg["spreads"]
        return ExitRules(dte_close=s["dte_close"], profit_target_pct=s["profit_target_pct"], stop_loss_pct=s["stop_loss_pct"])
    if strategy_type == "debit_spread":
        s = cfg["spreads"]
        lo = cfg["long_options"]
        return ExitRules(dte_close=s["dte_close"], profit_target_pct=lo["profit_target_pct"], stop_loss_pct=lo["stop_loss_pct"])
    if strategy_type in ("long_call", "long_put"):
        lo = cfg["long_options"]
        return ExitRules(dte_close=lo["dte_close"], profit_target_pct=lo["profit_target_pct"], stop_loss_pct=lo["stop_loss_pct"])
    if strategy_type == "long_straddle":
        st = cfg["straddles"]
        return ExitRules(dte_close=st["dte_close"], profit_target_pct=st["long_profit_target_pct"], stop_loss_pct=st["long_stop_loss_pct"])
    if strategy_type == "covered_straddle":
        st = cfg["straddles"]
        return ExitRules(dte_close=st["dte_close"], profit_target_pct=st["covered_profit_target_pct"], stop_loss_pct=None)
    raise ValueError(f"no exit rules for strategy_type {strategy_type!r}")


def _net_close_price(structure: structures.Structure, quotes: dict) -> float | None:
    """Per-share net price to unwind the structure now. Short legs are bought
    back at ask; long legs are sold at bid. Returns None if any leg has no
    usable quote (skip this sweep pass rather than act on garbage)."""
    net = 0.0
    for leg in structure.legs:
        q = quotes.get(leg.symbol)
        if q is None:
            return None
        if leg.side == "short":
            if q["ask"] <= 0:
                return None
            net += q["ask"]
        else:
            net -= q["bid"]  # bid may legitimately be 0 for a worthless long leg
    return net


def _min_dte(structure: structures.Structure) -> int:
    return min((date.fromisoformat(leg.expiry) - date.today()).days for leg in structure.legs)


def _put_symbol_for_call(call_symbol: str) -> str:
    """Same-strike same-expiry put for a short call's dividend check —
    OCC format makes this a single char swap."""
    return call_symbol[:-9] + "P" + call_symbol[-8:]


def _close_structure(client, structure: structures.Structure, quotes: dict, decision_id: str) -> list[dict]:
    """Submits the unwind order(s). Short legs buy-to-close at ask, long legs
    sell-to-close at bid; multi-leg structures unwind in ONE mleg order
    (except covered straddle, whose legs were opened separately too)."""
    legs = structure.legs
    if len(legs) == 1:
        leg = legs[0]
        q = quotes[leg.symbol]
        side = "buy" if leg.side == "short" else "sell"
        price = q["ask"] if leg.side == "short" else q["bid"]
        order = client.submit_single_leg_order(
            option_symbol=leg.symbol, side=side, qty=structure.contracts,
            limit_price=price, decision_id=decision_id,
        )
        return [order]

    if structure.strategy_type == "covered_straddle":
        orders = []
        for leg in legs:  # both short: two buy-to-close orders
            q = quotes[leg.symbol]
            orders.append(
                client.submit_single_leg_order(
                    option_symbol=leg.symbol, side="buy", qty=structure.contracts,
                    limit_price=q["ask"], decision_id=decision_id,
                )
            )
        return orders

    mleg = []
    net = 0.0
    for leg in legs:
        q = quotes[leg.symbol]
        if leg.side == "short":
            mleg.append({"symbol": leg.symbol, "side": "buy", "ratio_qty": 1})
            net += q["ask"]
        else:
            mleg.append({"symbol": leg.symbol, "side": "sell", "ratio_qty": 1})
            net -= q["bid"]
    # positive net = we pay a debit to unwind; negative = we collect credit
    order = client.submit_mleg_order(
        legs=mleg, qty=structure.contracts, limit_price=net, decision_id=decision_id
    )
    return [order]


def run() -> None:
    cfg = config()
    client = make_client()

    open_structures = structures.load_open()
    if not open_structures:
        log.info("no open structures — nothing to sweep")
        return

    positions_raw = client.list_positions()
    live_option_symbols = {
        p["symbol"] for p in positions_raw if p["asset_class"].lower() in ("us_option", "option")
    }
    intact, vanished = structures.reconcile(open_structures, live_option_symbols)

    for s in vanished:
        # assignment / expiry / manual close happened outside the bot — this
        # must be an ALERT, not a silent drop (RESEARCH.md: OCC assignment is
        # random and can land overnight)
        structures.record_closed(s.structure_id, reason="legs_vanished_assignment_or_manual", pnl_usd=None)
        notify.error(
            f"{s.underlying} {s.strategy_type}: leg(s) no longer in the account "
            f"(assignment, expiry, or manual close). Marked closed; check the account."
        )
        decision_log.record(
            {"kind": "exit", "ts": decision_log.now_iso(), "structure_id": s.structure_id,
             "underlying": s.underlying, "strategy_type": s.strategy_type,
             "reason": "legs_vanished_assignment_or_manual"}
        )

    if not intact:
        return

    all_symbols = [leg.symbol for s in intact for leg in s.legs]
    quotes = client.option_quotes(all_symbols)

    for s in intact:
        net = _net_close_price(s, quotes)
        if net is None:
            log.warning("%s %s: missing/garbage quote on a leg — skipping this sweep", s.underlying, s.strategy_type)
            continue
        is_long = s.strategy_type in LONG_TYPES
        dte = _min_dte(s)

        dividend_amount = None
        same_strike_put_price = None
        ex_div_within = False
        if s.strategy_type in HAS_SHORT_CALL:
            div = upcoming_dividend(s.underlying)
            if div is not None:
                ex_date, dividend_amount = div
                ex_div_within = (ex_date - date.today()).days <= dte
                call_leg = next(leg for leg in s.legs if leg.right == "call" and leg.side == "short")
                put_quote = client.option_quotes([_put_symbol_for_call(call_leg.symbol)])
                pq = next(iter(put_quote.values()), None)
                if pq is not None:
                    same_strike_put_price = pq["ask"]

        position = OpenPosition(
            underlying=s.underlying,
            strategy_type=s.strategy_type,
            strike=s.legs[0].strike,
            dte=dte,
            entry_credit=0.0 if is_long else s.entry_net,
            cost_to_close=0.0 if is_long else net,
            entry_debit=s.entry_net if is_long else 0.0,
            current_value=(-net) if is_long else 0.0,  # unwinding a long structure COLLECTS -net
            same_strike_opposite_price=same_strike_put_price,
            dividend_amount=dividend_amount,
            is_ex_dividend_within_dte=ex_div_within,
        )
        decision = evaluate_exit(position, _rules_for(s.strategy_type, cfg))
        if not decision.should_close:
            continue

        decision_id = decision_log.new_decision_id()
        orders = _close_structure(client, s, quotes, decision_id)
        if is_long:
            pnl_usd = ((-net) - s.entry_net) * 100 * s.contracts
        else:
            pnl_usd = (s.entry_net - net) * 100 * s.contracts
        structures.record_closed(s.structure_id, reason=decision.reason, pnl_usd=pnl_usd)
        decision_log.record(
            {"kind": "exit", "ts": decision_log.now_iso(), "structure_id": s.structure_id,
             "decision_id": decision_id, "underlying": s.underlying,
             "strategy_type": s.strategy_type, "reason": decision.reason,
             "estimated_pnl_usd": pnl_usd, "orders": orders}
        )
        notify.trade_closed(
            underlying=s.underlying, strategy_type=s.strategy_type,
            reason=decision.reason, pnl_usd=pnl_usd,
        )
        log.info("closed %s %s: %s (est P&L $%.2f)", s.underlying, s.strategy_type, decision.reason, pnl_usd)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.exception("exit sweep failed")
        notify.error(f"run_exits crashed: {e}")
        raise
