#!/bin/bash
# OptionsAgent — daily entry-proposal cycle.
# Self-gates to the 10:15-10:27 ET window (staggered after DeterministicAgent's
# 10:00 slot so shared APIs aren't hit simultaneously), once/day via a marker
# on the VOLUME (data/.locks — survives redeploys; container fs and /tmp are
# ephemeral). Market-open guard asks the broker clock and FAILS CLOSED: any
# error in the check skips the day rather than trading blind.

set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

TRADING_ENABLED=$(grep -E '^OA_TRADING_ENABLED=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${TRADING_ENABLED:-}" != "true" ]; then exit 0; fi
PAPER_MODE=$(grep -E '^ALPACA_PAPER=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
if [ "${PAPER_MODE:-}" != "true" ]; then echo "[entry] paper gate failed — skipping"; exit 0; fi

HOUR=$(TZ=America/New_York date +%H)
MIN=$(TZ=America/New_York date +%M)
DATE=$(TZ=America/New_York date +%Y%m%d)

LOCKS_DIR="$PWD/data/.locks"
mkdir -p "$LOCKS_DIR" 2>/dev/null
find "$LOCKS_DIR" -maxdepth 1 -type d -name 'entry_*' -mtime +7 -exec rmdir {} \; 2>/dev/null || true
# Entry windows (ET, "HH:MM-HH:MM", comma separated). Default = the historical
# single 10:15-10:27 window. OA_ENTRY_WINDOWS="10:15-10:27,14:00-14:12" adds an
# afternoon cycle (hackathon option, 2026-09-02); each window has its own
# once-per-day marker, and the rails' one-position-per-name / max-open checks
# keep a second cycle from doubling up on a name already open.
WINDOWS=$(grep -E '^OA_ENTRY_WINDOWS=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "')
WINDOWS="${WINDOWS:-10:15-10:27}"
NOW=$((10#$HOUR * 60 + 10#$MIN))
MARKER=""
IFS=',' read -ra WLIST <<< "$WINDOWS"
for W in "${WLIST[@]}"; do
  S="${W%-*}"; E="${W#*-}"
  SM=$((10#${S%:*} * 60 + 10#${S#*:})); EM=$((10#${E%:*} * 60 + 10#${E#*:}))
  if [ "$NOW" -ge "$SM" ] && [ "$NOW" -le "$EM" ]; then MARKER="$LOCKS_DIR/entry_${DATE}_${S/:/}"; break; fi
done
# Backward compatible: the first window keeps the old marker name so a day already
# claimed under the old scheme is not re-run after a redeploy.
[ -n "$MARKER" ] && [ "${MARKER##*_}" = "1015" ] && MARKER="$LOCKS_DIR/entry_${DATE}"
if [ -z "$MARKER" ]; then exit 0; fi

# Atomic once-per-window claim (mkdir is the lock).
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
