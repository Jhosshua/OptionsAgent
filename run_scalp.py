"""0DTE Opening-Range-Breakout scalp loop — the fused entry-watch + exit-management
driver. Runs once per minute from cron/scalp.sh during RTH. FULLY ISOLATED from the
credit-spread seller (run_cycle.py / run_exits.py): own enable switch, own registry
(data/scalp_positions.jsonl), own decision log (data/scalp_decisions.jsonl), own
`oas-` order prefix, own ⚡ SCALP Discord prefix. Never reads or writes the seller's
files.

Off unless OA_SCALP_ENABLED=true. OA_SCALP_DRY_RUN=1 = log-only (compute range /
breakout / selection, place NO orders) — the Phase-3 shadow session before arming.

Cron fires this every minute 9-15 ET; a bash run-lock in scalp.sh prevents overlap,
and per-bar idempotency (last_evaluated_bar_ts) prevents double-acting on one candle.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from harness import decision_log, notify, scalp_registry, scalp_state
from harness.alpaca_glue import make_client
from harness.contracts import select_0dte_atm
from harness.env import config
from harness.risk_rails import (
    active_scalp_rails,
    scalp_daily_loss_ok,
    scalp_entry_window_ok,
    scalp_must_flatten,
    scalp_one_at_a_time_ok,
    scalp_per_trade_budget_ok,
    scalp_trade_count_ok,
)
from harness.scalp_execution import submit_scalp_close, submit_scalp_entry
from harness.scalp_exits import ScalpExitRules, evaluate_scalp_exit
from harness.signals_intraday import breakout_check, opening_range, session_vwap
from harness.scalp_registry import ScalpPosition

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_scalp")

ET = ZoneInfo("America/New_York")
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SCALP_DECISIONS_PATH = os.path.join(_DATA_DIR, "scalp_decisions.jsonl")


def _enabled() -> bool:
    return (os.environ.get("OA_SCALP_ENABLED", "") or "").lower() == "true"


def _dry_run() -> bool:
    return (os.environ.get("OA_SCALP_DRY_RUN", "") or "").lower() in ("1", "true", "yes")


def _post(msg: str) -> None:
    tag = "⚡ SCALP" + (" [dry]" if _dry_run() else "")
    notify.post(f"{tag} {msg}")


def _log(record: dict) -> None:
    decision_log.record(record, path=SCALP_DECISIONS_PATH)


def _minutes_between(iso_a: str, dt_b: datetime) -> float:
    try:
        a = datetime.fromisoformat(iso_a)
    except Exception:
        return 0.0
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    return max(0.0, (dt_b - a).total_seconds() / 60.0)


def _manage_open(client, u, blk, *, now_utc, now_hhmm, rails, exit_rules, state, dry) -> None:
    """Exit path for an underlying that holds a scalp. Runs every minute."""
    pos = blk["position"]
    sym = pos["option_symbol"]
    quotes = client.option_quotes([sym])
    live_syms = {p["symbol"] for p in client.list_positions()}
    # Vanished-position guard: broker no longer holds it (expired / exercised /
    # closed outside the loop) -> record closed, don't retry forever.
    if sym not in live_syms:
        scalp_registry.record_closed(pos["scalp_id"], reason="vanished", exit_price=None, pnl_usd=None)
        _post(f"{u} scalp position vanished from broker ({sym}) — cleared, review.")
        _log({"kind": "scalp_close", "underlying": u, "reason": "vanished", "symbol": sym, "ts": decision_log.now_iso()})
        blk["position"] = None
        blk["state"] = "WATCHING_FOR_BREAK"
        return

    bid = float((quotes.get(sym) or {}).get("bid") or 0.0)
    entry_price = float(pos["entry_fill_price"])
    minutes_held = _minutes_between(pos["entry_ts"], now_utc)
    must_flat = scalp_must_flatten(now_hhmm, rails)
    # A zero/empty bid may be a transient quote gap, not a truly worthless option.
    # Don't dump the position at the tick floor on a phantom 0 bid — wait for a real
    # quote next minute. EXCEPT at the mandatory EOD flatten, where we must exit
    # regardless (0DTE auto-exercise guard trumps price).
    if bid <= 0 and not must_flat:
        return
    decision = evaluate_scalp_exit(
        entry_price=entry_price, current_bid=bid, minutes_held=minutes_held,
        must_flatten=must_flat, rules=exit_rules,
    )
    if not decision.should_close:
        return

    if dry:
        _post(f"{u} WOULD CLOSE {sym} ({decision.reason}) bid={bid:.2f} entry={entry_price:.2f}")
        return

    aggressive = decision.reason in ("eod_flatten", "stop_loss")
    res = submit_scalp_close(
        client, option_symbol=sym, qty=int(pos["qty"]),
        decision_id=pos["scalp_id"], aggressive=aggressive,
    )
    if not res.filled:
        _post(f"{u} close NOT confirmed for {sym} ({decision.reason}) — retrying next minute.")
        return
    exit_price = float(res.exit_price or 0.0)
    pnl = (exit_price - entry_price) * 100.0 * int(pos["qty"])
    state["realized_pnl_usd"] = float(state.get("realized_pnl_usd", 0.0)) + pnl
    scalp_registry.record_closed(pos["scalp_id"], reason=decision.reason, exit_price=exit_price, pnl_usd=pnl)
    _log({
        "kind": "scalp_close", "underlying": u, "reason": decision.reason, "symbol": sym,
        "entry_price": entry_price, "exit_price": exit_price, "qty": int(pos["qty"]),
        "pnl_usd": round(pnl, 2), "ts": decision_log.now_iso(),
    })
    sign = "+" if pnl >= 0 else "-"
    _post(f"Closed {u} {pos['right']} {sym} ({decision.reason}) P&L {sign}${abs(pnl):.2f}")
    blk["position"] = None
    # Daily-loss halt check after realizing the loss.
    ok, reason = scalp_daily_loss_ok(state["realized_pnl_usd"], rails)
    if not ok:
        state["halted"] = True
        state["halt_reason"] = reason
        blk["state"] = "DONE"
        _post(f"HALTED for the day: {reason}")
    else:
        blk["state"] = "WATCHING_FOR_BREAK"


def _try_entry(client, u, blk, bars, *, et_date, now_hhmm, now_utc, cfg_scalp, rails, state, dry) -> None:
    """Entry path: set the opening range, watch for a confirmed breakout, and open a
    0DTE ATM scalp if all rails pass."""
    minutes = int(cfg_scalp.get("range_minutes", 3))
    # Freeze the opening range ONCE (09:30-09:33 never changes) and reuse it from
    # state. This is why afternoon breakouts still fire after those bars age out of
    # the fetch window, and why a mid-session redeploy keeps the range (the state
    # file persists on the Railway volume).
    if blk.get("range_high") is None or blk.get("range_low") is None:
        rng = opening_range(bars, et_date, minutes=minutes)
        if rng is None:
            blk["state"] = "WAITING_FOR_RANGE"
            return
        blk["range_high"] = rng.high
        blk["range_low"] = rng.low
        blk["state"] = "WATCHING_FOR_BREAK"
    range_high = float(blk["range_high"])
    range_low = float(blk["range_low"])

    # Entry-gate: halted / trade count / entry window / one-at-a-time.
    if state.get("halted"):
        return
    ok, _ = scalp_trade_count_ok(int(state.get("trades_today", 0)), rails)
    if not ok:
        blk["state"] = "DONE"
        return
    ok, _ = scalp_entry_window_ok(now_hhmm, rails)
    if not ok:
        return
    ok, _ = scalp_one_at_a_time_ok(scalp_state.open_scalp_count(state), rails)
    if not ok:
        return

    bo = breakout_check(
        bars, et_date, range_high=range_high, range_low=range_low,
        rvol_min=float(cfg_scalp.get("rvol_min", 1.5)),
    )
    if bo is None:
        return
    # Once-per-bar idempotency.
    if blk.get("last_evaluated_bar_ts") == bo.bar_ts_utc:
        return
    blk["last_evaluated_bar_ts"] = bo.bar_ts_utc

    right = "call" if bo.direction == "up" else "put"
    spot = client.stock_latest_price(u, feed=cfg_scalp.get("data_feed", "sip")) or bo.close
    rows = client.option_chain_0dte(u, right=right, spot=spot)
    contract = select_0dte_atm(
        rows, spot=spot, right=right, max_spread_pct=float(cfg_scalp.get("max_spread_pct", 0.15)),
    )
    if contract is None:
        _log({"kind": "scalp_skip", "underlying": u, "reason": "no_0dte_contract",
              "direction": bo.direction, "spot": spot, "ts": decision_log.now_iso()})
        return

    budget = float(cfg_scalp.get("per_trade_usd", 250))
    ok, reason = scalp_per_trade_budget_ok(budget, rails)
    if not ok:
        _log({"kind": "scalp_skip", "underlying": u, "reason": f"budget:{reason}", "ts": decision_log.now_iso()})
        return

    vwap = session_vwap(bars, et_date)
    if dry:
        _post(f"{u} WOULD BUY {right} {contract.symbol} @~{contract.ask:.2f} "
              f"(break {bo.direction}, rvol {bo.rvol}, spot {spot:.2f}, vwap {vwap})")
        _log({"kind": "scalp_would_enter", "underlying": u, "symbol": contract.symbol, "right": right,
              "direction": bo.direction, "ask": contract.ask, "spot": spot, "rvol": bo.rvol,
              "ts": decision_log.now_iso()})
        return

    decision_id = decision_log.new_decision_id()
    fill = submit_scalp_entry(client, contract=contract, budget_usd=budget, decision_id=decision_id)
    if fill is None:
        _log({"kind": "scalp_skip", "underlying": u, "reason": "no_fill_or_below_one_contract",
              "symbol": contract.symbol, "ts": decision_log.now_iso()})
        return

    scalp_registry.record_opened(ScalpPosition(
        scalp_id=decision_id, underlying=u, option_symbol=fill.option_symbol, right=right,
        direction=bo.direction, qty=fill.qty, entry_price=fill.fill_price,
        opened_ts=decision_log.now_iso(), entry_order_id=fill.order_id,
    ))
    blk["position"] = {
        "scalp_id": decision_id, "option_symbol": fill.option_symbol, "right": right,
        "direction": bo.direction, "qty": fill.qty, "entry_fill_price": fill.fill_price,
        "entry_ts": now_utc.isoformat(), "entry_order_id": fill.order_id,
    }
    blk["state"] = "IN_TRADE"
    state["trades_today"] = int(state.get("trades_today", 0)) + 1
    _log({"kind": "scalp_open", "underlying": u, "symbol": fill.option_symbol, "right": right,
          "direction": bo.direction, "qty": fill.qty, "entry_price": fill.fill_price,
          "rvol": bo.rvol, "spot": spot, "decision_id": decision_id, "ts": decision_log.now_iso()})
    _post(f"BUY {u} {right} {fill.option_symbol} x{fill.qty} @ {fill.fill_price:.2f} "
          f"(break {bo.direction}, rvol {bo.rvol})")


def run() -> None:
    if not _enabled():
        log.info("OA_SCALP_ENABLED not true — scalper inert.")
        return
    cfg_scalp = config().get("scalp", {})
    underlyings = list(cfg_scalp.get("underlyings", ["SPY", "QQQ"]))
    rails = active_scalp_rails()
    exit_rules = ScalpExitRules(
        stop_loss_pct=float(cfg_scalp.get("stop_loss_pct", 0.30)),
        profit_target_pct=float(cfg_scalp.get("profit_target_pct", 0.50)),
        theta_cut_minutes=int(cfg_scalp.get("theta_cut_minutes", 15)),
    )
    dry = _dry_run()

    client = make_client()
    if not client.market_is_open():
        log.info("market closed — scalper idle.")
        return

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    et_date = now_et.strftime("%Y-%m-%d")
    now_hhmm = now_et.strftime("%H:%M")

    state = scalp_state.load_state(et_date, underlyings)
    feed = cfg_scalp.get("data_feed", "sip")

    for u in underlyings:
        blk = state["underlyings"][u]
        try:
            # Full-session lookback so the 09:30-09:33 opening-range bars are always
            # present (420 min covers 09:00-16:00 ET); also makes the RVOL baseline a
            # true session average, matching the config comment.
            bars = client.stock_minute_bars(u, lookback_minutes=420, feed=feed)
            if not bars:
                continue  # fail open: no data this minute -> do nothing for u
            if blk.get("position"):
                _manage_open(client, u, blk, now_utc=now_utc, now_hhmm=now_hhmm,
                             rails=rails, exit_rules=exit_rules, state=state, dry=dry)
            else:
                _try_entry(client, u, blk, bars, et_date=et_date, now_hhmm=now_hhmm,
                           now_utc=now_utc, cfg_scalp=cfg_scalp, rails=rails, state=state, dry=dry)
        except Exception:
            log.exception("scalp step failed for %s (continuing)", u)

    scalp_state.save_state(state)
    log.info("scalp tick complete et=%s %s dry=%s halted=%s trades=%s pnl=%.2f",
             et_date, now_hhmm, dry, state.get("halted"), state.get("trades_today"),
             float(state.get("realized_pnl_usd", 0.0)))


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.exception("run_scalp crashed")
        try:
            notify.error(f"run_scalp crashed: {e}")
        except Exception:
            pass
        raise
