#!/bin/bash
# OptionsAgent — 0DTE ORB scalper, one fused entry+exit tick per minute.
# FULLY ISOLATED from the credit-spread seller (entry.sh / exits.sh). Self-gates on:
#   1. OA_SCALP_ENABLED=true (off by default — the master switch)
#   2. ET window 09:33-15:59 (skip the first 3 min = the opening range)
#   3. an atomic run-lock so a >60s tick can't overlap the next minute's fire
#   4. the broker market clock (fail-closed: any error skips the minute)
# Env for the gate is sourced from .env (cron does not pass the container env to jobs).

set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

# --- 1. master switch (read from .env, which entrypoint.sh populates) ---
SCALP_ENABLED=$(grep -E '^OA_SCALP_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
if [ "${SCALP_ENABLED:-}" != "true" ]; then exit 0; fi

HOUR=$(TZ=America/New_York date +%H)
MIN=$(TZ=America/New_York date +%M)

# --- 2. ET window 09:33-15:59 (cron already bounds hours 9-15) ---
if [ "$HOUR" = "09" ] && [ "$MIN" -lt 33 ]; then exit 0; fi

# --- 3. atomic run-lock (mkdir) so overlapping ticks are a no-op ---
LOCK="$PWD/data/.locks/scalp_running"
mkdir -p "$PWD/data/.locks" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# --- 4. broker market clock (fail-closed) ---
if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  exit 0
fi

python3 run_scalp.py
