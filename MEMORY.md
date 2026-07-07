# MEMORY.md — OptionsAgent

## 2026-07-07 — Third 0-trades root cause found + fixed; FIRST TRADE EXECUTED

**What was decided:** add `anthropic==0.104.1` to `requirements.txt`. The package was never in the
container image, so `proposer.py`'s `import anthropic` failed and the bot degraded to no-trade on
every cycle — including today's 10:15 ET cycle, AFTER both 07-06 fixes. The 07-06 verification used
`railway run`, which runs on the Mac (where anthropic is installed globally), so it could not catch
a container-only dependency miss. See ERRORS.md for the full lesson.

**Why:** operator reported "still not seeing anything" for the second day. `railway logs` showed
the smoking gun directly: `anthropic package not installed — proposer degrading to no trade`
(the loud fallback logging added on 07-06 did its job).

**Result (all verified inside the container via `railway ssh`):**
- `import anthropic` OK (0.104.1), proposer smoke call returned HTTP 200.
- Manual `python3 run_cycle.py` (operator-visible catch-up for today, since the 10:15 cron slot had
  already burned on the broken image): 3 proposals → rails filtered 2
  (`no_contract_matched_criteria`, `skipped_no_shares_owned` for a covered call) → 1 executed.
- **FIRST-EVER TRADE: 8x MARA 2026-08-07 $13.00 puts (long_put) @ $2.18 net debit (~$1,744).**
  Confirmed as a real Alpaca position (equity $4,591.84, options BP $3,255.84 after fill).
- Watch item: position marked ~$1,336 right after the $1,744 fill — wide bid/ask on MARA puts means
  the mark sits well below the ask we paid. Not a bug, but if fills consistently land at the ask on
  wide-spread contracts, the contract-selection liquidity criteria may need a spread cap.
- 60 tests still pass. Exit sweeps (every 20 min) now have a real structure to monitor.

**What was rejected and why:** waiting for tomorrow's 10:15 cron as the first post-fix proof —
CLAUDE.md says to watch the first live cycles for first-contact bugs, so running one supervised
manual cycle today was safer than an unattended first run tomorrow.

## 2026-07-06 — First live day: bot ran clean but proposed nothing; TWO bugs found + fixed

**Trigger:** operator asked why the bot "didn't do anything today." Railway logs showed the entry
cycle fired on schedule at 10:15 ET (`cycle all_20260706_141502 … 0 proposal(s) from proposer …
complete`) and all exit sweeps ran fine. Not a crash, not a cron miss, not a Railway problem — the
LLM proposer returned zero proposals. Two independent root causes, both fixed and verified LIVE
(via `railway run` against the real paper account + Fable 5 key; propose-only, no orders placed):

1. **Empty market context (structural — it would have proposed nothing EVERY day).** `run_cycle.py`
   built the proposer bundle with `"context": {}` for every ticker — the LLM got 13 bare symbols
   and nothing else, plus a prompt that says "it is normal to propose nothing," so a conservative
   model proposed nothing. There was no context-builder module at all. FIX: new
   `harness/market_context.py` builds per-ticker context from the Alpaca stock data we already pay
   for (last price, 1/5/20-day % change, 20-day high/low + position in range, volume vs 20-day
   avg), via a new `PaperClient.stock_daily_bars()` (IEX feed, fail-open per ticker). Wired into
   `run_cycle.py`; logs `context built for N/13 underlyings` each cycle. Operator picked
   "Alpaca-only, no new API." Verified live: 13/13 tickers get real data.
2. **`temperature=0` 400'd on claude-fable-5 — hidden by a silent `except`.** `proposer.py`'s
   `client.messages.create(..., temperature=0, ...)` returned HTTP 400 (`temperature is deprecated
   for this model`) EVERY call — Fable 5 removed temperature/top_p/top_k. The `except Exception:
   return stub_proposals()` swallowed it, logging identically to a genuine no-trade. FIX: removed
   the `temperature` param (rails enforce determinism, not sampling); added `log.exception` /
   `log.warning` in the proposer's fallback paths so a broken call is now distinguishable from a
   real no-trade in the logs. Operator approved the error-logging change. See ERRORS.md.
   Verified live post-fix: proposer returned 4 grounded proposals (T/PFE CSPs at 20-day lows, AAL
   covered call after +34%, SOFI bear credit spread at range highs on weak volume).

**Result:** 60 tests pass (52 + 8 new for market_context). Next scheduled entry cycle is Tuesday
2026-07-07 10:15 ET — that's the real end-to-end proof (context → LLM → rails → paper orders).

## 2026-07-03 (session end) — Fully deployed and armed; docs refreshed

**Worked on:** end-to-end deployment day. Research (3 passes) → architecture → build (all 8
strategies) → code review (10 findings fixed) → Railway deploy → keys → sizing rework → watchlist
swap → operator explainer PDF → full docs refresh.

**Completed:**
- Alpaca paper keys live (2nd account, $5k; 1st had $0 equity and was replaced). Clipboard→Railway
  flow, secrets never in the conversation. Auth verified from inside the container.
- Sizing reworked to FULL-DEPLOY (see dedicated entry below).
- Watchlist swapped to 13 liquid sub-$50 names (prices verified live via yfinance the same hour:
  INTC $120, GM $76, UBER $74 were all disqualified): F, T, PFE, VZ, CMCSA, KVUE, SOFI, CCL, AAL,
  WBD, MARA, EWZ, KWEB. Rationale: on $5k the old big-cap list couldn't host a single CSP.
- Operator explainer PDF at `~/Desktop/OptionsAgent-Explained.pdf` (6 pages, zero-knowledge intro
  to options + every step badged CODE vs AI; rendered via headless Chrome from scratchpad HTML).
- Docs: README/CLAUDE/ARCHITECTURE(banner)/ERRORS updated, SETUP.md created (deployment runbook).

**In progress / next session priorities:**
1. **Monday 2026-07-06 10:15 ET = first live cycle.** Watch railway logs + #options-agent.
   Expected first-contact bug shapes are listed in SETUP.md ("First-cycle watch").
2. After the first week: review decisions.jsonl for proposer quality (conviction distribution,
   veto reasons) and exit-sweep behavior on any opened structures.
3. Deferred by design: self-learning/postmortem loops (wait for a track record).

**Decisions made today:** see the three dated entries below (all-phases+Railway override,
full-deploy sizing, plus the original research/architecture decisions).

## 2026-07-03 (latest) — Sizing rework: FULL-DEPLOY (no percentage caps) + real keys live

**What was decided:** operator, after seeing the new paper account's $5,000 balance made the
15%-per-position cap ($750) block nearly everything: "we need to change sizing math, i want to use
all the cash i have in the account, it doesnt have to be all at once, but there should be no cap."
Implemented: position budget = conviction-scaled fraction of AVAILABLE options buying power
(0.60 floor → 30%, 0.85+ → 100%, may take everything). Removed: per-position/per-underlying/
gross-exposure/margin-utilization percentage caps. Kept: 0.60 conviction floor, 6 max positions,
21 DTE close, skip-below-1-contract, covered-call share clamp, broker BP rejection.
`apply_opened_position` now shrinks the next proposal's base within a cycle (this is what makes
"not necessarily all at once" mechanically true). Kill knob added: `OA_MAX_POSITION_USD` env.

**Flagged to operator before implementing:** this supersedes the logged medium-risk profile, and a
max-conviction trade can take the entire account's buying power in one position. Operator's call.

**Also this session:** Alpaca paper keys (2nd account, $5k) set via the clipboard flow (secrets
never entered the conversation), container verified authenticating from inside Railway
(equity $5,000 / options BP $5,000). First account supplied had $0 equity and was replaced.
Market closed 2026-07-03 (July 4 observed) — first live entry window is Monday 2026-07-06 10:15 ET.

## 2026-07-03 (latest) — All strategies built at once + straight to Railway (operator override)

**What was decided:** operator explicitly overrode the logged phased-rollout plan: "i want to build
everything all phases and it needs to go right into railway." All 8 strategy types are now
implemented and enabled (`config.json` phase `"all"`), and deployment goes directly to Railway with
keys in Railway env vars (no local .env validation step first).

**Why:** operator's call after the phase-1 build + code review were done. The phase machinery is
kept so strategies can be switched off by narrowing `phase`.

**What was rejected:** the original validate-each-phase-in-paper-first rollout (ARCHITECTURE.md).
Risk accepted by the operator: all strategies' first live contact happens at once, debugging
through Railway logs.

**Build:** spreads/long-options/straddle selectors + mleg execution + structure registry
(data/structures.jsonl) + fully-wired exit sweep + dividends lookup (yfinance, fail-open).
55 tests passing. Covered straddle = two sequential single-leg orders BY NECESSITY (Alpaca: short
legs must be covered within an mleg order; shares can't be a leg).

**Railway:** project `OptionsAgent` (e312c619-5ac9-4edb-9d57-6ec4d1252ddd), service from GitHub
`Jhosshua/OptionsAgent` main, volume `optionsagent-volume` at `/Users/mo/OptionsAgent/data`.
First deploy failed (expected: railpack ran before Dockerfile/railway.json were pushed).
Cron: entry 10:15-10:27 ET (staggered after DA's 10:00), exits every 20 min market hours; both
gated by the broker clock, fail-closed.

**Deployment completed same day:** container ONLINE on Railway (volume mounted, cron running,
secrets injected). Discord fully wired WITHOUT operator action: created `#options-agent`
(channel id 1522587333822513253) in the StockBot guild via the fleet bot token + a webhook,
set as `DISCORD_WEBHOOK_URL` on Railway, test message posted. ANTHROPIC_API_KEY shared from
the fleet per existing policy; `OA_ANTHROPIC_MODEL=claude-fable-5`.

**ONLY remaining blocker: Alpaca PAPER keys.** Needs a NEW paper account (Alpaca dashboard →
create additional paper account) — sharing DA's or DayTrading's accounts would tangle exposure
math (this bot's rails count ALL account positions; independence is a fleet rule). Checked for
idle fleet accounts: none exist (EarningsVol borrows DayTradingAgent's live account). Until the
keys land, the entry cron fires at 10:15 ET and fails fast at make_client() — no trading, logs
only. When keys arrive: `railway variables --service OptionsAgent --set "ALPACA_API_KEY=..."
--set "ALPACA_SECRET_KEY=..."` then redeploy.

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
