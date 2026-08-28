# OptionsAgent

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

## Status (2026-08-27)

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
| `SETUP.md` | Railway deployment runbook: env vars, redeploy, logs, kill knobs |

## Local dev

1. `pip install -r requirements.txt`
2. `python3 -m pytest tests/` — all tests pass with no network access or keys needed.
3. For a future recreated deployment only: copy `.env.example` to `.env`, fill in new paper
   credentials, and run `python3 run_cycle.py`. The historical Railway production target is
   deleted; do not run a local cycle against an account unless a new deployment/account has been
   explicitly provisioned.

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
sequence in `SETUP.md`.
