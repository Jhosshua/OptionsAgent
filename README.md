# OptionsAgent

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

## Status (2026-08-27)

**RETIRED and not deployed.** The archived bot history was analyzed and the 0DTE scalp hard
entry cutoff was tightened to 11:30 ET. The original Railway project, paper account, and webhook
were deleted on 2026-08-02; see `CLAUDE.md` and `OVERFIT_ANALYSIS.md` before any restart.

## Docs map

| File | What it's for |
|---|---|
| `CLAUDE.md` | Read FIRST every session: constraints, locked stack, current status |
| `MEMORY.md` | Decision log: what was decided / why / what was rejected |
| `ERRORS.md` | Approaches that failed and what worked instead |
| `ARCHITECTURE.md` | The original design + rationale (superseded parts are banner-marked) |
| `RESEARCH.md` | The 3-pass deep research every threshold number traces back to |
| `OVERFIT_ANALYSIS.md` | Archived per-day/per-trade replay and the validated narrow strategy change |
| `SETUP.md` | Railway deployment runbook: env vars, redeploy, logs, kill knobs |

## Local dev

1. `pip install -r requirements.txt`
2. `python3 -m pytest tests/` — all tests pass with no network access or keys needed.
3. For a local cycle run: copy `.env.example` to `.env`, fill in values, `python3 run_cycle.py`.
   (Production runs on Railway; local runs share the same paper account, so avoid running a local
   cycle while the Railway cron is live unless you mean to.)

## Config

`config/config.json` holds tunables (strategy phase allowlist, delta/DTE targets, conviction
thresholds, exit targets). The rails in `harness/risk_rails.py` (conviction floor, max positions,
DTE close) live in code by design. Sizing is full-deploy per operator decision 2026-07-03:
conviction-scaled fraction of available buying power, no percentage caps — `OA_MAX_POSITION_USD`
env var is the tighten-only emergency brake.
