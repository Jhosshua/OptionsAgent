# OptionsAgent

> **Where this runs (since 2026-09-01):** Railway, project `OptionsAgent`, not this Mac.
> Linux cron in the container is the scheduler; state lives on the volume at `data/`.
> Proposals come from the **DeepSeek API** (`DEEPSEEK_API_KEY`, since 2026-09-01 evening);
> the image no longer carries the Claude Code CLI. `harness/proposer.py` fails CLOSED on
> any API/key error and pages Discord, and every call is journaled as a `proposer_result` row.
> Dashboard: https://optionsagent-production.up.railway.app (public, no password).
> Alerts: Discord `#options-agent`. Redeploy: `railway up --service OptionsAgent`.
> The Mac's launchd plist and its three user-crontab lines are disabled.

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

> **OPERATING MODE — 2026-09-01:** A paper-trading robot on Railway. The DeepSeek
> API (`OA_LLM_PROVIDER=deepseek`, model `deepseek-v4-pro`) supplies proposals;
> no Anthropic key and no Claude CLI login are involved any more. Public.com is read-only options
> data, AlpacaRelay serves stock bars, Alpaca remains paper execution. **Railway
> variables are authoritative** — `entrypoint.sh` writes them into `.env` at boot,
> because cron does not inherit the container environment.
> (Until 2026-09-01 this ran locally, with the Mac `.env` and user crontab
> authoritative. Those crontab lines are now commented out.)

## Status (2026-09-01)

**ACTIVE ON RAILWAY, PAPER ONLY, TWO ENGINES on a $100,000 Alpaca paper account.**
- Engine 1, credit-spread seller: the DeepSeek API proposes, deterministic rails
  dispose, once daily 10:15-10:27 ET (cron/entry.sh), exits every 20 min
  (cron/exits.sh). Winner-profile gated; most days it vetoes everything.
- Engine 2, EQUITY intraday scalper (run_scalp_equity.py, NEW tonight): two
  rules mined from 6 months of SPY/QQQ minute bars and frozen (morning fade at
  10:15; QQQ gap follow at 13:00). $20k notional, 0.7% intrabar stop, 120m time
  exit, 15:50 ET flatten, -$300 daily halt. Cron * 9-15 * * 1-5.
- The 0DTE OPTION scalper was retired tonight: a 16,384-combination study over
  125 sessions found no positive-expectancy configuration (RESEARCH_SCALP_6MO.md).
- Stock data runs through a read-only SIP-entitled key (OA_DATA_* in .env);
  option chains/quotes via the Public.com sidecar; execution paper-only.
- Dashboard: https://optionsagent-production.up.railway.app — read-only, reset to
  the 08-28 activation date. (Was a local LaunchAgent on 127.0.0.1:8765 until
  2026-09-01; it is now public to anyone with the link, with no password.) Operator explainer PDF: OptionsAgent-Explained.pdf.

## Docs map

| File | What it's for |
|---|---|
| `CLAUDE.md` | Read FIRST every session: constraints, locked stack, current status |
| `MEMORY.md` | Decision log: what was decided / why / what was rejected |
| `ERRORS.md` | Approaches that failed and what worked instead |
| `ARCHITECTURE.md` | The original design + rationale (superseded parts are banner-marked) |
| `RESEARCH.md` | The 3-pass deep research every threshold number traces back to |
| `OVERFIT_ANALYSIS.md` | Archived per-day/per-trade replay and the documented local research changes |
| `research_credit_spread_history.py` | Replays the archived multi-day credit-spread ledger and winner profile |
| `DEEPSEEK_CREDIT_SPREAD_PROMPT.md` | Read-only prompt for an independent DeepSeek/claude-ds review |
| `SETUP.md` | Railway runbook, scheduler, the DeepSeek proposer, logs, and paper-trading gates |

## Local dev

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in paper credentials, `DEEPSEEK_API_KEY`, and the
   read-only Public secret. (`OA_LLM_PROVIDER=claude_cli` uses the Mac's Claude CLI instead.)
4. `python3 -m pytest tests/` — all tests pass without broker or model calls.
4. The bot itself runs on Railway; the Mac crontab lines are commented out. Run
   `python3 run_cycle.py` locally only when intentionally performing a paper entry cycle
   (it would trade the same paper account).

## Config

`config/config.json` holds tunables (strategy phase allowlist, delta/DTE targets, conviction
thresholds, exit targets). The rails in `harness/risk_rails.py` (conviction floor, max positions,
DTE close, and the historical credit-spread winner profile) live in code by design. Sizing is full-deploy per operator decision 2026-07-03:
conviction-scaled fraction of available buying power, no percentage caps — `OA_MAX_POSITION_USD`
env var is the tighten-only emergency brake.

## Optional Public market-data sidecar

The default provider is Alpaca. Set `OA_OPTIONS_DATA_PROVIDER=public` to source option chains,
Greeks, bid/ask quotes, and exit marks from Public.com while Alpaca remains the paper execution
broker. This requires a personal Public API secret and account ID in environment variables; the
adapter is read-only and never submits Public orders. See `SETUP.md` for the credential flow and
`harness/public_marketdata.py` for the boundary.

## Dashboard

The supplied daylight dashboard is implemented under `dashboard/` and served by the
`harness.dashboard_server` process, which the Railway entrypoint supervises alongside cron.
It is read-only and defaults to paper trading disarmed.

**Live at https://optionsagent-production.up.railway.app.** In the container it binds
`0.0.0.0` on Railway's `$PORT` (`OA_DASHBOARD_HOST=0.0.0.0`), so unlike the old
loopback-only setup it is reachable by anyone with the URL and has no password.
A dashboard crash never bounces cron mid-trade — it is deliberately not the healthcheck.

Enable `OA_TRADING_ENABLED` only after the deployment verification sequence in `SETUP.md`.
