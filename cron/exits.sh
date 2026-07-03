#!/bin/bash
# OptionsAgent — exit sweep (LLM-free deterministic monitoring).
# Cron fires this every 20 min on weekdays; it self-gates to market hours via
# the broker clock (fail-closed: an error in the check means skip, never act
# blind). No once-per-day marker — the sweep is idempotent (a structure it
# already closed is gone from the registry on the next pass).

set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  exit 0
fi

echo "[exits] $(TZ=America/New_York date '+%H:%M ET') — running exit sweep"
python3 run_exits.py
