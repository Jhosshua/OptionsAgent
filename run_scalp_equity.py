"""Equity intraday scalper driver — the two rules mined 2026-08-28 (see
harness/risk_rails.py EquityScalpRails). Runs once per minute from
cron/equity_scalp.sh during RTH. Fully isolated: own state file
(data/equity_scalp_state/<date>.json), own decision log
(data/equity_scalp_decisions.jsonl), order prefix oae-. No LLM anywhere.

Rules (one slot each per day: one morning fade across SPY/QQQ, one QQQ gap
follow, so the 2-trade daily cap always reserves the gap-follow slot):
  morning_fade — at the 10:15 window, first eligible bar: beyond BOTH vwap and
    the 15m opening range -> fade. Exits: 0.7% stop on INTRABAR adverse
    extremes, 120-minute time exit, mandatory 15:50 ET flatten.
  gap_follow — QQQ at the 13:00 window when |gap| > 0.8%: hold with the gap.

Fail-closed: if the broker position reconciliation fails, no new entries that
tick. Orphaned broker positions (crash between fill and state save) are adopted
and managed; the 15:50 flatten closes them regardless.

Off unless OA_EQUITY_SCALP_ENABLED=true.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from harness import alpaca_cli, decision_log, notify
from harness.alpaca_glue import make_client
from harness.env import config
from harness.equity_scalp import (
    evaluate_equity_exit,
    gap_follow_signal,
    morning_fade_signal,
    orphan_equity_positions,
    session_bars,
)
from harness.risk_rails import active_equity_scalp_rails
from harness.scalp_execution import _confirm_fill

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_scalp_equity")

ET = ZoneInfo("America/New_York")
EQ_PREFIX = "oae-"
STATE_DIR = os.path.join(os.path.dirname(__file__), "data", "equity_scalp_state")
DECISIONS_PATH = os.path.join(os.path.dirname(__file__), "data", "equity_scalp_decisions.jsonl")


def _enabled() -> bool:
    return (os.environ.get("OA_EQUITY_SCALP_ENABLED", "") or "").lower() == "true"


def _dry() -> bool:
    return (os.environ.get("OA_EQUITY_SCALP_DRY_RUN", "") or "").lower() in ("1", "true", "yes")


def _today_et() -> str:
    return datetime.now(timezone.utc).astimezone(ET).strftime("%Y-%m-%d")


def _load_state(et_date: str) -> dict:
    path = os.path.join(STATE_DIR, f"{et_date}.json")
    if os.path.exists(path):
        import json
        return json.load(open(path))
    return {"date": et_date, "trades_today": 0, "realized_pnl_usd": 0.0,
            "halted": False, "halt_reason": None, "rules_taken_day": [],
            "symbols": {}}


def _save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    import json
    path = os.path.join(STATE_DIR, f"{state['date']}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


def _log(record: dict) -> None:
    decision_log.record(record, path=DECISIONS_PATH)


def _post(msg: str) -> None:
    notify.post(f"◆ EQ-SCALP {msg}")


def _submit_market(client, *, symbol: str, side: str, qty: int, decision_id: str,
                   allow_sdk_fallback: bool = False):
    """Market DAY order through the shared broker adapter (the Alpaca CLI when
    OA_BROKER_TRANSPORT=cli). ENTRIES fail closed: a broken CLI costs at most a
    missed $20k share entry. EXITS (flatten) may fall back to the SDK, loudly
    journaled, because an open position with a broken CLI at 15:50 ET is
    worse than a fallback (2026-09-01 review)."""
    try:
        return client.submit_equity_order(
            symbol=symbol, side=side, qty=qty, decision_id=decision_id, prefix=EQ_PREFIX,
        )
    except alpaca_cli.CliError as e:
        if not allow_sdk_fallback:
            raise
        _post(f"⚠ CLI order path failed ({str(e)[:120]}); SDK FALLBACK for exit {side} {symbol} x{qty}")
        _log({"kind": "eq_cli_fallback", "symbol": symbol, "side": side, "qty": qty,
              "error": str(e)[:300], "ts": decision_log.now_iso()})
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest
    coid = f"{EQ_PREFIX}{decision_id}-{side[:1]}{os.urandom(3).hex()}"
    req = MarketOrderRequest(
        symbol=symbol, qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY, client_order_id=coid,
    )
    order = client._trading_client().submit_order(req)
    return {"id": str(order.id), "client_order_id": coid}


def _flatten_position(client, symbol: str, pos, *, reason: str, dry: bool):
    """Close (buy back a short / sell a long). Returns ("closed", pnl-or-None)
    on a CONFIRMED close, or None to stay in trade and retry next minute.

    `symbol` is passed in because the state block is stored UNDER the symbol in
    state["symbols"] and never carries a "symbol" field of its own. Reading it
    from the block raised KeyError and broke every exit path — stop, time exit
    and the mandatory EOD flatten alike (2026-08-31)."""
    close_side = "buy" if pos["side"] == "short" else "sell"
    if dry:
        _post(f"WOULD CLOSE {symbol} {pos['side']} x{pos['qty']} ({reason})")
        return ("closed", None)
    res = _submit_market(client, symbol=symbol, side=close_side,
                         qty=int(pos["qty"]), decision_id=pos["trade_id"],
                         allow_sdk_fallback=True)
    confirmed = _confirm_fill(client, res["id"])
    if confirmed is None:
        _post(f"{symbol} close NOT confirmed ({reason}) — retrying next minute")
        return None
    _, exit_price = confirmed
    entry = float(pos.get("entry_price") or 0)
    if entry <= 0:
        _post(f"Closed adopted orphan {symbol} ({reason}) — P&L unknown")
        _log({"kind": "eq_close", "symbol": symbol, "reason": f"{reason}_orphan",
              "exit": exit_price, "qty": int(pos["qty"]), "pnl_usd": None,
              "ts": decision_log.now_iso()})
        return ("closed", None)
    direction = -1.0 if pos["side"] == "short" else 1.0
    pnl = (exit_price - entry) * direction * int(pos["qty"])
    _post(f"Closed {symbol} {pos['side']} x{pos['qty']} ({reason}) "
          f"P&L {'+' if pnl >= 0 else '-'}${abs(pnl):.2f}")
    _log({"kind": "eq_close", "symbol": symbol, "reason": reason,
          "entry": entry, "exit": exit_price, "qty": int(pos["qty"]),
          "pnl_usd": round(pnl, 2), "ts": decision_log.now_iso()})
    return ("closed", pnl)


def _open_position(client, symbol: str, signal, spot: float, rails, *, dry: bool) -> bool:
    """Returns True if a position is now open (or would be, in dry run)."""
    qty = int(rails.notional_per_trade_usd / spot) if spot > 0 else 0
    if qty < 1:
        _log({"kind": "eq_skip", "symbol": symbol, "reason": "notional below 1 share",
              "ts": decision_log.now_iso()})
        return False
    side = "sell" if signal.side == "short" else "buy"
    decision_id = decision_log.new_decision_id()
    if dry:
        _post(f"WOULD OPEN {symbol} {signal.side} x{qty} rule={signal.rule} @~{spot:.2f}")
        return True
    res = _submit_market(client, symbol=symbol, side=side, qty=qty, decision_id=decision_id)
    confirmed = _confirm_fill(client, res["id"])
    if confirmed is None:
        client.cancel_order(res["id"])
        _log({"kind": "eq_skip", "symbol": symbol, "reason": "entry_not_confirmed",
              "ts": decision_log.now_iso()})
        return False
    filled_qty, fill_price = confirmed
    state = _load_state(_today_et())
    blk = state["symbols"].setdefault(symbol, {})
    blk.update({
        "trade_id": decision_id, "rule": signal.rule, "side": signal.side,
        "qty": int(filled_qty), "entry_price": float(fill_price),
        "entry_ts": decision_log.now_iso(), "entry_bar_time": None,
    })
    if signal.rule not in state.get("rules_taken_day", []):
        state.setdefault("rules_taken_day", []).append(signal.rule)
    state["trades_today"] = int(state.get("trades_today", 0)) + 1
    _save_state(state)
    _post(f"OPEN {symbol} {signal.side} x{int(filled_qty)} rule={signal.rule} "
          f"@ {fill_price:.2f}")
    _log({"kind": "eq_open", "symbol": symbol, "rule": signal.rule, "side": signal.side,
          "qty": int(filled_qty), "entry_price": float(fill_price), "ts": decision_log.now_iso()})
    return True


def run() -> None:
    if not _enabled():
        log.info("OA_EQUITY_SCALP_ENABLED not true — equity scalper inert.")
        return
    client = make_client()
    if not client.market_is_open():
        return
    rails = active_equity_scalp_rails()
    cfg = config().get("equity_scalp", {})
    underlyings = list(cfg.get("underlyings", ["SPY", "QQQ"]))
    gap_symbol = str(cfg.get("gap_follow", {}).get("symbol", "QQQ")).upper()
    gap_pct_min = float(cfg.get("gap_follow", {}).get("gap_pct_min", 0.8))
    dry = _dry()

    now_et = datetime.now(timezone.utc).astimezone(ET)
    et_date, now_hhmm = now_et.strftime("%Y-%m-%d"), now_et.strftime("%H:%M")
    state = _load_state(et_date)

    # ---- broker reconciliation (fail-closed: entries blocked if this fails) ----
    try:
        broker_positions = client.list_positions()
    except Exception:
        log.exception("broker position read failed — no entries this tick (fail closed)")
        broker_positions = None

    if broker_positions is not None:
        # Orphan guard: adopt any untracked SPY/QQQ equity position so it gets
        # stops and the mandatory flatten (crash between fill and state save).
        try:
            orphans = orphan_equity_positions(broker_positions, state, symbols=tuple(underlyings))
            for o in orphans:
                if o["qty"] == 0:
                    continue
                _post(f"adopted orphaned {o['symbol']} {o['side']} x{abs(o['qty'])} "
                      f"from the broker (state was missing it) — now managed.")
                state["symbols"][o["symbol"]] = {
                    "trade_id": f"orphan-{o['symbol']}-{et_date}", "rule": "orphan",
                    "side": o["side"], "qty": int(abs(o["qty"])),
                    "entry_price": 0.0, "entry_ts": decision_log.now_iso(),
                    "entry_bar_time": None,
                }
            if orphans:
                _save_state(state)
        except Exception:
            log.exception("orphan check failed (continuing to exit management)")

    for symbol in underlyings:
        blk = state["symbols"].setdefault(symbol, {})
        try:
            bars_raw = client.stock_minute_bars(symbol, lookback_minutes=1600, feed="sip")
            session = session_bars(bars_raw, et_date)
            if not session:
                continue

            # ---- manage an open position (qty is the marker; orphans carry
            #      entry_price 0.0 and still get the flatten) ----
            if blk.get("qty"):
                last = session[-1]
                entry_min = blk.get("entry_bar_time")
                entry_i = next((i for i, b in enumerate(session) if b["et_time"] == entry_min), None) \
                    if entry_min else None
                if entry_i is None:
                    entry_i = len(session) - 1  # conservative: treat as just entered
                decision = evaluate_equity_exit(
                    side=blk["side"], entry_price=float(blk.get("entry_price") or 0),
                    last_price=float(last["c"]), bar_low=float(last["l"]), bar_high=float(last["h"]),
                    entry_bar_index=entry_i, last_bar_index=len(session) - 1,
                    now_et_hhmm=now_hhmm, rails=rails)
                if decision.should_close:
                    result = _flatten_position(client, symbol, blk, reason=decision.reason, dry=dry)
                    if result is not None:
                        _, pnl = result
                        if pnl is not None:
                            state["realized_pnl_usd"] = float(state.get("realized_pnl_usd", 0.0)) + pnl
                        state["symbols"][symbol] = {}
                        if state["realized_pnl_usd"] <= -abs(rails.daily_loss_stop_usd):
                            state["halted"] = True
                            state["halt_reason"] = (
                                f"daily loss ${state['realized_pnl_usd']:.0f} hit "
                                f"-${rails.daily_loss_stop_usd:.0f}")
                            _post(f"HALTED for the day: {state['halt_reason']}")
                        _save_state(state)
                continue  # holding: no new entry on this symbol

            # ---- entry windows (one slot per rule per day, fail-closed on
            #      broker read failure) ----
            if broker_positions is None or state.get("halted"):
                continue
            if len(state.get("rules_taken_day", [])) >= rails.max_trades_per_day:
                continue
            open_count = sum(1 for b in state["symbols"].values()
                             if isinstance(b, dict) and b.get("qty"))
            if open_count >= rails.max_concurrent:
                continue

            signal = None
            if "morning_fade" not in state.get("rules_taken_day", []):
                win = next(w for w in rails.entry_windows if w[0] == "morning_fade")
                if win[1] <= now_hhmm <= win[2]:
                    s = morning_fade_signal(session)
                    if s:
                        signal = s
            if signal is None and symbol == gap_symbol and \
                    "gap_follow" not in state.get("rules_taken_day", []):
                win = next(w for w in rails.entry_windows if w[0] == "gap_follow")
                if win[1] <= now_hhmm <= win[2]:
                    prior = [b for b in bars_raw if b["et_date"] != et_date]
                    prev_close = prior[-1]["c"] if prior else 0.0
                    s = gap_follow_signal(session, prev_close=prev_close,
                                          open_px=session[0]["o"], gap_pct_min=gap_pct_min)
                    if s:
                        signal = s
            if signal is None:
                continue
            if _open_position(client, symbol, signal, float(session[-1]["c"]), rails, dry=dry):
                state = _load_state(et_date)
                blk = state["symbols"].setdefault(symbol, {})
                blk["entry_bar_time"] = session[-1]["et_time"]
                _save_state(state)
        except Exception:
            log.exception("equity scalp step failed for %s (continuing)", symbol)

    log.info("equity scalp tick et=%s %s trades=%s rules=%s pnl=%.2f halted=%s",
             et_date, now_hhmm, state.get("trades_today"), state.get("rules_taken_day"),
             float(state.get("realized_pnl_usd", 0.0)), state.get("halted"))


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.exception("run_scalp_equity crashed")
        try:
            notify.error(f"run_scalp_equity crashed: {e}")
        except Exception:
            pass
        raise
