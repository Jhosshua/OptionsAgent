# MEMORY.md — OptionsAgent

## 2026-07-03 (later) — Code review found 10 confirmed bugs in the initial commit; all fixed

**What happened:** operator asked for a bug check right after the initial commit. A high-effort
multi-agent code review (with adversarial verification) confirmed 10 findings. All 10 fixed the
same day; test count went 25 → 36.

**The findings and fixes (worth remembering the patterns):**
1. `run_cycle.py` never called the execution module but logged `outcome: "executed"` and posted
   "Opened ..." to Discord — a phantom track record. Fixed: execution wired
   (`execute_csp`/`execute_covered_call_on_owned_shares`), outcome only says `executed` after a
   successful submit. Same bug class as LiveSwingAgent's 2026-06-29 recap bug (reporting decisions
   as fills) — check for this in any new bot.
2. `option_chain()` read `snap.strike_price/.type/.expiration_date` — none exist on alpaca-py
   0.43.4's OptionsSnapshot (only symbol/quotes/trade/IV/greeks). Fixed: new `harness/occ.py`
   parses strike/expiry/right from the OCC symbol (from the END, digit-safe roots).
3. `float(None)` crash on `options_buying_power` (field exists but is Optional — getattr default
   never fires). Fixed with explicit None handling; missing BP now reads as 0 → rails veto (safe).
4. `max(1, ...)` contract sizing forced 1 contract even when the cap couldn't afford one —
   silently overriding the 15% position cap. Fixed: skip below 1 contract (LiveSwing convention).
5. Covered-call count wasn't clamped to owned share lots → naked calls. Fixed: `min(cap_count,
   owned_shares // 100)`.
6. Short-option exposure measured at premium (`cost_basis`) instead of strike collateral —
   understated CSP exposure ~100x, disabling the portfolio caps for the exact strategy phase 1
   trades. Fixed in `positions.py`: short options = strike×100×|qty|, long = cost basis.
7. Account snapshot went stale within a cycle (6 proposals could jointly deploy 90% against the
   60% cap). Fixed: `apply_opened_position()` updates state after each successful fill.
8. Fill-status compare against `"filled"` vs alpaca-py's `str(OrderStatus.FILLED)` ==
   `'OrderStatus.FILLED'` — confirm loop could never succeed, would strand unhedged shares.
   Fixed: `_status_str()` normalizes to lowercase `.value` at the single point statuses enter.
9. `csp_dte_min` (21) == `dte_close` (21), and the scorer favors shortest DTE → bot would
   preferentially open positions the exit sweep closes the same day. Fixed: 28 in config + a
   code-level guard at the top of `run()` that fires before any credentials are needed.
10. Margin-utilization rail was a no-op (available hardcoded == total). Fixed: utilization is now
    `1 - available_obp/equity` (clamped), computed from the real Alpaca field; fails safe.

**Test-bug note:** one new test (sequential fills vs gross cap) initially failed due to a bug in
the TEST itself (fill attributed to a different symbol than proposed, off-by-one on an index).
Diagnosed by reproducing the exact test body standalone. The production rails were correct.

**Lesson recorded:** the unit-tested pure core was fine; all 10 bugs lived in the untested
integration layer. Next bot: integration-shaped bugs (wrong API field names, enum-str mismatches,
unwired modules) need either a live smoke test or API-shape assertions early, not just pure-logic
tests.

## 2026-07-03 — Research complete, architecture finalized, phase 1 scaffolded

**What was decided:**
- Own Railway project + own Discord channel, both named `OptionsAgent` (not sharing infra with an
  existing bot).
- Alpaca paper trading first, no live-money path yet.
- Risk profile: **medium risk, high conviction**, operator explicitly delegated the exact
  calibration after seeing 3 research passes. Concrete numbers: 0.60 conviction floor (hard gate,
  not just smaller sizing below it), 6 max concurrent positions, 15%/20%/60% position/underlying/
  gross-exposure caps, 60% margin-utilization buffer, 21 DTE mandatory close on short premium.
- Phased strategy rollout: wheel (CSP + covered call) → spreads → long calls/puts → straddles,
  each phase validated in paper trading before the next unlocks.
- Covered straddle's short put requires full internal cash-backing, stricter than Alpaca's own
  margin math — flagged in research as the one strategy with a real "surprise capital call" risk.
- Tech stack mirrors DeterministicAgent exactly: Python, `alpaca-py`, flat JSONL, no DB, same
  LLM-proposes/rails-dispose pattern, LLM defaults to whatever the sibling bots currently run
  (`claude-fable-5` as of this date).

**Why:** operator asked for deep research (200+ sources target, explicitly including Reddit/X) to
inform a from-scratch options bot design, then delegated the final risk calibration to "medium risk
high conviction" rather than specifying exact numbers, trusting the research to back the choices.

**What was rejected:** launching all 7 strategies simultaneously (rejected in favor of the phased
rollout — research confidence isn't uniform across strategies, and simultaneous launch would make
it hard to attribute a paper-trading bug to the right rule).

**Research process note (for future sessions):** the deep-research workflow's automated synthesis
step broke on 2 of the 3 passes (returned a literal placeholder stub instead of real content). Both
times this was caught by inspecting the raw per-claim adversarial-verify votes in the run's journal
directly and hand-reconstructing the findings — do not trust a `deep-research` workflow's top-level
`result.findings` without spot-checking against the raw journal if anything in the summary looks
templated or generic. See RESEARCH.md for the full findings across all 3 passes.

## Phase 1 (wheel) build — this session

Scaffolded `harness/` (env, risk_rails, contracts, exits, positions, alpaca_glue, proposer,
execution, notify, decision_log) plus `run_cycle.py`/`run_exits.py` entry points and config.
25 unit tests written and passing for the pure deterministic logic (risk_rails, contracts, exits,
positions) — these run with no network access and no API keys.

Two real bugs caught and fixed during this build, worth remembering the pattern:
1. `conviction_to_size_frac` originally mapped the conviction floor (0.60) to a 0.0 size fraction,
   which then got vetoed downstream as "no headroom" — a silent contradiction of the architecture
   doc's stated intent ("0.60 → minimum size"). Fixed by adding an explicit `min_size_frac` (0.30)
   that the floor maps to, never zero. Caught by writing the test for it, not by inspection.
2. `run_cycle.py`'s covered-call path tried to read `account_raw[f"{underlying}_cost_basis"]`, a
   field that was never defined anywhere. Fixed to look up the actual equity position from the
   positions list. Caught by re-reading the code right after writing it, not by a test (no test
   covers `run_cycle.py`'s live-wiring path yet — it needs a real paper account to integration-test).

**What's NOT done, don't claim otherwise:** `run_exits.py`'s open-positions builder (needs mark
price + same-strike-opposite quote + dividend calendar per position — currently a documented TODO
stub, the sweep is a no-op). No live paper-account run yet — needs the operator to supply
`ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/`ANTHROPIC_API_KEY`/`DISCORD_WEBHOOK_URL`. No Railway project,
no Discord channel, no cron schedule, no GitHub repo yet.

## Next session priorities

1. Get real Alpaca paper credentials + Anthropic key + Discord webhook into `.env`, run
   `run_cycle.py` against a live paper account for the first time, fix whatever breaks.
2. Wire `run_exits.py`'s open-positions builder (the TODO stub).
3. GitHub repo + Railway project + Discord channel creation.
4. Once phase 1 has a paper track record: unlock phase 2 (spreads).
