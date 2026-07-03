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

## ⭐ UPDATE 2026-07-03 (later): ALL STRATEGIES LIVE AT ONCE + RAILWAY — supersedes the phased rollout below

Operator decision: build all 4 strategy phases immediately and deploy straight to Railway (no local
`.env` validation step). The phased-rollout machinery is KEPT (config.json `phase` key) so any
strategy family can be switched off by moving to a narrower phase, but `phase` is now `"all"`.

What was added on top of the wheel build:
- `harness/contracts.py`: `select_credit_spread` / `select_debit_spread` (vertical spreads, defined
  width ≤ `spreads.max_width_usd`), `select_long_option` (conviction-scaled delta target within
  0.50-0.70), `select_straddle` (ATM pair, used by both long and covered straddles).
- `harness/execution.py`: mleg executors (credit/debit spread, long straddle — one combo order,
  never sequential legs), `execute_long_option`, `execute_covered_straddle` (two sequential
  single-leg orders BY NECESSITY: Alpaca requires short legs covered within an mleg order and
  shares can't be a leg; a partial fill is reported loudly, never silent).
- `harness/structures.py`: open-structure registry (`data/structures.jsonl`, append-only
  opened/closed events) — the exit sweep's source of truth for what each flat position IS.
  `reconcile()` detects vanished legs (assignment/expiry/manual) and alerts, never silently drops.
- `harness/exits.py`: generalized to two families — short premium (profit % of credit, optional
  stop, 21 DTE, dividend check on short calls) and long (profit/stop % of debit, 21 DTE).
- `harness/dividends.py`: yfinance ex-dividend lookup, FAIL-OPEN (missing feed = no early warning,
  never a crash). Note: quarterly amount approximated as dividendRate/4 when calendar lacks it.
- `run_exits.py`: fully wired (was a stub) — load registry → reconcile → quotes → evaluate →
  unwind orders (mleg reverse for combos) → estimated P&L → Discord.
- Railway: `Dockerfile` + `entrypoint.sh` + `cron/` (entry 10:15-10:27 ET once/day, exit sweep
  every 20 min market hours, both broker-clock-gated fail-closed) + `railway.json`, mirroring the
  DeterministicAgent-Railway pattern. Railway project `OptionsAgent`
  (e312c619-5ac9-4edb-9d57-6ec4d1252ddd), volume at `/Users/mo/OptionsAgent/data`.
  ⚠️ entrypoint.sh `secret_keys` allowlist = the fleet's known 3-touch-point gotcha; a new key
  must be added to code, Railway vars, AND that list.

## Current build status (2026-07-03, post code-review fixes)

**Phase 1 (wheel) scaffolded, 10 code-review findings fixed, 36 passing unit tests, NOT yet run
against a live paper account.** A high-effort multi-agent code review of the initial commit found
10 confirmed bugs (all fixed same day, see MEMORY.md for the list): the worst were run_cycle never
calling the execution module while logging trades as "executed", the option-chain adapter reading
snapshot fields that don't exist in alpaca-py 0.43.4, a forced 1-contract minimum that overrode the
position cap, and short-put exposure measured at premium instead of collateral (~100x understated).

Done and unit-tested (36 tests, no network/keys needed):
- `harness/risk_rails.py` — conviction floor/scaling, all portfolio caps, phase gating,
  equity-based margin utilization (fails safe on missing buying power), `apply_opened_position`
  for intra-cycle state updates so one cycle can't jointly breach the caps.
- `harness/contracts.py` — CSP/covered-call delta/DTE selection + scoring, roll-cap rule.
- `harness/exits.py` — DTE close, profit target, dividend-assignment check.
- `harness/positions.py` — exposure = strike collateral for short options (never premium),
  cost basis for long; conservative by construction.
- `harness/occ.py` — OCC symbol parser (parse from the END, roots with digits are safe); the
  chain adapter and positions both depend on it because alpaca-py snapshots expose no
  strike/expiry/right fields.

Written but **not yet integration-tested against a live paper account** (needs
`ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/`ANTHROPIC_API_KEY`/`DISCORD_WEBHOOK_URL` in `.env`):
- `harness/alpaca_glue.py`, `harness/proposer.py`, `harness/execution.py`, `harness/notify.py`.
- `run_cycle.py` — execution IS now wired (CSP + covered-call-on-owned-shares), sizing skips
  below one contract, covered calls clamp to owned share lots, outcomes are truthful
  (`executed` only after a successful submit; `execution_failed: ...` otherwise). A config
  guard at the top of `run()` rejects any entry-DTE window that doesn't clear `dte_close`.
- `run_exits.py` — **the open-positions builder is still a documented TODO stub**, the sweep
  loop is a no-op until that's wired (needs mark-price + same-strike-opposite-side quotes +
  a dividend-calendar lookup per open position).

Not started (BY DESIGN, per operator 2026-07-03 — do not build these yet): credit/debit spreads,
long calls/puts, straddles (phases 2-4), self-learning/postmortem loops (deferred until a paper
track record exists), Railway deployment, Discord channel creation, cron schedule.
