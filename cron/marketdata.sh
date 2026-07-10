#!/bin/bash
# OptionsAgent — shared market-data publisher, one snapshot/minute during RTH.
# Independent of the trading scalper. Self-gates on OA_MARKETDATA_ENABLED=true, the
# 09:30-16:00 ET window, a run-lock, and the broker market clock (fail-closed).
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

MD_ENABLED=$(grep -E '^OA_MARKETDATA_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
if [ "${MD_ENABLED:-}" != "true" ]; then exit 0; fi

LOCK="$PWD/data/.locks/marketdata_running"
mkdir -p "$PWD/data/.locks" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  exit 0
fi

python3 run_marketdata.py
