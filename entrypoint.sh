#!/usr/bin/env bash
# OptionsAgent — Railway container entrypoint. Mirrors the proven
# DeterministicAgent-Railway pattern:
#   1. Inject secrets from Railway env vars into .env (cron does NOT pass the
#      container env to jobs; harness/env.py reads .env via dotenv).
#   2. Ensure the persistent volume (mounted at data/) has the runtime dirs.
#   3. Point logs/ at the volume so logs survive redeploys.
#   4. Install the cron schedule and hand off to cron in the foreground (PID 1).
set -euo pipefail

APP=/Users/mo/wingspan
ENV_FILE="$APP/.env"

# During a folder migration the existing volume may still use its old mount.
# Always use that same volume; never start a second, empty trading ledger.
if [ -n "${RAILWAY_ENVIRONMENT_ID:-}" ]; then
  VOLUME_PATH="${RAILWAY_VOLUME_MOUNT_PATH:?Persistent volume is required}"
  [ -d "$VOLUME_PATH" ] || { echo "[entrypoint] missing persistent volume"; exit 1; }
  if [ "$VOLUME_PATH" != "$APP/data" ]; then
    if [ -d "$APP/data" ] && [ ! -L "$APP/data" ]; then rmdir "$APP/data"; fi
    ln -sfn "$VOLUME_PATH" "$APP/data"
  fi
fi

echo "[entrypoint] Wingspan starting at $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"

# --- 1. Inject secrets from Railway env -> .env (upsert) ---
# ⚠️ This allowlist is a known 3-touch-point gotcha (see fleet memory): adding a
# new provider/key later means updating (a) code/config, (b) Railway vars, AND
# (c) this list. A key missing here silently never reaches the cron jobs.
python3 - "$ENV_FILE" <<'PY'
import os, sys
env_file = sys.argv[1]
secret_keys = [
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER",
    "OA_TRADING_ENABLED", "OA_DASHBOARD_HOST", "OA_DASHBOARD_URL",
    # The AI proposer (harness/proposer.py) runs the agy CLI (Gemini) since
    # 2026-09-13. Its Google login is restored from GEMINI_HOME_TGZ_B64 below,
    # not through .env. A broken login = the proposer fails closed = "no
    # trade" that day, paged to Discord.
    "OA_AGY_MODEL", "OA_AGY_CLI", "OA_LLM_TIMEOUT_SECONDS", "OA_LLM_ATTEMPTS",
    # Equity scalper rails. The master switch alone is not enough: without these
    # every rail silently falls back to its code default, so a TIGHTER limit set
    # in Railway would never bind. cron does not pass the container env.
    "OA_EQUITY_SCALP_ENABLED", "OA_EQUITY_SCALP_DRY_RUN",
    "OA_EQUITY_NOTIONAL_USD", "OA_EQUITY_STOP_PCT",
    "OA_EQUITY_MAX_TRADES", "OA_EQUITY_DAILY_LOSS_USD",
    # Tighten-only per-position cap (harness/risk_rails.py).
    "OA_MAX_POSITION_USD",
    # Credit-spread gate mode (winner_profile | research_rules) and the broker
    # transport (sdk | cli). Hackathon 2026-09-01: both are set on Railway and
    # MUST reach the cron .env or the container silently runs the old path.
    "OA_CREDIT_SPREAD_GATE", "OA_BROKER_TRANSPORT", "OA_ALPACA_CLI", "OA_ENTRY_WINDOWS",
    # Alert transport. Either a webhook, OR the fleet's bot token + channel —
    # harness/notify.py accepts both. With neither, every alert is log-only and
    # a fail-closed no-trade day passes in total silence.
    "DISCORD_WEBHOOK_URL", "NOTIFY_DISCORD_TOKEN", "NOTIFY_DISCORD_CHANNEL",
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

# --- 1b. Restore the agy (Antigravity CLI) Google login ---
# GEMINI_HOME_TGZ_B64 is base64 of a tar.gz of a working ~/.gemini folder,
# the same variable ManualTrading2 uses. cron jobs run as root with HOME=/root.
if [ -n "${GEMINI_HOME_TGZ_B64:-}" ]; then
  if echo "$GEMINI_HOME_TGZ_B64" | base64 -d | tar -xzf - -C /root; then
    echo "[entrypoint] agy login restored to /root/.gemini"
  else
    echo "[entrypoint] GEMINI_HOME_TGZ_B64 could not be unpacked: AI proposals will fail closed"
  fi
else
  echo "[entrypoint] GEMINI_HOME_TGZ_B64 not set: AI proposals will fail closed"
fi

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
install -m 0644 -o root -g root "$APP/cron/crontab.railway" /etc/cron.d/wingspan

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

# Say at boot which alert transport is live. A bot that cannot alert is the
# failure that hides every other failure, so it is announced either way.
python3 -c "
from harness.notify import transport_status
print('[entrypoint] alert transport:', transport_status())
" || echo "[entrypoint] could not read the alert transport"

# Announce the deploy in Discord. Never fatal.
if [ -n "${DISCORD_WEBHOOK_URL:-}" ] || { [ -n "${NOTIFY_DISCORD_TOKEN:-}" ] && [ -n "${NOTIFY_DISCORD_CHANNEL:-}" ]; }; then
  python3 -c "
from harness.notify import post
post('### Wingspan is running\nOptions spreads and the stock strategy are being monitored. Trade updates and important alerts will appear here.')
" || true
fi

exec cron -f -L 2
