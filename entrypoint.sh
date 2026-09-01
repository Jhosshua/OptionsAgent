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
    "OA_TRADING_ENABLED", "OA_DASHBOARD_HOST",
    "ANTHROPIC_API_KEY", "OA_ANTHROPIC_MODEL", "OA_MAX_TOKENS",
    # The proposer shells out to the Claude Code CLI. Headless auth is the
    # OAuth token; OA_CLAUDE_CLI is the container path to the executable.
    # Missing either = _claude_cli() raises = fail-closed "no trade", silently.
    "CLAUDE_CODE_OAUTH_TOKEN", "OA_CLAUDE_CLI", "OA_CLAUDE_MODEL",
    "OA_CLAUDE_TIMEOUT_SECONDS", "OA_CLAUDE_ATTEMPTS",
    # Equity scalper rails. The master switch alone is not enough: without these
    # every rail silently falls back to its code default, so a TIGHTER limit set
    # in Railway would never bind. cron does not pass the container env.
    "OA_EQUITY_SCALP_ENABLED", "OA_EQUITY_SCALP_DRY_RUN",
    "OA_EQUITY_NOTIONAL_USD", "OA_EQUITY_STOP_PCT",
    "OA_EQUITY_MAX_TRADES", "OA_EQUITY_DAILY_LOSS_USD",
    # Tighten-only per-position cap (harness/risk_rails.py).
    "OA_MAX_POSITION_USD",
    "DISCORD_WEBHOOK_URL",
    # 0DTE ORB scalper (isolated). Master switch + tighten-only rail overrides +
    # dry-run. Missing from this list = silently never reaches the cron job.
    "OA_SCALP_ENABLED", "OA_SCALP_DRY_RUN",
    "OA_SCALP_PER_TRADE_USD", "OA_SCALP_MAX_TRADES", "OA_SCALP_DAILY_LOSS_USD",
    # Shared market-data feed: publisher switch + relay token/port.
    "OA_MARKETDATA_ENABLED", "OA_RELAY_TOKEN", "OA_RELAY_PORT",
    # AlpacaRelay data proxy: eyes creds + base-URL override. Missing from
    # this list = deployed cron jobs silently fall back to direct Alpaca.
    "OA_DATA_KEY_ID", "OA_DATA_SECRET_KEY", "OA_DATA_URL",
    # Optional read-only Public.com market-data sidecar. Alpaca remains the
    # account/order broker; these values are only copied into the cron .env.
    "OA_OPTIONS_DATA_PROVIDER", "PUBLIC_API_SECRET", "PUBLIC_API_SECRET_KEY",
    "PUBLIC_ACCOUNT_ID", "PUBLIC_OPTIONS_DTE_MIN", "PUBLIC_OPTIONS_DTE_MAX",
    "PUBLIC_QUOTE_BATCH_SIZE", "PUBLIC_API_TIMEOUT_SECONDS",
]
try:
    lines = open(env_file).read().splitlines()
except OSError:
    lines = []
filtered = []
for ln in lines:
    key = ln.split("=", 1)[0].strip() if "=" in ln and not ln.lstrip().startswith("#") else ""
    if key not in secret_keys:
        filtered.append(ln)
lines = filtered
injected = []
for key in secret_keys:
    val = os.environ.get(key)
    if val is not None and val != "":
        lines.append(f"{key}={val}")
        injected.append(key)
os.makedirs(os.path.dirname(env_file), exist_ok=True)
with open(env_file, "w") as fh:
    fh.write("\n".join(lines) + "\n")
os.chmod(env_file, 0o600)
print("[entrypoint] injected secrets:", ", ".join(injected) if injected else "(none set)")
PY

# --- 2. Volume runtime dirs (never clobber existing volume state) ---
mkdir -p "$APP/data/logs" "$APP/data/.locks" "$APP/data/scalp_state" "$APP/data/marketdata"
[ -f "$APP/data/decisions.jsonl" ] || : > "$APP/data/decisions.jsonl"
[ -f "$APP/data/structures.jsonl" ] || : > "$APP/data/structures.jsonl"
[ -f "$APP/data/scalp_positions.jsonl" ] || : > "$APP/data/scalp_positions.jsonl"
[ -f "$APP/data/scalp_decisions.jsonl" ] || : > "$APP/data/scalp_decisions.jsonl"

# --- 3. logs/ -> volume so logs survive redeploys ---
rm -rf "$APP/logs"
ln -sfn "$APP/data/logs" "$APP/logs"

# --- 4. Install cron schedule + run cron in the foreground ---
install -m 0644 -o root -g root "$APP/cron/crontab.railway" /etc/cron.d/optionsagent

# Dashboard is supervised independently from cron. It is intentionally not a
# Railway healthcheck: a dashboard crash must not bounce cron mid-trade.
dashboard_loop() {
  while true; do
    python3 -m harness.dashboard_server >> "$APP/data/logs/dashboard.log" 2>&1 || true
    if [ -f "$APP/data/logs/dashboard.log" ] && [ "$(wc -c < "$APP/data/logs/dashboard.log")" -gt 2097152 ]; then
      tail -c 1048576 "$APP/data/logs/dashboard.log" > "$APP/data/logs/dashboard.log.tmp" || true
      mv "$APP/data/logs/dashboard.log.tmp" "$APP/data/logs/dashboard.log" 2>/dev/null || true
    fi
    sleep 5
  done
}
dashboard_loop &
echo "[entrypoint] dashboard supervisor started on ${OA_DASHBOARD_HOST:-127.0.0.1}:${PORT:-8080}."

echo "[entrypoint] cron schedule installed; handing off to cron (foreground)."

# --- 4b. Shared market-data relay (background). Only starts when OA_RELAY_TOKEN is
# set (read-only, token-gated GET server serving data/marketdata/<date>.jsonl to
# other bots). A crash here never affects trading — it's a separate process. ---
if [ -n "${OA_RELAY_TOKEN:-}" ]; then
  if [ "${OA_RELAY_PORT:-8399}" = "${PORT:-8080}" ]; then
    echo "[entrypoint] relay port equals public dashboard PORT — relay disabled to avoid collision"
  else
    echo "[entrypoint] starting market-data relay on internal port ${OA_RELAY_PORT:-8399}"
    python3 -m harness.marketdata_relay >> "$APP/data/logs/marketdata_relay.log" 2>&1 &
  fi
fi

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
