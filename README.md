# OptionsAgent

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

## Status

Phase 1 (the options wheel: cash-secured puts + covered calls) is scaffolded and unit-tested.
Not yet run against a live paper account. See `CLAUDE.md`'s "Current build status" section.

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in real values.
3. `python3 -m pytest tests/` — should show all tests passing with no network access needed.
4. `python3 run_cycle.py` — runs one entry-proposal cycle against the paper account (needs `.env`
   filled in first; not yet verified against a live account).

## Config

`config/config.json` holds tunables (rollout phase, delta/DTE targets, conviction thresholds).
Hard risk floors live in `harness/risk_rails.py` instead — by design, so they can't be loosened by
editing a config file. See `CLAUDE.md` permanent constraint #2.
