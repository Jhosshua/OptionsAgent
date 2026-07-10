# MEMORY.md — OptionsAgent

## 2026-07-10 (later) — REMOVED per-position stop losses (paper account, learn the full outcome distribution)

**What was decided:** operator — "this is a paper account, it should not have stop loss limits as
we need to learn as much as we can." So the per-position stop-loss EXITS are removed. Set to `null`
in `config/config.json` (no code change — `harness/exits.py` already treats `stop_loss_pct=None` as
"no stop", and `run_exits.py:_rules_for` passes the config value straight through):
- `spreads.stop_loss_pct: 1.00 -> null`  ← the ONLY one live now (phase = credit_spreads_only)
- `long_options.stop_loss_pct: 0.50 -> null`  (inactive phase)
- `straddles.long_stop_loss_pct: 0.50 -> null`  (inactive phase)

**Why it's safe:** credit spreads are defined-risk — worst case is width minus credit (~$200 on
max_width_usd=2.0), already bounded by the structure, so a stop was never what capped the risk. Long
options/straddles cap at the debit paid. Removing the stop just lets each position run to its true
outcome (50% profit target / 21 DTE close / full max loss) so we see the real win/loss distribution
instead of cutting early. Bonus: the 2x-credit stop is known to hurt credit-spread expectancy (locks
in losses on positions that often recover by expiry).

**What was deliberately NOT touched (these are catastrophe rails, NOT P&L stops):**
- 21 DTE mandatory close (gamma/pin/assignment backstop) — kept.
- Scalper 15:50 ET EOD flatten + theta cut — kept, non-negotiable (ITM 0DTE auto-exercises into
  ~$75k of SPY shares on a $5k account).
- Scalper `stop_loss_pct` (0.30) + `daily_loss_stop_usd` (150): left as-is. The scalper is OFF
  (`OA_SCALP_ENABLED` unset) so it doesn't affect current learning, AND `run_scalp.py:280` does
  `float(cfg_scalp.get("stop_loss_pct", 0.30))` — `null` would CRASH it, not disable it. Removing
  the scalp stop would need a code change to make it Optional; flagged to operator, not done.

**What was rejected:** nulling the scalp stop (would crash), removing DTE/EOD closes (blows the
account, not "learning"). **Verified:** 129/129 tests pass; `_rules_for` builds `stop_loss_pct=None`
for every live strategy. Rollback = set any value back to a float.

## 2026-07-10 — NEW MODE APPROVED: 0DTE ORB scalper (isolated) + Phase-0 probe = GO

**What was decided:** operator wants the Desktop doc `~/Desktop/high_risk_options_strategies.md`
(high-risk 0DTE 1-minute options scalping) implemented into live paper. Locked scope: **extend
OptionsAgent** with an isolated **Opening-Range-Breakout (ORB) 0DTE scalper** (strategy C only for
v1), built **disciplined** (deterministic rules + hard rails + pre-committed success gates), and
the fetched Alpaca data must be **shareable with the other bots**. Full approved plan:
`~/.claude/plans/cozy-strolling-canyon.md`.

**Honest framing (on the record):** buying OTM 0DTE options is the SAME systematic premium-BUYING
that BotResearch flagged as the negative-EV side of the vol risk premium — the exact reason this
bot was pivoted to credit-spread SELLING (2026-07-08 entry below). So the scalper ships as a
**thesis under test**, fully isolated from the live seller, killed by the numbers if the gates fail.

**Isolation contract (never violate):** the seller (`run_cycle.py`/`run_exits.py`, phase
`credit_spreads_only`) stays byte-untouched. Scalper is a parallel system: separate order prefix
`oas-` (vs seller `oa-`), separate registry `data/scalp_positions.jsonl` (seller reads only
`structures.jsonl` and never sees scalp legs), own enable switch `OA_SCALP_ENABLED` (off by
default), own decision log `data/scalp_decisions.jsonl`, own `⚡ SCALP` Discord prefix. Disjoint by
expiry (0DTE vs 21-45 DTE), underlying (SPY/QQQ vs the 13 small-caps), and structure.

**Phase-0 read-only probe (2026-07-10, live paper keys via `railway run`, NO orders) — VERDICT GO:**
- **0DTE IS listed on paper:** SPY 56 + QQQ 50 contracts expiring same-day, ATM quotes present.
- **SIP works on OptionsAgent's OWN keys** (operator confirmed all bots share one Alpaca login that
  holds the SIP/Algo Trader Plus sub; entitlement is login-level). SIP gave 3882 SPY 1-min bars w/
  real volume (8322 on a bar) vs IEX 1573 w/ volume 100. So the scalper fetches SIP with its own
  `ALPACA_API_KEY` — NO key-borrowing. (The existing `stock_daily_bars` IEX default was just
  conservative, not a hard limit.)
- **Option snapshot does NOT expose open interest / volume** (only greeks/IV/quote/trade/symbol) →
  the entry liquidity guard gates on **bid/ask spread only**, OI is best-effort/absent.
- **Greeks/IV came back None** on the 0DTE sample (market was closed) → the 0DTE selector must use
  **spot-based nearest-strike ATM**, never a delta filter. (Design already does this.)
- Account at probe time: equity $3,517, options BP $1,579 (shared w/ the seller), options level 3.
  => scalp `per_trade_usd` must stay SMALL (default ~$250, one-at-a-time) so it can't starve the
  seller's spreads.
- **Auto-exercise** could not be tested read-only; assume ITM 0DTE auto-exercises into 100 shares
  (~$75k notional on SPY at $752) → the mandatory **15:50 ET EOD flatten** rail is non-negotiable.

**Next:** Phase 1 build (off by default), then pre-committed gates + log-only dry run before arming.

## 2026-07-10 (later) — Phase 1 BUILT: the isolated 0DTE ORB scalper (off by default, 102 tests green)

**What shipped (all new, gated behind `OA_SCALP_ENABLED`, seller byte-untouched):**
- `harness/signals_intraday.py` — ET-aware opening range (09:30-09:33), 1-min breakout + RVOL
  surge gate, session VWAP. Pure functions over bar dicts (unit-tested, no network).
- `harness/alpaca_glue.py` — `stock_minute_bars` (SIP, UTC->ET), `stock_latest_price`,
  `option_chain_0dte` (server-side today-expiry + strike-window + type filter; keeps rows even
  when 0DTE greeks are None), `get_order` now returns `filled_avg_price`, `cancel_order`, and a
  `prefix=` arg on `submit_single_leg_order` so scalp orders carry `oas-`.
- `harness/contracts.py` — `ScalpContract` + `select_0dte_atm` (SPOT-nearest strike, spread-only
  liquidity guard; delta unused because 0DTE greeks are None).
- `harness/risk_rails.py` — `ScalpRails` + 6 pure predicates + `active_scalp_rails` (env
  TIGHTEN-only: OA_SCALP_PER_TRADE_USD / _MAX_TRADES / _DAILY_LOSS_USD).
- `harness/scalp_state.py` (atomic per-day state machine on the volume), `scalp_registry.py`
  (append-only `data/scalp_positions.jsonl`, the seller NEVER reads it), `scalp_execution.py`
  (fill-confirmed entry/close, `oas-` prefix), `scalp_exits.py` (EOD-flatten -> stop -> target ->
  theta priority).
- `run_scalp.py` — fused entry+exit state machine, **OA_SCALP_DRY_RUN=1 = log-only shadow**.
- `cron/scalp.sh` (enable + 09:33-15:59 ET window + run-lock + broker-clock gates), crontab line
  (`* 9-15 * * 1-5`), entrypoint secret-allowlist + dir seeding, and a belt-and-suspenders guard
  in `run_exits.py` (drops any live scalp symbol from the seller's reconcile set).

**Isolation (verified):** separate order prefix `oas-` vs seller `oa-`; separate registry file;
own enable switch, decision log (`data/scalp_decisions.jsonl`), and `⚡ SCALP` Discord prefix;
disjoint by expiry (0DTE vs 21-45 DTE) + underlying (SPY/QQQ vs the 13 small-caps) + structure.
The seller's run_cycle/run_exits are behaviorally unchanged. 76 seller tests still pass.

**Two self-review bugs found + fixed before commit:** (1) bar lookback was 90 min, so the
09:30-09:33 range bars aged out by ~11am and afternoon breakouts (valid to 14:30) could never fire
-> now fetch the full session (420 min) AND freeze the range in state (survives a mid-session
redeploy). (2) a transient empty option quote read `bid=0` as a stop-loss and would dump the
position at the tick floor -> now skip the exit on a zero bid unless it's the mandatory EOD flatten.

**Tests:** `tests/test_scalp.py` 26 cases (signals, 0DTE selection, every rail predicate incl.
env-tighten-only, exit priority order, state + registry). Suite 76 -> **102 passing**.

**Pre-committed ARMING GATES (score ~30 trading days after OA_SCALP_ENABLED=true; the Phase-3
decision, logged BEFORE arming per the credit-spread-A/B precedent):**
- Sample floor: >= 30 scalp round-trips before ANY verdict (0DTE is high-variance).
- Win rate >= 45%; average winner >= 1.4x average loser (target +50% vs stop -30% ~ 1.67 structural).
- Net P&L > $0 over the 30-trade sample (on the isolated scalp budget, not the account).
- Daily-loss `HALTED` rail trips on <= ~20% of trading days (else sizing/stop miscalibrated).
- BINARY discipline invariants (must be 100%, ANY violation = disarm immediately regardless of P&L):
  zero 0DTE positions ever held past 15:50 ET / to expiry; zero scalp order ever touched by
  run_exits.py; zero seller position ever touched by the scalp loop.
- Fail any of the above -> revert to OA_SCALP_ENABLED unset (one env flip), same as the seller's
  "flip back = one config key" posture.

**Status:** Phase 1 committed + PUSHED (dee3339, operator-authorized 2026-07-10; Railway redeployed,
scalp stays OFF, seller unaffected). QAExpert review: only 1/5 reviewers finished (shared z.ai key
rate-limited fleet-wide); its testing-reviewer findings are all covered by new driver/execution/
isolation integration tests (tests/test_scalp_driver.py). Data feed = OptionsAgent's own keys on SIP.

## 2026-07-10 (later) — Phase 2 BUILT: shared market-data relay (producer for the fleet)

**Operator ask ("share the same Alpaca data with the other bots") — delivered by mirroring DTA's
proven token-gated HTTP relay pattern.** OptionsAgent becomes a market-data PRODUCER:
- `harness/marketdata_publish.py` — per-minute snapshot of each SPY/QQQ latest 1-min SIP bar +
  computed signals (session VWAP, frozen opening range, latest RVOL, breakout direction) appended to
  `data/marketdata/<ET-date>.jsonl` on the volume (fail-open per symbol, like chain_capture).
- `run_marketdata.py` + `cron/marketdata.sh` — publisher tick every minute RTH, gated on
  `OA_MARKETDATA_ENABLED=true` (off by default; INDEPENDENT of the trading scalper — sharing data is
  useful even with OA_SCALP_ENABLED off).
- `harness/marketdata_relay.py` — token-gated read-only GET server. GET-only, `Bearer` token
  (constant-time compare), filename whitelisted to a bare date (no path traversal), path asserted
  inside the data dir. Launched from `entrypoint.sh` ONLY when `OA_RELAY_TOKEN` is set; port
  `OA_RELAY_PORT` (default 8399). Pure `resolve_request()` is unit-tested; verified end-to-end over a
  real socket (401 no/bad token, 200 ndjson with the token).
- `MARKETDATA_RELAY.md` — consumer doc + a stdlib pull-and-cache snippet other bots drop in.
- Both env keys added to the entrypoint secret allowlist; `data/marketdata/` seeded on boot.

**To activate sharing:** set `OA_MARKETDATA_ENABLED=true` (publish) + `OA_RELAY_TOKEN=<secret>` (serve)
on Railway, expose the port with a domain. Caveat recorded: this is the cross-Railway bridge — a bot on
another service pulls over HTTPS (there is no shared volume between services).

**Tests:** +9 (tests/test_marketdata.py: snapshot builder + relay auth/path/traversal). Suite -> **127
passing**. Remaining: Phase 3 (log-only dry run on a live session, then arm the scalper).

## 2026-07-10 (later) — ARMED LIVE (operator: "flip everything on, it's just paper money")

Operator waived the dry-run: it's paper and the rails bound the paper downside, so we armed live
mid-session instead. Before arming, added an ORPHAN-RECONCILE (`run_scalp._reconcile_orphans`,
commit 7036067): re-adopts any registry-open scalp missing from per-day state (crash/redeploy between
fill and save), closing the one auto-exercise hole. Suite -> **129 passing**.

**Set on Railway (redeployed 11:00 ET):** `OA_SCALP_ENABLED=true`, `OA_MARKETDATA_ENABLED=true`,
`OA_RELAY_TOKEN=<set>`. `OA_SCALP_DRY_RUN` NOT set (real paper trades).

**First-contact CLEAN (11:01-11:02 ET logs):** relay started on :8399; `scalp tick complete dry=False
halted=False trades=0` every minute (no crash/traceback, opening range reconstructed, watching for a
breakout); `marketdata published {SPY:1, QQQ:1}`. The SIGNAL/DATA path is proven live. The ORDER path
(option_chain_0dte -> submit_scalp_entry -> fill confirm) is still UNPROVEN until the first breakout
fires — watch the first `⚡ SCALP BUY` in #options-agent + Railway logs for first-contact order bugs.
Kill switch: `OA_SCALP_ENABLED=false` (one flip). Score the pre-committed gates after ~30 round-trips.

**Data-sharing note:** the relay is running + the feed file is writing, but external bots can only pull
it once a Railway DOMAIN is exposed on port 8399 (operator step). Until then the data is captured on the
volume (readable by anything with volume access).

## 2026-07-08 (later) — BUG FIX: adjusted contracts filtered out of the chain adapter

**What was decided:** the first credit-spreads-only entry cycle (10:15 ET) crashed at order
submit: the selector had picked `CCL1260821P00022500`, an adjusted contract (root `CCL1`, Carnival
corporate action) that Alpaca's market data returns but its trading API rejects as "not active"
(code 42210000). Fix: `alpaca_glue._adapt_chain()` now drops any chain row whose parsed OCC root
differs from the requested underlying, so only standard, tradable contracts ever reach
`harness/contracts.py`. 4 regression tests added (76 total passing). Full writeup in ERRORS.md.
Today's other 2 proposals were lost to the crash (the cycle died on its first submit; mleg orders
are atomic so nothing partial was placed).

**Why:** adjusted contracts don't just slip through, the wheel score actively prefers them (their
quotes look mispriced against the nominal strike). Filtering by root match makes the candidate
pool tradable by construction instead of validating at submit time.

**What was rejected:** validating tradability per-contract via the trading API's
get-option-contract endpoint before submit (extra network call per candidate, and root-mismatch
already exactly identifies the adjusted class); catching the APIError and retrying the next-best
candidate (treats the symptom, keeps untradable rows in the pool).

## 2026-07-08 — STRATEGY PIVOT: premium buyer → defined-risk premium seller (credit spreads only)

**What was decided:** after the day-1 result (8x MARA Aug-07 $13 long puts at $2.18 lost 37.6% of
premium in one session; account $4,343.84 vs $5,000 start, -13.1%), the operator ran the
BotResearch pipeline on this bot (run `BotResearch/runs/optionsagent/20260708-0015`, read artifacts
02/03/04/05 for the full reasoning) and approved its selected change, shipped DIRECTLY to live
paper (operator explicitly rejected the flag-gated shadow-A/B version mid-build: "not behind an
experiment flag, we are shipping it in live paper money"). The change:
1. `config.json` `phase: "credit_spreads_only"` — strategy menu is `credit_spread` only.
2. `spreads.max_width_usd` 5.0 → 2.0 (GLM-skeptic survival condition on $5k: worst case per
   spread ≈ $200 minus credit ≈ 4% of account; three simultaneous gapped spreads ≈ 12%, not 30%).
3. Proposer SYSTEM_PROMPT: seller posture (bullish → put credit spread, bearish → call credit
   spread, never neutral for spreads) + anti-chase rule (never buy options after an extended move).
4. Always-on chain-snapshot capture (`harness/chain_capture.py`, `option_chain_raw` in
   alpaca_glue): full chain (quotes+sizes, trade, IV, greeks) per name per entry cycle →
   `data/chain_snapshots/YYYY-MM-DD/<SYM>.jsonl.gz`, atomic write, fail-open. THE backtesting
   prerequisite; roughly ~1 MB/day gzipped.

**Why:** the day-1 loss was structural, not unlucky: the bot's only mechanically-workable strategy
on a share-less $5k account was buying single options (covered structures need shares, CSPs kept
failing contract match), i.e. always paying the volatility risk premium, at peak fear prices,
IV-blind and spread-blind. Credit spreads flip it to the side of that premium with documented
positive base rates (CBOE put-write indices, tastytrade mechanical studies) while capping worst
case per trade. Full evidence chain in the BotResearch artifacts.

**What was rejected:** long-option band-aids (anti-chase filters alone), IV-rank routing (no IV
history exists yet — that's what snapshot capture fixes), universe rebuild (later), the
flag+shadow-baseline A/B harness (operator chose direct ship; the built-then-reverted version is
in git history at the "pivot" commit's parent diffs if ever wanted).

**30-day review gates (score ~2026-08-19 on decisions.jsonl + structures.jsonl; the numbers
decide):** validity: ≥ 12 executed spreads and no 15-trading-day window with 0 trades (else the
finding is "filters/watchlist too tight", not a strategy verdict). Pass: mean P&L per closed trade
> $0 after subtracting $1.30/contract/leg by hand (Alpaca paper is commission-free, real fees are
not), AND max-loss exits ≤ 25% of closed trades. Hard abort: equity down 25% from $4,343.84 start
(→ ~$3,258) at any point = stop and rethink. Review must also gap-test the book: worst overnight
10% gap-down on all simultaneously-open spreads, plain-language write-up. Honest blow-up mode
(operator accepted): a broad market gap-down through several spreads can still cost 10-20% in one
night; width cap bounds it, nothing removes it.

**Known watch items:** (a) sub-$50 watchlist may not offer $2-wide spreads with positive crossed
credit everywhere — skip reasons `no_spread_matched_criteria` in decisions.jsonl tell us; 0-trade
weeks route to the liquidity/universe backlog items in artifact 05. (b) LLM may propose neutral
credit_spread despite the prompt → skipped with a logged reason, watch frequency. (c) snapshot
capture failures post to Discord but never block the cycle.

## 2026-07-07 (later still) — Closed the submit-vs-fill gap: sweep now checks opening-order status

**What was decided:** before the exit sweep declares a structure's legs "vanished", it now asks the
broker what the OPENING order(s) actually did. New `Structure.order_ids` field (recorded by
run_cycle from the execution result; pre-upgrade events load as an empty list), new pure
`structures.classify_vanished(order_states)`:
- `pending` — an opening order is still working (new/accepted/partially_filled/held/...) → the
  position just hasn't filled; leave the structure open, no alert.
- `never_filled` — every opening order is dead with zero fills (canceled/expired/rejected day
  order) → close quietly with reason `opening_order_never_filled` and a calm info message
  ("no money moved"), NOT an error alert.
- `gone` — something filled (or there is no order info at all) and the position is missing →
  the original loud assignment/manual-close alert, unchanged. No-info stays LOUD by design.

**Why:** structures are recorded on order SUBMISSION, so an unfilled limit order was
indistinguishable from a real assignment — the second way to fire the same false alarm as the
asset_class incident. Flagged in that postmortem; operator said fix and ship.

**Verified:** 66 tests pass (4 new, including the exact 07-07 shape, covered-straddle
one-leg-filled, partial-fill-then-cancel). Deployed; in-container checks: MARA structure loads
(legacy empty order_ids), classifier returns pending/never_filled/gone correctly, full manual
`run_exits.py` sweep ran clean with the MARA put intact.

**What was rejected and why:** polling for fills inside run_cycle (blocking the entry cycle for
minutes, and a fill can land any time before the day order expires) — checking at sweep time is
simpler and self-heals every 20 minutes.


## 2026-07-07 (later) — Exit sweep falsely closed the MARA put 11 minutes after the first fill

**Trigger:** Discord error at 14:40 UTC: "MARA long_put: leg(s) no longer in the account
(assignment, expiry, or manual close). Marked closed; check the account." The position was NOT
gone — 8x MARA 2026-08-07 $13 puts were sitting in the account the whole time (filled 14:29:30,
same second as submission).

**Root cause:** `alpaca_glue.list_positions()` serialized the asset class with `str(p.asset_class)`,
producing `"AssetClass.US_OPTION"`. All three consumers compare against the plain value:
`run_exits.py` (reconcile filter, `"us_option"`), `run_cycle.py` (covered-call owned-shares check,
`"us_equity"`), `harness/positions.py` (exposure calc for the risk rails). The reconcile filter
therefore built an EMPTY live-options set, so the first sweep after the first-ever fill marked the
structure vanished. Side effects until fixed: the put was unmonitored (no profit target / stop /
DTE close), covered calls could never see owned shares, and the rails understated existing exposure.

**What was decided:** route `asset_class` through the existing `_status_str` helper (it was written
for exactly this enum-vs-value problem, the field just never used it). One-line fix + regression
test (`tests/test_alpaca_glue.py`). 62 tests pass. Deployed, verified inside the container:
`list_positions()` now returns `us_option`.

**State repair:** appended a fresh `opened` event for structure `8c74b8ab...` to
`data/structures.jsonl` on the volume (replay of the original event, new ts) AFTER the redeploy,
then ran a manual `run_exits.py` in the container: reconcile kept it intact, no exit triggered,
no false alert. The bogus `closed` event stays in the log (append-only convention).

**What was rejected and why:** hand-editing the jsonl to delete the bogus closed event — the file
is append-only by design; a replayed opened event supersedes it in `load_open()`.

**Known gap flagged (NOT built):** structures are recorded as opened on order SUBMISSION, not fill
(`execute_long_option` returns success right after `submit_order`). A limit order that never fills
would trigger the same false "vanished" alert on the next sweep. Today's fill was instant so this
was not the cause, but it is a real race. Needs an operator decision on the fix shape (e.g. sweep
checks order status before declaring legs vanished).


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
