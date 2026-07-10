#!/usr/bin/env bash
# OptionsAgent — Railway container entrypoint. Mirrors the proven
# DeterministicAgent-Railway pattern:
#   1. Inject secrets from Railway env vars into .env (cron does NOT pass the
#      container env to jobs; harness/env.py reads .env via dotenv).
#   2. Ensure the persistent volume (mounted at data/) has the runtime dirs.
#   3. Point logs/ at the volume so logs survive redeploys.
#   4. Install the cron schedule and hand off to cron in the foreground (PID 1).
set -euo pipefail

APP=/Users/mo/OptionsAgent
ENV_FILE="$APP/.env"

echo "[entrypoint] OptionsAgent starting at $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"

# --- 1. Inject secrets from Railway env -> .env (upsert) ---
# ⚠️ This allowlist is a known 3-touch-point gotcha (see fleet memory): adding a
# new provider/key later means updating (a) code/config, (b) Railway vars, AND
# (c) this list. A key missing here silently never reaches the cron jobs.
python3 - "$ENV_FILE" <<'PY'
import os, sys
env_file = sys.argv[1]
secret_keys = [
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER",
    "ANTHROPIC_API_KEY", "OA_ANTHROPIC_MODEL", "OA_MAX_TOKENS",
    "DISCORD_WEBHOOK_URL",
    # 0DTE ORB scalper (isolated). Master switch + tighten-only rail overrides +
    # dry-run. Missing from this list = silently never reaches the cron job.
    "OA_SCALP_ENABLED", "OA_SCALP_DRY_RUN",
    "OA_SCALP_PER_TRADE_USD", "OA_SCALP_MAX_TRADES", "OA_SCALP_DAILY_LOSS_USD",
]
try:
    lines = open(env_file).read().splitlines()
except OSError:
    lines = []
present = {}
for i, ln in enumerate(lines):
    if "=" in ln and not ln.lstrip().startswith("#"):
        present[ln.split("=", 1)[0].strip()] = i
injected = []
for key in secret_keys:
    val = os.environ.get(key)
    if val is None or val == "":
        continue
    line = f"{key}={val}"
    if key in present:
        lines[present[key]] = line
    else:
        lines.append(line)
    injected.append(key)
open(env_file, "w").write("\n".join(lines) + "\n")
print("[entrypoint] injected secrets:", ", ".join(injected) if injected else "(none set)")
PY

# --- 2. Volume runtime dirs (never clobber existing volume state) ---
mkdir -p "$APP/data/logs" "$APP/data/.locks" "$APP/data/scalp_state"
[ -f "$APP/data/decisions.jsonl" ] || : > "$APP/data/decisions.jsonl"
[ -f "$APP/data/structures.jsonl" ] || : > "$APP/data/structures.jsonl"
[ -f "$APP/data/scalp_positions.jsonl" ] || : > "$APP/data/scalp_positions.jsonl"
[ -f "$APP/data/scalp_decisions.jsonl" ] || : > "$APP/data/scalp_decisions.jsonl"

# --- 3. logs/ -> volume so logs survive redeploys ---
rm -rf "$APP/logs"
ln -sfn "$APP/data/logs" "$APP/logs"

# --- 4. Install cron schedule + run cron in the foreground ---
install -m 0644 -o root -g root "$APP/cron/crontab.railway" /etc/cron.d/optionsagent
echo "[entrypoint] cron schedule installed; handing off to cron (foreground)."

# Announce the deploy in Discord if the webhook is configured. Never fatal.
if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
  python3 -c "
from harness.env import active_phase, allowed_strategies
from harness.notify import post
ts = __import__('subprocess').run(['date', '+%H:%M ET'], capture_output=True, text=True, env={'TZ': 'America/New_York'}).stdout.strip()
post(f'🚂 OptionsAgent is live on Railway ({ts}). Mode: {active_phase()} ({\", \".join(allowed_strategies())}), Alpaca PAPER.')
" || true
fi

exec cron -f -L 2
