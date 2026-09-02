# CLAUDE.md — OptionsAgent

> **CURRENT OPERATING MODE — 2026-08-28 (night), hosting updated 09-01:** OptionsAgent is a
> paper-trading robot (on Railway since 09-01, see CURRENT SETUP below) with TWO engines on a $100,000 Alpaca paper account:
> (1) the credit-spread seller (the AI proposer, DeepSeek API since 09-01, proposes;
> rails dispose, once daily 10:15-10:27 ET) and (2) the EQUITY intraday scalper (run_scalp_equity.py,
> mined rules, shares only, every minute 09:45-15:55 ET, cron/equity_scalp.sh).
> The 0DTE OPTION scalper was RETIRED tonight on 6-month evidence (no positive
> expectancy in 16,384 configs). Stock data runs through the hosted AlpacaRelay
> proxy (OA_DATA_URL; OA_DATA_KEY_ID is a relay token, no direct SIP from this
> repo — 2026-08-31); Public.com is options-only sidecar data; Alpaca
> is paper-only execution. The dashboard was reset to the 08-28 activation date.
> See RESEARCH_SCALP_6MO.md.

> **CURRENT SETUP — 2026-09-01:** OptionsAgent runs on **Railway**, in project
> `OptionsAgent` (`cc393b70-4ef5-48d5-8299-253b914cc219`), service `OptionsAgent`,
> region sfo. Linux cron in the container is the scheduler; the volume at
> `/Users/mo/OptionsAgent/data` holds all state. Proposals come from the
> **DeepSeek API** (`harness/proposer.py`, `OA_LLM_PROVIDER=deepseek`,
> `DEEPSEEK_API_KEY`, model `deepseek-v4-pro`) since 2026-09-01 (evening). The
> Claude Code CLI is NOT in the image any more: its login expired twice
> ("Not logged in · Please run /login", 08-31 and 09-01) and each time the
> once-a-day cycle failed closed and the trading day was lost. Every AI call is
> journaled as a `proposer_result` row in `data/decisions.jsonl` and shown on
> the dashboard, so a dead model can no longer pass for a quiet market.
> Public.com is read-only options data, AlpacaRelay serves stock bars, Alpaca is
> the paper execution broker. **Railway variables are authoritative**, and
> `entrypoint.sh` writes them into `.env` at boot because cron does not inherit
> the container environment. Alerts go to Discord `#options-agent`.
> Dashboard: https://optionsagent-production.up.railway.app
> Redeploy with `railway up --service OptionsAgent`. The Mac's launchd plist and
> user-crontab lines are disabled; do not restart this bot locally.

The retirement notes below describe the FIRST Railway deployment (deleted
2026-08-02) and are historical. They do not describe the current one.

> ## HISTORICAL RETIREMENT 2026-08-02 — superseded by the local reactivation note above.
>
> Shut down at the operator's instruction. **The Railway project is deleted** (`e312c619`, purge
> scheduled 2026-08-04) along with its volume, every app env var (Alpaca, Anthropic, Discord) is
> gone, the Discord webhook is deleted at the API, and the Alpaca paper account is being closed.
> There is no deployment target left — bringing this back means creating a new Railway project,
> service and volume from scratch. The volume data is archived in
> `backups/volume_2026-08-02.tar.gz` (md5-verified) and extracted into `data/`.
>
> Do not "fix", redeploy, or restart anything here without the operator explicitly saying to bring
> the bot back. Read `MEMORY.md` 2026-08-02 first — it lists exactly what has to be re-created.
> Everything below describes how the bot worked while it was live.

> **HISTORICAL 2026-08-27 research update:** `OVERFIT_ANALYSIS.md`,
> `research_scalp_history.py`, and `research_credit_spread_history.py` document the archived
> trade study. The 0DTE hard entry cutoff (11:30 ET) and two-trade daily cap remain in
> `harness/risk_rails.py`; the multi-day seller now has an explicitly requested, hard
> in-sample winner profile in the same module. This is local and not deployed. Do not claim a
> restart or deployment: the old Railway target and credentials were deleted.

> **HISTORICAL 2026-08-27 Public data update:** `harness/public_marketdata.py` is an optional,
> read-only market-data sidecar. It is now enabled locally; Alpaca remains the paper
> execution/account broker. Its secret stays in the local `.env` only.

> **2026-09-01 (evening) dashboard rework:** the Research tab and `/api/research` are GONE (they
> replayed an always-empty file). `/api/summary.seller_cycle`, `/api/system.proposer` and
> `/api/risk.rails.allowed_profiles` come from `_seller_cycle_report()` / `_allowed_profiles()`,
> which read the latest cycle's `proposer_result` + `decision` rows and the SAME rule tuple the
> rail enforces. The sidebar is sticky, sections load independently (one failed endpoint no
> longer blanks the page), and the page refreshes every 60 s. Any new "is the seller alive"
> view must read the `proposer_result` row, not the mere presence of a `cycle_start`.

> **2026-09-01 dashboard update:** the dashboard reads BOTH engines. Any new P/L
> view must merge `data/structures.jsonl` (seller) AND
> `data/equity_scalp_decisions.jsonl` + `data/equity_scalp_state/<ET-date>.json`
> (scalper) — reading one alone silently reports a flat, empty day. Trading days
> bucket by ET, not UTC. A missing scalper day-state file renders as "not
> running", never as 0.

> **2026-08-27 dashboard update:** `dashboard/` and `harness/dashboard_server.py` are a
> local-only, read-only observer. It uses a background cache and a separate supervisor;
> `OA_TRADING_ENABLED` defaults false in templates and is verified from the local `.env` before
> paper cron may act. Never link or deploy this repo to `tqqq-qqq-paperbot`.

> **2026-09-01 (night) HACKATHON MODE — read before touching the seller or the broker adapter:**
> Three env switches are set on Railway for the Alpaca hackathon window (see README "Alpaca AI
> Trading Agents Hackathon" and MEMORY.md 2026-09-01 night):
> `OA_CREDIT_SPREAD_GATE=research_rules` (the frozen CCL/SOFI/F winner table is BYPASSED; the
> picker's delta/DTE/width rules still bind), `OA_MAX_POSITION_USD=3000` (the per-position cap that
> makes the open gate survivable on $100k; never unset one without the other), and
> `OA_BROKER_TRANSPORT=cli` (every account/position/order/clock call goes through the official
> Alpaca CLI, `harness/alpaca_cli.py`, journaled to `data/cli_calls.jsonl`, fail-closed, no SDK
> fallback). Constraint 2 below ("rails only tighten") has exactly this one operator-approved
> exception; the default of the gate env is the strict mode. After the hackathon, delete the gate
> var to return to the research posture.

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
- **LLM:** the DeepSeek chat-completions API (`harness/proposer.py`, `OA_LLM_PROVIDER=deepseek`,
  `DEEPSEEK_API_KEY`, `OA_DEEPSEEK_MODEL`, default `deepseek-v4-pro`, JSON-object mode, temperature
  0). One call per trading day with the whole watchlist in one bundle; ~1-2k tokens in, up to
  ~5k out, ~40-80 s. Transient errors retry 3x; config errors (bad/missing key) do not. Any
  failure returns no proposals (conservative, not a guess) and pages Discord once. The Claude Code
  CLI path (`OA_LLM_PROVIDER=claude_cli`) still exists for the Mac only.
- **Persistence:** flat JSONL under `data/` (`decisions.jsonl`), no DB — matches DA.
- **Runtime:** Railway (Linux cron in the container, state on the volume) + the public read-only
  dashboard. The Mac crontab lines are commented out; do not run the bot locally as well.

## Permanent constraints (apply every session, flag before breaking)

1. **Paper only.** No live-money path until a sustained positive paper track record exists and the
   operator explicitly initiates the switch. The bot never promotes itself.
2. **Rails live in code, not config.** `harness/risk_rails.py` hard floors are never widened by a
   proposal, by config JSON, or by the model. `config/config.json`'s `OA_*` env overrides may only
   *tighten* a floor (see `active_rails()`), never loosen one.
3. **Risk profile: FULL-DEPLOY, HIGH conviction** (operator 2026-07-03, SUPERSEDES the earlier
   medium-risk percentage caps — "use all the cash, not necessarily all at once, no cap").
   Position budget = conviction-scaled fraction of AVAILABLE options buying power: 0.60 conviction
   (the hard entry floor, unchanged) → 30% of what's available, 0.85+ → 100% (a max-conviction
   trade MAY take all remaining buying power; that is deliberate policy). No per-position,
   per-underlying, gross-exposure, or margin-utilization percentage caps. Still in force: the
   0.60 floor, 6 max concurrent positions, 21 DTE close, skip-below-1-contract, covered-call
   share clamp, Alpaca's own buying-power rejection as broker-side backstop. Kill knob:
   `OA_MAX_POSITION_USD` env (absolute per-position ceiling, tighten-only). The original
   medium-risk rationale in `ARCHITECTURE.md` is historical.
4. **The LLM never picks a strike, delta, or DTE.** It proposes
   `{underlying, strategy_type, direction, conviction, thesis}` only — `harness/proposer.py`'s
   schema enforces this at the type level.
5. **The `phase` key gates the strategy menu** (`config/config.json`). Currently
   `credit_spreads_only` (operator 2026-07-08, see banner above). `harness/risk_rails.py`'s
   `allowed_strategies` check vetoes any strategy_type outside the active phase.
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

## ⭐ UPDATE 2026-07-08: CREDIT-SPREADS-ONLY PIVOT — supersedes "all strategies" below

Operator decision after BotResearch run 20260708-0015 (triggered by the day-1 MARA long-put loss,
-37.6% of premium in one session, account -13.1%): the bot flips from premium BUYER to defined-risk
premium SELLER. Shipped straight to live paper (operator: no experiment flag, no shadow arm).

- `config.json`: `phase: "credit_spreads_only"` (new phase, menu = `credit_spread` only) and
  `spreads.max_width_usd: 2.0` (was 5.0) — the skeptic-bot survival condition on $5k: max loss per
  spread ~$200 minus credit (~4% of account). Flip back = one config key.
- `harness/proposer.py` SYSTEM_PROMPT now carries the seller posture: bullish → put credit spread,
  bearish → call credit spread (never neutral for spreads), and an anti-chase rule — never buy
  options after an extended move (the day-1 mistake).
- **Chain-snapshot capture is LIVE and always-on** (`harness/chain_capture.py` +
  `alpaca_glue.option_chain_raw`): every entry cycle persists each watchlist name's full chain
  (quotes+sizes, last trade, IV, all greeks) to `data/chain_snapshots/YYYY-MM-DD/<SYM>.jsonl.gz`
  on the Railway volume, fail-open. This is the prerequisite for ever building a backtester or an
  IV-rank signal; do not remove it.
- 30-day review gates are logged in MEMORY.md (2026-07-08 entry) — score them around 2026-08-19,
  and `tests/test_pivot_credit_spreads.py` cements the pivot (a phase/width revert fails tests
  until consciously changed).
- Exits for credit spreads were already live (short-premium family: 50% profit target, 2x-credit
  stop, 21 DTE close) — unchanged.

## ⭐ UPDATE 2026-07-11: JULY 10 EXECUTION SAFEGUARDS

The July 10 replay found two quote/signal timing failures and one exit-policy mismatch. Fixed in
the deterministic layer:

- Credit-spread 2x-credit stops are evaluated only from 10:00 ET and must persist across two
  consecutive 20-minute sweeps. A recovered quote resets confirmation. This prevents a single
  wide opening combo quote from forcing another VZ-style liquidation.
- 0DTE ORB entries now require the immediately following one-minute bar to remain outside the
  opening range and on the matching side of session VWAP. Stale confirmations expire.
- While the confirmed underlying breakout remains intact, the scalper suppresses its ordinary
  30% premium stop and 15-minute theta cut, but retains a 60% catastrophic premium stop, the 50%
  profit target, and mandatory 15:50 ET flatten. Each direction may be traded once per symbol/day.

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

## ⭐ HISTORICAL STATUS (2026-07-03 end of day) — superseded by the local operating mode above

- **LIVE on Railway**: project `OptionsAgent` (e312c619-5ac9-4edb-9d57-6ec4d1252ddd), container
  Online, volume at `/Users/mo/OptionsAgent/data`, verified from INSIDE the container (auth +
  account reads + current code). Deploys auto-trigger on push to `main`.
- **Alpaca paper keys set** (2nd account the operator created; the 1st had $0 equity): equity
  $5,000 / options BP $5,000, verified. Keys went clipboard→Railway via `pbpaste`, never through
  the conversation. `ALPACA_PAPER=true`; `make_client()` refuses non-paper regardless.
- **Sizing = FULL-DEPLOY** (see constraint 3, rewritten): conviction-scaled fraction of available
  BP, no percentage caps, `OA_MAX_POSITION_USD` env = tighten-only brake.
- **Watchlist = 13 liquid sub-$50 names** (F, T, PFE, VZ, CMCSA, KVUE, SOFI, CCL, AAL, WBD, MARA,
  EWZ, KWEB — prices verified live 2026-07-03) so CSPs are affordable on $5k. Old big-cap list
  (AAPL/MSFT/SPY/...) couldn't host a single CSP at this equity.
- **Discord `#options-agent`** (channel 1522587333822513253, StockBot guild) + webhook — created
  via the fleet bot token, zero operator action. Deploy announcements, trades, passes, closes,
  errors all post there.
- **Cron**: entry 10:15-10:27 ET once/day (staggered after DA's 10:00), exit sweep every 20 min
  9-16h ET — both self-gate on the broker market clock, fail-closed.
- **First live cycle: Monday 2026-07-06 10:15 ET** (2026-07-03 was the observed July-4th holiday).
  ⚠️ The integration layer has NEVER touched the live API (operator chose straight-to-Railway) —
  watch the first cycles' Railway logs + #options-agent for first-contact bugs; fix loudly.
- Operator-facing explainer PDF: `~/Desktop/OptionsAgent-Explained.pdf` (regen source lives in the
  session scratchpad; rebuild via headless Chrome if it needs updating).
- Tests: 52 passing (pure deterministic core; the integration layer is what Monday shakes out).

## Current build status (2026-07-03, post code-review fixes — HISTORICAL, see banner above)

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

Written but **not yet integration-tested against a live paper account** (historical note; the
current local integration uses Alpaca/Public credentials and Claude Code CLI authentication):
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
