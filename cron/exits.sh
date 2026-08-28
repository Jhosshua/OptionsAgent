#!/bin/bash
# OptionsAgent — exit sweep (LLM-free deterministic monitoring).
# Cron fires this every 20 min on weekdays; it self-gates to market hours via
# the broker clock (fail-closed: an error in the check means skip, never act
# blind). No once-per-day marker — the sweep is idempotent (a structure it
# already closed is gone from the registry on the next pass).

set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

TRADING_ENABLED=$(grep -E '^OA_TRADING_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${TRADING_ENABLED:-}" != "true" ]; then exit 0; fi
PAPER_MODE=$(grep -E '^ALPACA_PAPER=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${PAPER_MODE:-}" != "true" ]; then echo "[exits] paper gate failed — skipping"; exit 0; fi

LOCK="$PWD/data/.locks/exits_running"
if [ -d "$LOCK" ]; then
  find "$LOCK" -maxdepth 0 -type d -mmin +15 -exec rmdir {} \; 2>/dev/null || true
fi
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  exit 0
fi

echo "[exits] $(TZ=America/New_York date '+%H:%M ET') — running exit sweep"
python3 run_exits.py
