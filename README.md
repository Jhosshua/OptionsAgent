# OptionsAgent

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

> **CURRENT OPERATING MODE — 2026-08-28:** This is a local paper-trading
> robot. Claude Code CLI supplies proposals through the operator's existing
> authenticated CLI login; no `ANTHROPIC_API_KEY` is configured or required.
> Public.com is read-only market data and Alpaca remains paper execution. The
> local `.env` plus user crontab are authoritative; Railway is not used.

## Status (2026-08-28, night)

**ACTIVE LOCALLY, PAPER ONLY, TWO ENGINES on a $100,000 Alpaca paper account.**
- Engine 1, credit-spread seller: Claude Code CLI proposes, deterministic rails
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
- Dashboard: local LaunchAgent, 127.0.0.1:8765, read-only, reset to the 08-28
  activation date. Operator explainer PDF: OptionsAgent-Explained.pdf.

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
| `SETUP.md` | Local setup, scheduler, Claude Code CLI, logs, and paper-trading gates |

## Local dev

1. `pip install -r requirements.txt`
2. Ensure the authenticated `claude` CLI is on PATH (or set `OA_CLAUDE_CLI`).
3. Copy `.env.example` to `.env` and fill in paper credentials plus the read-only Public secret.
4. `python3 -m pytest tests/` — all tests pass without broker or model calls.
5. The local user crontab runs `cron/entry.sh` and `cron/exits.sh`; run `python3 run_cycle.py`
   manually only when intentionally performing a paper entry cycle.

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

The supplied daylight dashboard is implemented under `dashboard/` and served by the always-on
`harness.dashboard_server` process. It is read-only, local-only by default, and defaults to paper
trading disarmed. Run `zsh deploy/install_local_dashboard.sh` to keep it available at
`http://127.0.0.1:8765`; enable `OA_TRADING_ENABLED` only after the deployment verification
sequence in `SETUP.md` (the current sequence is local, not Railway).
