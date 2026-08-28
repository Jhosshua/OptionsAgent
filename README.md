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

## Status (2026-08-28)

**ACTIVE LOCALLY, PAPER ONLY.** Public market data and the Claude Code CLI proposer are enabled
locally. Alpaca remains paper-only execution. The archived Railway deployment is not used.

### Historical status (2026-08-27)

**RETIRED and not deployed.** The archived bot history was analyzed, the 0DTE scalp hard entry
cutoff was tightened to 11:30 ET, and the multi-day credit-spread seller was intentionally
overfit to a three-record historical winner profile. The original Railway project, paper account,
and webhook were deleted on 2026-08-02; see `CLAUDE.md` and `OVERFIT_ANALYSIS.md` before any restart.

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
