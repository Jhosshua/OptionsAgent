# CLAUDE.md — OptionsAgent

> Read this first every session. Then read `MEMORY.md` and `ERRORS.md`.

## What this is

A deterministic options-trading bot on Alpaca, paper trading first. Same governing rule as
DeterministicAgent (`/Users/mo/DeterministicAgent/`): **the LLM proposes, deterministic Python
disposes.** No model output ever places an order directly, and — the options-specific addition —
no model output ever picks a strike, delta, or expiration either. That's the deterministic
contract-selection rail's job (`harness/contracts.py`), not the LLM's.

Full design rationale: `RESEARCH.md` (3 research passes, verified findings + explicit gaps) and
`ARCHITECTURE.md` (the finalized architecture, all decisions locked with the operator 2026-07-03).

## Locked tech stack (do not swap without asking)

- **Language:** Python 3, mirrors DeterministicAgent's style (small pure modules, fail-open data
  adapters, a verifier per module).
- **Broker:** Alpaca paper via `alpaca-py`. PAPER ONLY — `make_client()` refuses any non-paper
  endpoint. Order prefix `oa-`.
- **LLM:** Anthropic, model `claude-fable-5` by default (`OA_ANTHROPIC_MODEL` to override) —
  matches the sibling bots' current control model. Temperature 0. Offline/no-key path returns no
  proposals (conservative, not a guess) so the whole cycle is testable without a live key.
- **Persistence:** flat JSONL under `data/` (`decisions.jsonl`), no DB — matches DA.
- **Deployment:** own Railway project + own Discord channel, both named `OptionsAgent`.

## Permanent constraints (apply every session, flag before breaking)

1. **Paper only.** No live-money path until a sustained positive paper track record exists and the
   operator explicitly initiates the switch. The bot never promotes itself.
2. **Rails live in code, not config.** `harness/risk_rails.py` hard floors are never widened by a
   proposal, by config JSON, or by the model. `config/config.json`'s `OA_*` env overrides may only
   *tighten* a floor (see `active_rails()`), never loosen one.
3. **Risk profile: MEDIUM risk, HIGH conviction** (finalized 2026-07-03, operator delegated the
   calibration after 3 research passes). Concretely: a hard 0.60 conviction floor gates entry
   entirely (below it: no trade, not just a smaller one); 6 max concurrent positions; 15% per-
   position / 20% per-underlying / 60% gross-exposure caps; 60% margin-utilization buffer; 21 DTE
   mandatory close on all short-premium legs. Full rationale in `ARCHITECTURE.md`.
4. **The LLM never picks a strike, delta, or DTE.** It proposes
   `{underlying, strategy_type, direction, conviction, thesis}` only — `harness/proposer.py`'s
   schema enforces this at the type level.
5. **Phased strategy rollout** (`config/config.json`'s `phase` key): wheel (CSP + covered call) →
   spreads → long calls/puts → straddles, each validated in paper trading before the next phase
   turns on. Currently on phase 1 (`wheel`). `harness/risk_rails.py`'s `allowed_strategies` check
   vetoes any strategy_type outside the active phase.
6. **Covered straddle's short put requires full internal cash-backing**, stricter than Alpaca's own
   margin math — the one strategy in scope with a real "surprise capital call" failure mode
   (RESEARCH.md Pass 3). Gets a tighter 10% per-position cap too.
7. **Commit + push after every change** as Jhosshua (see global CLAUDE.md).

## Architecture (the deterministic pipeline)

```
Watchlist (config/universe.txt) + market context   ─┐
                                                      ├→ LLM PROPOSES (no strike/DTE) ─┐
{underlying, strategy_type, direction,               │                                 ▼
 conviction, thesis}                    ┌─────────────────────────────────────────────────┐
                                         │              DETERMINISTIC RAILS                │
                                         │  1. phase/conviction gate, position caps         │
                                         │  2. CONTRACT SELECTION (delta/DTE picker)        │
                                         │  3. execution (mleg / equity-leg sequencing)     │
                                         └─────────────────────────────────────────────────┘
                                                      ▼
                                          paper order(s) → decisions.jsonl
```

A separate, LLM-free exit sweep (`run_exits.py`, `harness/exits.py`) runs on its own schedule
purely to check DTE-close, profit-target, and dividend-assignment triggers on open positions.

## Current build status (2026-07-03)

**Phase 1 (wheel) scaffolded, deterministic core unit-tested, NOT yet run against a live paper
account.** What's done and tested (25 passing tests, no network access needed):
- `harness/risk_rails.py` — conviction floor/scaling, all portfolio caps, phase gating.
- `harness/contracts.py` — CSP/covered-call delta/DTE selection + scoring, roll-cap rule.
- `harness/exits.py` — DTE close, profit target, dividend-assignment check.
- `harness/positions.py` — Alpaca position aggregation into rail-ready account state.

What's written but **not yet integration-tested against a live paper account** (needs
`ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/`ANTHROPIC_API_KEY`/`DISCORD_WEBHOOK_URL` in `.env`):
- `harness/alpaca_glue.py`, `harness/proposer.py`, `harness/execution.py`, `harness/notify.py`.
- `run_cycle.py` (entry cycle) — end-to-end wiring is written, unverified live.
- `run_exits.py` (exit sweep) — **the open-positions builder is a documented TODO stub**, the
  sweep loop is a no-op until that's wired (needs mark-price + same-strike-opposite-side quotes +
  a dividend-calendar lookup per open position).

Not started: credit/debit spreads, long calls/puts, straddles (phases 2-4), self-learning/
postmortem loops (deferred per ARCHITECTURE.md until a paper track record exists), Railway
deployment, Discord channel creation, cron schedule.
