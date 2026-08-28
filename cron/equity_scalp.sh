#!/bin/bash
# OptionsAgent — equity intraday scalper (mined rules A+C, 2026-08-28), one fused
# entry+exit tick per minute. Isolated from the 0DTE option scalper and the
# credit-spread seller. Self-gates on:
#   1. OA_EQUITY_SCALP_ENABLED=true (master switch)
#   2. ET window 09:45-15:55 (rules fire 10:15 and 13:00; exits run to 15:50 flatten)
#   3. an atomic run-lock so a >60s tick can't overlap the next minute's fire
#   4. the broker market clock (fail-closed: any error skips the minute)
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

TRADING_ENABLED=$(grep -E '^OA_TRADING_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${TRADING_ENABLED:-}" != "true" ]; then exit 0; fi
PAPER_MODE=$(grep -E '^ALPACA_PAPER=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${PAPER_MODE:-}" != "true" ]; then echo "[eq-scalp] paper gate failed — skipping"; exit 0; fi

EQ_ENABLED=$(grep -E '^OA_EQUITY_SCALP_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
if [ "${EQ_ENABLED:-}" != "true" ]; then exit 0; fi

HOUR=$(TZ=America/New_York date +%H)
MIN=$(TZ=America/New_York date +%M)
if [ "$HOUR" = "09" ] && [ "$MIN" -lt 45 ]; then exit 0; fi
if [ "$HOUR" = "15" ] && [ "$MIN" -gt 55 ]; then exit 0; fi
if [ "$HOUR" \> "15" ] || [ "$HOUR" \< "09" ]; then exit 0; fi

LOCK="$PWD/data/.locks/equity_scalp_running"
mkdir -p "$PWD/data/.locks" 2>/dev/null
find "$LOCK" -maxdepth 0 -type d -mmin +10 -exec rmdir {} \; 2>/dev/null || true
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  exit 0
fi

python3 run_scalp_equity.py
