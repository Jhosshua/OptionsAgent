"""Exit sweep. Run every 15-30 min during market hours (cron). LLM-free —
pure deterministic monitoring of open wheel positions against exits.py's
checks (dividend-assignment risk, DTE close, profit target). NOT YET RUN
against a live paper account; see run_cycle.py's same caveat.

Building the OpenPosition rows from Alpaca's raw position + quote data (mark
price, same-strike opposite price, dividend calendar lookup) is the piece
still to wire up — this file lays out the sweep shape and where that data
needs to plug in.
"""

from __future__ import annotations

import logging

from harness import decision_log, notify
from harness.alpaca_glue import make_client
from harness.env import config
from harness.exits import evaluate_exit

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_exits")


def run() -> None:
    cfg = config()["wheel"]
    client = make_client()

    # TODO(phase 1 wiring): build_open_positions() needs to turn Alpaca's raw
    # short-option positions into exits.OpenPosition rows, which requires a
    # mark-price quote per position, the same-strike opposite-side quote
    # (for the dividend-assignment check), and an ex-dividend-date lookup.
    # None of that is wired yet — this loop is a no-op until it is.
    open_positions = []  # build_open_positions(client)

    for position in open_positions:
        decision = evaluate_exit(
            position, dte_close=cfg["dte_close"], profit_target_pct=cfg["profit_target_pct"]
        )
        if not decision.should_close:
            continue
        log.info("closing %s %s: %s", position.underlying, position.strategy_type, decision.reason)
        # TODO(phase 1 wiring): submit the buy-to-close order via
        # client.submit_single_leg_order(side="buy", ...) and compute realized
        # P&L before calling notify.trade_closed(...).
        decision_log.record(
            {
                "kind": "exit",
                "ts": decision_log.now_iso(),
                "underlying": position.underlying,
                "strategy_type": position.strategy_type,
                "reason": decision.reason,
            }
        )


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.exception("exit sweep failed")
        notify.error(f"run_exits crashed: {e}")
        raise
