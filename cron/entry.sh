#!/bin/bash
# OptionsAgent — daily entry-proposal cycle.
# Self-gates to the 10:15-10:27 ET window (staggered after DeterministicAgent's
# 10:00 slot so shared APIs aren't hit simultaneously), once/day via a marker
# on the VOLUME (data/.locks — survives redeploys; container fs and /tmp are
# ephemeral). Market-open guard asks the broker clock and FAILS CLOSED: any
# error in the check skips the day rather than trading blind.

set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

HOUR=$(TZ=America/New_York date +%H)
MIN=$(TZ=America/New_York date +%M)
DATE=$(TZ=America/New_York date +%Y%m%d)

LOCKS_DIR="$PWD/data/.locks"
mkdir -p "$LOCKS_DIR" 2>/dev/null
find "$LOCKS_DIR" -maxdepth 1 -type d -name 'entry_*' -mtime +7 -exec rmdir {} \; 2>/dev/null || true
MARKER="$LOCKS_DIR/entry_${DATE}"

# Window: 10:15-10:27 ET
if [ "$HOUR" != "10" ] || [ "$MIN" -lt 15 ] || [ "$MIN" -gt 27 ]; then exit 0; fi

# Atomic once-per-day claim (mkdir is the lock).
if ! mkdir "$MARKER" 2>/dev/null; then exit 0; fi

# Holiday/weekend guard via broker clock (fail-closed).
if ! python3 -c "
from harness.alpaca_glue import make_client
import sys
sys.exit(0 if make_client().market_is_open() else 1)
"; then
  echo "[entry] market closed (or clock check failed) — skipping today"
  exit 0
fi

echo "[entry] $(TZ=America/New_York date '+%H:%M ET') — running entry cycle"
python3 run_cycle.py
