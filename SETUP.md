# Wingspan deployment runbook

Updated 2026-09-09.

| Resource | Identifier |
|---|---|
| Railway project | `wingspan` · `cc393b70-4ef5-48d5-8299-253b914cc219` |
| Production environment | `0ca4cd30-99eb-489e-b8fd-ba580ede800a` |
| Service | `wingspan` · `ad956ca9-5bed-4369-aa1c-671ca77bf720` |
| Persistent volume | `f2d1a835-debe-472b-b154-7c441fb98bc8` |
| Mac/container working directory | `/Users/mo/wingspan` |
| Discord channel | `1544462423111761990` · `wingspan` |
| Dashboard | https://optionsagent-production.up.railway.app |

## Deploy

```bash
cd /Users/mo/wingspan
python3 -m pytest -q tests
railway up --service wingspan
railway service status --service wingspan
railway logs --service wingspan --lines 50
railway ssh --service wingspan -- pwd
```

Deploy manually; the repository is not used for automatic deployments. The image
runs Python 3.11, the pinned Alpaca CLI and Linux cron in America/New_York.
Mac launchd and local trading cron remain disabled.

## Persistent state

The existing Railway volume must remain attached. Never replace it with an empty
volume during a rename. `entrypoint.sh` requires the mounted volume on Railway and
uses `RAILWAY_VOLUME_MOUNT_PATH` if a migration still exposes a previous path.
The final mount is `/Users/mo/wingspan/data`.

Keep `structures.jsonl`, `decisions.jsonl`, `spread_exit_orders.json`, `exit_state.json`,
stock-scalper journals/day state, chain snapshots and `data/.locks`. Daily entry
markers prevent duplicate cycles after deployment. `logs/` links to volume logs.
A pending exit survives restart and is reconciled before classifying missing legs.

## Schedule

- Entries: `cron/entry.sh`, every five minutes during configured ET windows.
  `OA_ENTRY_WINDOWS` currently includes morning and afternoon windows, each with
  its own once-per-day marker. Default without the variable is 10:15–10:27 ET.
- Exits: `cron/exits.sh`, every 20 minutes during market hours, with a run lock.
- Stock scalper: `cron/equity_scalp.sh`, every minute during its market window.
- Retired options scalp and shared-data publisher remain controlled by separate flags.

Every trading wrapper checks the paper gate and broker market clock. Never run
`run_cycle.py` as a health check: the Python runner can place paper orders.

## Configuration

Secrets stay in Railway variables and ignored local `.env`; never print values.
Entrypoint writes an explicit allowlist into `.env` because cron lacks the service environment.

| Purpose | Variables |
|---|---|
| Paper execution | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER=true`, `OA_TRADING_ENABLED` |
| Broker transport | `OA_BROKER_TRANSPORT=cli`, optional `OA_ALPACA_CLI` |
| AI proposals | `DEEPSEEK_API_KEY`, `OA_LLM_PROVIDER=deepseek`, `OA_DEEPSEEK_MODEL` |
| AI retries/timeouts | `OA_LLM_ATTEMPTS`, `OA_LLM_TIMEOUT_SECONDS` |
| Options guard | `OA_CREDIT_SPREAD_GATE=research_rules`, `OA_MAX_POSITION_USD=3000` |
| Entry windows | `OA_ENTRY_WINDOWS` |
| Discord | `NOTIFY_DISCORD_TOKEN`, `NOTIFY_DISCORD_CHANNEL`; alternative `DISCORD_WEBHOOK_URL` |
| Dashboard | `OA_DASHBOARD_HOST`, `OA_DASHBOARD_URL`, Railway `PORT` |
| Public options data | `OA_OPTIONS_DATA_PROVIDER=public`, `PUBLIC_API_SECRET`, `PUBLIC_ACCOUNT_ID` |
| Stock data relay | `OA_DATA_URL`, `OA_DATA_KEY_ID`, `OA_DATA_SECRET_KEY` |
| Stock scalper | `OA_EQUITY_SCALP_ENABLED` and the tighten-only `OA_EQUITY_*` rails |

New variables must be added to code, Railway and the entrypoint allowlist together.
The dashboard is public and observational; `/healthz` proves liveness only. Verify
`/api/summary`, `/api/positions`, `/api/history`, `/api/risk` and `/api/system` as well.
Compare broker positions and persistent records before and after a deployment.
