"""Shared market-data publisher runner — one tick per minute during RTH. Writes a
bar+signals snapshot per underlying to data/marketdata/<date>.jsonl so the fleet
relay can serve it. Independent of the trading scalper: runs whenever
OA_MARKETDATA_ENABLED=true (sharing the data is useful even with the scalper off).
"""

from __future__ import annotations

import logging
import os

from harness import marketdata_publish, notify
from harness.alpaca_glue import make_client
from harness.env import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_marketdata")


def _enabled() -> bool:
    return (os.environ.get("OA_MARKETDATA_ENABLED", "") or "").lower() == "true"


def run() -> None:
    if not _enabled():
        log.info("OA_MARKETDATA_ENABLED not true — publisher inert.")
        return
    cfg_scalp = config().get("scalp", {})
    symbols = list(cfg_scalp.get("underlyings", ["SPY", "QQQ"]))
    feed = cfg_scalp.get("data_feed", "sip")
    rvol_min = float(cfg_scalp.get("rvol_min", 1.5))

    client = make_client()
    if not client.market_is_open():
        log.info("market closed — publisher idle.")
        return
    counts = marketdata_publish.publish(client, symbols, rvol_min=rvol_min, feed=feed)
    log.info("marketdata published: %s", counts)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.exception("run_marketdata crashed")
        try:
            notify.error(f"run_marketdata crashed: {e}")
        except Exception:
            pass
        raise
