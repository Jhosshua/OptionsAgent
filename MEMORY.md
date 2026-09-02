# MEMORY.md — OptionsAgent

## 2026-09-01 (night) — HACKATHON GO-LIVE: gate opened + $3k cap + Alpaca CLI in the order path

**Context:** submitting to the lablab × Alpaca "AI Trading Agents Hackathon"
(deadline Fri 09-04 11:00 ET; judges read total equity EOD Thu 09-03 on a fresh
$100k paper account; the agent must use Alpaca's Trading API through the
official MCP server or CLI and must trade options). Research + todo list:
`HACKATHON_SUBMISSION_PLAN.md`. Account PA371G5THNUO qualifies (created 08-30,
$100k, only this bot has traded it) but had **0 option fills**: all 14 seller
proposals since 08-28 died at the contract picker or at the frozen winner-profile
gate, and the 08-31/09-01 cycles were lost to the Claude CLI login bug. Neither
this repo nor the wheel bot used MCP or CLI.

**Decided (operator, "go live immediately, no shadow"):**
1. `OA_CREDIT_SPREAD_GATE=research_rules` (new env, `risk_rails.active_credit_spread_gate()`
   + `credit_spread_gate_decision()`): the `_CREDIT_SPREAD_OVERFIT_RULES` table is bypassed;
   a picker-approved spread on ANY watchlist name may open. Default and any junk value =
   `winner_profile` (strict). The reason string names the mode; every decision row carries
   `judged_against` (gate mode, cap, concurrency, spread rules) so the row can be audited.
2. `OA_MAX_POSITION_USD=3000` on Railway (existing tighten-only knob, was UNSET). Without it a
   0.62-conviction idea on $100k options BP sizes to 35.6% = $35.6k = **178 contracts** of a
   $2 spread (`run_cycle.py` `contracts = position_cap_usd / (width*100)`). With it: 15
   contracts, worst case ≈ $3,000 − credit per position, 6 slots ⇒ ≈ $18k. The two changes
   ship together on purpose; `tests/test_credit_spread_gate.py::test_cap_and_gate_arithmetic_on_a_100k_account`
   pins the arithmetic.
3. `OA_BROKER_TRANSPORT=cli` (new `harness/alpaca_cli.py`): `PaperClient.account_state`,
   `list_positions`, `submit_single_leg_order`, `submit_equity_order`, `submit_mleg_order`,
   `get_order`, `cancel_order`, `market_is_open` run `alpaca … -q` as a subprocess with an
   explicit env (only PATH/HOME + this client's two keys; `ALPACA_PROFILE` cannot leak),
   parse JSON, and journal every call to `data/cli_calls.jsonl`. **Fail-closed, no SDK
   fallback** (a silent fallback would make the hackathon claim false). Net-credit limits use
   the `--limit-price=-0.30` equals form: cobra would read a bare `-0.30` as a flag. Dockerfile
   installs Alpaca CLI v0.0.14 (linux_amd64, sha256 pinned `6c82ef31…ba66`, verified).
   Market data untouched (Public.com chains, AlpacaRelay bars).

**Verified:** 262 tests (was 233). Real CLI smoke on the Mac through the adapter
(account/positions/clock, 120–170 ms each, journal rows written). `--dry-run`
mleg produced the exact Alpaca body. Mutation checks: forcing `winner_profile`
→ 3 tests fail; dropping the cap → 2 fail; two-token `--limit-price` → 2 fail;
swallowing a non-zero CLI exit → 1 fails. Docker daemon was down locally, so the
image build is proven by the Railway build + in-container `alpaca version`.

**Adversarial review before deploy (subagent, read-only) found three day-one
problems in the plan; all fixed and pinned by tests before the first deploy:**
- P0 *The open gate would have booked spreads already past their own stop.* Entry
  credit is short.BID − long.ASK, the exit sweep prices the unwind at short.ASK −
  long.BID, so the bid/ask is paid twice and the 2x-credit stop fires at t=0 on any
  spread whose quoted width exceeds its credit. Replay of the 09-01 chain
  snapshots: 8 of 23 pickable shapes were past the stop on the quotes they were
  picked from (WBD bull credit 0.07 / unwind 0.45 ⇒ −$1,140 on 30 contracts).
  Fix: research_rules now requires credit ≥ $0.10 and unwind-now < 1.5× credit
  (`RESEARCH_RULES_MIN_CREDIT`, `RESEARCH_RULES_MAX_CLOSE_COST_X`); run_cycle passes
  `close_cost_now`; None fails closed. Replay after the fix: 5 of 26 admitted
  (CCL bull, MARA bull/bear, T bull/bear), **0 past the stop**.
- P0 *No dedupe.* The proposer accepts any string and any count, nothing read the
  open-structure registry, so "CCL bullish" twice or an off-list NVDA each got a
  full $3k. Fix: `run_cycle.proposal_skip_reason()` — universe only, one per
  underlying per cycle, skip names already open; `apply_opened_position` now counts
  legs like the broker does. Plus `research_rules_missing_cap()`: a cycle REFUSES
  to run in research_rules mode if `OA_MAX_POSITION_USD` is unset or unparsable
  ("3,000" would have silently meant no cap ⇒ 178 contracts).
- P0 *The equity scalper bypassed the adapter* (`_trading_client().submit_order`
  direct), so "orders via CLI" would have been false. Fix: `_submit_market` →
  `client.submit_equity_order(prefix="oae-")`; entries fail closed, the 15:50
  flatten alone may fall back to the SDK, journaled as `eq_cli_fallback` and paged.
- P1 *Fills.* Entries were booked at the requested count and exits marked
  "closed" on submission. Fix: `execution.confirm_fill()` polls ≤30 s, cancels
  the remainder, books the FILLED count (entry: `unfilled_cancelled` outcome and
  no structure; exit: `exit_unfilled` row and the structure stays open; partial
  unwind re-registers the remainder as `<id>-r<n>`). CLI submit failures are
  reconciled via `order get-by-client-id` before being declared failures; the
  CLI's own `--timeout` is set 10 s under the subprocess timeout.
- Noted, not fixed: `exits.HAS_SHORT_CALL` omits bearish call spreads (no ex-div
  check; irrelevant before Oct expiries). How Alpaca marks an open spread in
  `equity` is unverified — compare `position list` current_price vs mid on 09-02.

**Rejected:** MCP server as the transport (needs an MCP client in Python plus a
long-running server in the container; the CLI is one binary and one
subprocess). Loosening the picker's delta/DTE/width rules (the gate was the
lever; the picker is research). Opening the phase to CSPs (a CSP's collateral
is strike×100 and the same %-of-BP sizer would have sized in the tens of
thousands).

**DEPLOYED 2026-09-01 23:00 ET** (Railway deployment 416c1fea, commit db43c52). Verified
from inside the container: `/usr/local/bin/alpaca` 0.0.14; the three vars present in the cron
`.env`; `make_client()` on the CLI path read account ($100,034.43), positions ([]) and clock in
~220 ms each with journal rows in `data/cli_calls.jsonl`; a `--dry-run` mleg produced the exact
Alpaca body; cron running with `/etc/cron.d/optionsagent`. Public `/api/risk` reports
gate=research_rules, cap=$3,000, transport=cli.

**Submission pack (09-01 23:20 ET):** repo flipped PUBLIC with MIT (history + backup tarball scanned clean first). `submission/build.py` renders everything from live numbers (Alpaca CLI + dashboard API): cover.png, 9-slide PDF, 1-page write-up PDF, and a narrated MP4 (macOS `say` Samantha + ffmpeg, 4:08). Re-run Thursday after the close. Form copy in `submission/SUBMISSION.md` (short desc 254/255 chars). Only the team leader can submit on lablab.

**Video v3 pipeline (09-02 ~01:10 ET), after the operator rejected v2 ("sound cuts off, slow, boring"):**
`submission/video/make_scenes.py` emits nine animated 1920x1080 HTML artboards (Nunito Sans + the dashboard's
tokens; CSS animations with fill-mode both), which double as the design canvas
(https://claude.ai/code/artifact/b53639dd-0a0a-4d5b-97d4-570f4b6b8f34) and as the video source:
`submission/video/render.py` drives the debug Chrome on :9222 over CDP (Host header must be `localhost:9222`),
pauses every animation and seeks `currentTime` per frame at 24 fps, captures JPEG frames, then ffmpeg builds
per-scene clips with the audio resampled to 48 kHz stereo, a 120–300 ms lead-in, and `apad=whole_dur` +
`-t` (the v2 cut-off was `-shortest`), crossfades only around the app shots, `loudnorm` on the mix.
Narration = edge-tts `en-US-AndrewMultilingualNeural` at +12% (free Microsoft neural voice; `say` was robotic).
A design-review subagent rewrote the script PM-style (customer = a developer pointing an LLM at an Alpaca
account; hook = the real "178 contracts on one idea" sizing number), one idea per scene, dim-mask highlights,
22-dot proof visual, no count-ups. It also asked to CUT the alpaca mascot (judges are Alpaca staff); operator
had asked for it, so it stays restrained in scenes 1 and 9 only. Scene 5's screenshot still shows an EMPTY
"AI trade ideas" card: re-shoot after the 09-02 10:15 cycle and re-run make_scenes + render.

**Video v4 (09-02 ~01:40 ET):** operator rejected v3 (highlight drifted under the zoom, big zero over the dots, only
one engine explained, no customer vignette). Fixes: the focus ring lives inside the zoomed layer; a
developer+LLM vignette opens the video; engine two has its own scene; a code-reading subagent produced
"How Wingspan works today (from the code)" and every claim in the video, one-pager and README was aligned to it
(6 slots = LEGS so 3 spreads max ≈ $9k, stop needs two sweeps after 10:00, the scalper's flatten is the one
journaled SDK fallback, 0DTE scalper wired but OFF, market data never via the CLI). Reveals now lock to the
spoken word: `render.py` uses edge-tts WordBoundary events (`Communicate(..., boundary="WordBoundary")`; the
CLI has no per-word option in 7.2.8) and sets `--c-<cue>` CSS vars per scene. The one-pager is an artboard
(`OnePager.dc.html`, Letter) printed via CDP `Page.printToPDF`, so it matches the video's design. Replay count
corrected to 23 pickable shapes (my reproducible replay; the first reviewer said 22). Scene 6 still shows an
EMPTY ideas card: reshoot after the 10:15 cycle and re-run make_scenes + render + print_pdf.

**Watch on 09-02:** the 10:15 ET cycle's `judged_against` row, the first
`cli_calls.jsonl` rows from the container, and whether any spread actually
fills (the picker still binds; a quiet-IV day can legitimately yield zero).

## 2026-09-01 — "Seller, last cycle" tile renamed "AI trade ideas" + info tooltip

**Decided:** the Overview tile "Seller, last cycle / — proposals / AI call not
journaled for this cycle" is now "AI trade ideas" with an info icon whose
tooltip explains it in plain words (each morning the credit-spread engine asks
the AI for ideas, the rails pick which become trades, and the tile shows how
many came back and whether the call worked). The lower card is "AI trade ideas
· latest run" with the same icon; its rows read "AI call / Ideas proposed /
Traded" and the list is "What happened to the ideas". Status copy:
"No run yet" · "Last run predates AI logging · check back after the next daily
run" · "AI call failed, nothing traded (safe) · <error>" · "AI responded in Xs
[after N tries]". Files: `dashboard/index.html`, `dashboard/app.js`,
`dashboard/app.css` (`.info`, `.tooltip`, CSS-only, hover + keyboard focus).

**Why:** operator: "its not user friendly idk what its even for". The label
assumed you knew "seller" = credit-spread engine and "cycle" = its daily run,
a dash next to "proposals" looked broken instead of unknown, and "not
journaled" is developer language. The unknown state still never renders as 0.

**Rejected:** putting "10:15 ET" in the tile copy. The schedule is a cron
constant that has moved before; the tooltip says "each morning after the open"
so the text cannot rot.

**Staleness sweep, same evening:** CLAUDE.md opened with "a local
paper-trading robot" while its next paragraph said Railway (fixed); SETUP.md
and DASHBOARD_BUILD_PLAN.md still named the card "AI proposer" (fixed); README
dashboard section now records the Wingspan brand. Suite 233 passed. Deployed
with `railway up --service OptionsAgent`.

## 2026-09-01 — DASHBOARD BRAND: "Wingspan" wordmark + W-wing mark

**Decided:** the dashboard's logo and name are now **Wingspan** (wordmark) with
a W-shaped mark made of two option-spread payoff diagrams, white on the existing
`--accent` red. Applied in `dashboard/index.html` (sidebar brand block, footer
"Wingspan · OptionsAgent v1.1.0", tab title "Wingspan · OptionsAgent", inline
SVG favicon) and two CSS lines in `dashboard/app.css`. Nothing outside the
dashboard was renamed: repo, Railway service, Discord channel and server
version string all stay OptionsAgent.

**Why:** the old brand was a bare "↗" glyph in a red square plus the literal
project name. Wingspan keeps the current red, Nunito Sans and rounded-card
theme untouched and means something to a spread trader (iron condor = bird,
strike width = wings). Operator picked it from three directions on a design
canvas ("implement wingspan").

**Rejected:** Thetafox (theta glyph with fox ears, orange; would have changed
the accent color) and Ratchet (dark, acid-yellow staircase mark; a full
restyle and a "never loses" promise a paper bot has not earned). Both remain
on page two of the canvas. Working files: `dashboard/brand/`.

**Verified:** full suite 233 passed; page rendered in Chrome from a static
server, mark crisp at 34px and 14px, favicon shows in the tab. Deployed to
Railway the same evening on the operator's "push it now" (`railway up
--service OptionsAgent`); the live page served the Wingspan markup ~50s later.

## 2026-09-01 — DASHBOARD UI AUDIT: THE ENGINE THAT WAS ACTUALLY TRADING WAS INVISIBLE

A browser audit of all six dashboard tabs (Overview, Positions, Trade history,
Research, Risk rails, System) found the dashboard was reporting a flat, empty
day while the equity intraday scalper was mid-trade. The cause: every P/L view
read ONLY `data/structures.jsonl`, the credit-spread seller's registry. The
scalper writes its own journal (`data/equity_scalp_decisions.jsonl` plus
`data/equity_scalp_state/<ET-date>.json`) and never touches that registry, and
the seller's registry has been absent since the 08-28 reset. So the dashboard
had no source of trades at all.

What the operator was shown vs. the truth at 14:31 ET:

| Field | Displayed | Truth |
|---|---|---|
| Today P/L | +$0 | -$8.09 realized (SPY morning_fade) |
| Trade history | "No closed trades" | 2 closed scalps, -$19.53 total |
| Equity curve / daily bars | empty, "No realized closes" | 2 days of realized P/L |
| Open QQQ short | "Broker position", no P/L | Equity Scalp · gap_follow, short 28 @ 708.89, +$61 unrealized |
| Account equity | never rendered at all | $100,041.08 (the API returned it; no tile consumed it) |

Fixes shipped (`harness/dashboard_server.py`, `dashboard/`):
- `_equity_scalp_records()` pairs eq_open/eq_close per symbol into open and
  closed rows; both engines' closes now feed today's P/L, the equity curve, the
  daily bars, and the trade table.
- `_equity_scalp_summary()` surfaces the day state (trades taken vs cap, rules
  fired, realized today, halt flag). **A missing state file reports
  `has_state: false` and `None`, never 0** — silence is not a zero day.
- Positions rows are matched to the engine that opened them and carry entry
  price plus unrealized P/L (`market_value - cost_basis`, correct for a short,
  whose cost basis is negative proceeds; Alpaca's facade returns no unrealized).
- `_today_pnl` and `_history_metrics` bucket by the **ET** trading date. They
  used the UTC date, which rolls at 20:00 ET and would credit a late close to
  the wrong session.
- Risk rails tab gained the scalper's own rails (notional, daily cap, stop %,
  daily loss stop, time exit, flatten time, entry windows). System tab
  separates the options provider (`public`) from the stock data source
  (AlpacaRelay proxy) and shows scalper liveness.
- Account equity tile added; "Open spreads" became "Open positions" with a
  spreads/scalps breakdown (it was labelled "Total open positions" while
  counting credit spreads only, reading 0 with a live position on the book).
- `plainMoney()` rendered a negative as `$-19,787`; now `-$19,787`. P/L shows
  cents below $1,000 (whole-dollar rounding erased a -$8.09 scalp result).
- Switching tabs now scrolls to the top; the sidebar scrolls with the page, so
  a nav click while scrolled landed on empty space.

### OPEN ISSUE (pre-existing, NOT from this change): broker refresh times out

While verifying the restart, the dashboard's background snapshot began reporting
`broker_timeout` on most cycles: `consecutive_failures` climbs, `as_of` freezes
for minutes, then one refresh succeeds and it starts over. The UI handles this
correctly (stale banner, values held from the last good read, nothing
fabricated) — verified in the browser — but the account panel is minutes stale
much of the time.

It is **not** caused by the dashboard work: `git diff` shows `SnapshotStore`,
`ReadOnlyBroker`, `make_client` and `BROKER_TIMEOUT_SECONDS` are untouched, and
the identical `SnapshotStore.refresh()` run in a fresh process completes in
**0.35s** against the same account. Only the long-lived server process stalls
past its 10s join.

Prime suspect: `ReadOnlyBroker.read_snapshot` calls `make_client()` on EVERY
30-second refresh, and `make_client` constructs a new `PaperClient` and calls
`_ensure_paper()` before `account_state()` and `list_positions()` — three round
trips on a fresh connection every cycle, forever. Worth checking connection/
socket accumulation in the resident process. Note also that `refresh()` clears
`_refresh_inflight` only in the worker's `finally`, so a worker that outlives
the 10s join leaves the flag set and the NEXT cycle returns early.

Not fixed here: out of scope for the UI audit, and it needs its own diagnosis.
Flag before building on the assumption that the account panel is live.

### Adversarial QA round (2 sub-agents) — 10 further findings, all fixed

A code-correctness reviewer and an independent data-integrity auditor were run
against the change. The auditor reconciled EVERY served field to source and
found all values correct; the reviewer found ten defects, seven of them in the
same "a zero is a claim" family:

1. **Open positions printed 0 during a broker outage.** `len(positions or [])`
   is 0 on an unread snapshot, and `?? "—"` never fires on 0. Now `None` when
   the account is unread, and the Positions tab says the list is *unknown, not
   empty*.
2. **An unpaired scalp open was reported open forever.** Pairing had no date
   bound, so a 12-day-old open with an un-journaled close showed as a live
   position while the Positions table showed nothing. Pending opens are now
   bounded to the current ET day (the scalper mandates a 15:50 flatten).
3. **The 6-position cap governs OPTION LEGS**, not broker rows
   (`harness/positions.py` counts legs). Showing an all-positions total against
   it would print "8 of 6" for a rail that was never breached. The tile no
   longer pairs them; the cap stays on the Risk rails tab.
4. **Two opens on one symbol mis-attributed BOTH trades.** `pending[symbol] =`
   discarded the earlier open, so one close rendered with the other trade's
   rule/side/entry and the second rendered with none. Now a FIFO queue.
5. **A day whose closes all have unknown P/L showed +$0.00.** The orphan-close
   path journals `pnl_usd: null`. `_today_pnl` now returns `None` when today has
   closes but no known P/L, and 0.0 only for a genuinely empty day. The System
   panel's figure is relabelled "Realized today (scalper only)" so the two
   sources on one page cannot be mistaken for each other.
6. Overview history header and rows used different grid tracks (~21px offset).
7. A malformed `rules_taken_day` took the whole page to the error banner. Note
   the first coercion was wrong too — iterating a bare string yields its
   characters; the test caught it.
8. `last_cycle` was serialized as `str(datetime)` (space separator, outside the
   ECMAScript grammar). Now real ISO-8601.
9. File-sourced strings reaching `innerHTML` are now escaped.
10. Trade sort was string-lexicographic (`Z` sorts after `+00:00` at the same
    instant). Now sorts on the parsed instant.

**Unresolved, upstream of the dashboard:** a constant **$0.43** gap between
broker equity and journal-derived P/L across two paired reads. The journal's own
P/L (-11.440000000001419, -8.09000399999968) overstates realized by that amount,
or starting equity was not exactly $100,000.00. The dashboard faithfully copies
the journal, so `today_pnl_usd` is right relative to its source but may be $0.43
off broker truth. Settling it needs the orders/activities endpoint.

**Scope disclosure added to the UI:** history is equity-scalper-only from
2026-08-31 forward. The seller's entire closed record (12 closes, **-$1,684**
known, 2 unknown) lives in `data/archive_pre_2026-08-28/` after the logged 08-28
reset, so `research.records` and `unknown_pnl_closes` read 0. The Trade history
and Research tabs now say so instead of implying an all-time view.

Tests: 13 new dashboard tests (journal pairing, orphan close, FIFO
re-entry, stale-day opens, ET-date bucketing, short-position P/L sign,
unknown-P/L days, malformed state, trade ordering, ISO timestamps,
missing-day-state semantics). **195 passed.**
Dashboard LaunchAgent `com.optionsagent.dashboard` restarted and re-verified in
the browser on all six tabs.


## 2026-08-31 — TRADING KEY DIED OVER THE WEEKEND; NEW KEY + NEW PAPER ACCOUNT

Pre-market check found the trading key (PK4UIM…) returning 401 from
paper-api.alpaca.markets, confirmed three independent ways (curl, the bot's own
`make_client().market_is_open()` path, and Python reading `.env` directly). The
bot traded normally through Friday 08-28 15:55, so the key died over the
weekend, most likely collateral from the 08-30 dashboard session that retired
MT4's key. Every cron wrapper fail-closes on the broker clock, so the bot would
have silently skipped all of today with no errors and no trades.

Operator supplied a fresh key pair (PKT3XD…) at ~08:45 ET; `.env` updated.
The new key maps to a NEW paper account **PA371G5THNUO**: status ACTIVE,
equity exactly $100,000.00, cash $100,000.00, 0 positions, 0 open orders, no
blocks. Friday's equity-scalp P/L lives in the old account's book, so broker
history now spans two accounts (journal remains the continuous record; do not
join broker fills across the boundary). Data path unaffected: OA_DATA_* still
rides the AlpacaRelay proxy (verified 200 pre-market). Dashboard LaunchAgent
restarted after the swap.

## 2026-08-28 — REACTIVATED LOCALLY; CLAUDE CODE CLI PROPOSER

Operator clarified that OptionsAgent is a local paper-trading robot, not a Railway deployment. The
proposal path was changed from the Anthropic Python SDK/API-key requirement to the locally
authenticated Claude Code CLI (`claude -p`). The CLI is invoked with structured JSON output,
`--safe-mode`, no tools, and no session persistence; any failure fails closed to no trade.

Verified: `claude --version` reports 2.1.250; a direct authenticated CLI probe succeeded; the
OptionsAgent proposer boundary returned valid structured output without `ANTHROPIC_API_KEY`.
Public.com read-only market data and Alpaca paper authentication also passed. Full tests after the
CLI change: **163 passed**.

The local user crontab is authoritative: `cron/entry.sh` runs every five minutes in the 10:15–10:27
ET entry window, and `cron/exits.sh` runs every 20 minutes during market hours. Do not link or deploy
this repo to `tqqq-qqq-paperbot` or infer that Railway is required.

## 2026-08-27 — ARCHIVED TRADE STUDY; SELLER OVERFIT LOCALLY; NO DEPLOYMENT

The archived volume was analyzed with `research_scalp_history.py`. It contains
37 scalp registry pairs across 15 trading days, 36 with realized P/L and one
vanished position with unknown P/L. Realized scalp P/L was **-$367**, 10/36
winners. Twelve entries at or after 11:30 ET were 0/12 and **-$681**; the 24
entries before 11:30 ET were 10/24 and **+$314**. Capping the pre-cutoff
history at two entries per day retained 23 known trades, 10 winners, and
**+$345**. These two gates were promoted; underlying, direction, and high-RVOL
slices were too small or did not separate cleanly.

`ScalpRails.entry_cutoff_et` and `max_trades_per_day` plus their config
documentation mirrors were changed from 14:30/3 to **11:30 ET/2**. No scalp
sizing, stop, or RVOL rule was changed. This is a conditional replay of realized fills, not a complete option
backtest; require at least 30 new prospective scalp round-trips before another
tuning decision.

The seller archive has 10 credit-spread records across 5 entry days. Eight
filled structures have non-zero quote-based P/L totaling -$644 (3 wins, 5
losses), plus one never-filled order and one still-open structure. Per the
operator's explicit instruction to overfit even on tiny data, a hard winner
profile was added to `harness/risk_rails.py`: CCL bullish put width >= 1.50 and
credit >= .29; SOFI bullish put width >= 1.00 and credit >= .23; F bearish call
width <= .50 and credit >= .06. Conditional replay is +$130 across 3/3 winners.
This is selection-biased in-sample research, not evidence of an edge; hold it
unchanged for at least 30 prospective credit-spread round-trips.

The local `claude-ds` wrapper was invoked but hung without a response; the raw
DeepSeek fallback reset its connection. No external recommendation was received.
The bot remains retired and not deployed because its original Railway project,
volume, paper credentials, and Discord webhook were deleted on 2026-08-02.

## 2026-08-02 — SHUT DOWN. Railway off, Discord off, data archived.

**Operator instruction:** turn the agent completely off in Railway, kill the Discord side, he is
deleting the Alpaca paper account. Data kept for future use.

**What was done, in order:**
1. **Backed up the Railway volume FIRST** (before touching anything). 11 MB tarball,
   `md5 bc28e9bc6f3123ebdfdfe5577612757e`, verified byte-identical against the container. Pulled
   via 30 base64 chunks over `railway ssh`, each chunk md5-checked (a single-shot stream silently
   truncated 11 MB to 353 KB — see ERRORS.md). Archive: `backups/volume_2026-08-02.tar.gz`,
   also extracted into `data/` for direct use.
   Contents: 19 chain snapshots (11 MB, full chains w/ IV + greeks), marketdata (4 MB),
   `decisions.jsonl` (91), `structures.jsonl` (23), `scalp_decisions.jsonl` (104),
   `scalp_positions.jsonl` (74), `exit_state.json`, scalp_state, logs.
2. `railway down` — the running container/deployment removed. No cron, no cycles, no exit sweep,
   no market-data relay.
3. **Discord webhook DELETED** at the API (`DELETE` → 204, now 404). Nothing can post to
   `#options-agent` again, ever, even if the container came back. The channel and its message
   history were deliberately left intact (that's history worth keeping).
4. **All app env vars deleted from Railway**: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`,
   `ALPACA_PAPER`, `ANTHROPIC_API_KEY`, `OA_ANTHROPIC_MODEL`, `DISCORD_WEBHOOK_URL`,
   `OA_RELAY_TOKEN`, `OA_MARKETDATA_ENABLED`, `OA_SCALP_ENABLED`. Only Railway's own
   `RAILWAY_*` vars remain. Even a manual redeploy now has no broker key, no LLM key, no webhook.
5. **GitHub repo DISCONNECTED from the Railway service** (`serviceDisconnect`). This was the real
   trap: the service auto-deployed on every push to `Jhosshua/OptionsAgent`, so committing these
   very notes would have brought the bot back online. Pushes are now inert.

6. **Railway project DELETED** (operator confirmed, same session). `railway delete --project
   e312c619-5ac9-4edb-9d57-6ec4d1252ddd --yes`; the API now reports
   `deletedAt: 2026-08-04T19:30:51Z` — Railway schedules the purge rather than doing it instantly,
   so the name may linger in `railway list` until then. The `optionsagent-volume` goes with it.
   Local dir `railway unlink`ed. Nothing of this bot remains on Railway.

   Deletion was only done AFTER the archive was md5-verified locally **and** pushed to GitHub in
   commit `0d5c3b2`, so there are two independent copies that do not depend on Railway.

**Side effect flagged:** the shared market-data relay
(`optionsagent-production.up.railway.app`, `MARKETDATA_RELAY.md`) is DEAD. No other bot's code
referenced it (checked every `.py` under `/Users/mo`) — only mentions in sibling md files — so
nothing else breaks.

**To bring this back one day:** it's a from-scratch redeploy now — new Railway project + service +
volume, new Alpaca paper keys and a new Discord webhook into its vars, reconnect the GitHub repo, and restore `data/` from the tarball onto the
volume. The 30-day pivot review (`credit_spreads_only`, gates scored ~2026-08-19) never completed
— it was cut short here at the operator's call, not by hitting the -25% abort.


## 2026-07-10 (later 2) — DISABLED the scalper daily-loss halt (operator saw it fire, wants max learning)

**Trigger:** operator saw `⚡ SCALP HALTED for the day: daily loss $-154 hit stop -$150 — halted`
and said that's what he does NOT want on a paper account — we need to learn as much as we can.
(So the 0DTE scalper IS live on Railway — `OA_SCALP_ENABLED` is set — despite the "off by default"
note in the build entry below.)

**What was decided:** disable the scalper's daily-loss halt. This is a HARD CODE RAIL
(`harness/risk_rails.py` `ScalpRails.daily_loss_stop_usd`), not the config tunable — `run_scalp.py`
enforces it via `active_scalp_rails()`, so the `config.json` `scalp.daily_loss_stop_usd` key was
never actually read (now set to 0 + documented as doc-only to avoid confusion).

**How (code, reversible):**
- `ScalpRails.daily_loss_stop_usd` default `150.0 -> 0.0`; `scalp_daily_loss_ok()` now treats
  `<= 0` as DISABLED (returns "daily loss halt disabled", never halts).
- `active_scalp_rails()`: a POSITIVE `OA_SCALP_DAILY_LOSS_USD` env re-enables the halt at that
  value (a tightening from "no halt"). So re-enabling is a Railway env var, no code edit.
- Tests updated: `test_daily_loss_predicate` (default disabled + explicit stop still halts),
  `test_env_overrides_tighten_only` (env 500 now re-enables, not ignored), and split the driver
  halt test into enabled-halts vs disabled-does-not-halt. 130/130 pass.

**Why it's still bounded (flagged to operator):** the scalper's OTHER rails are untouched —
`max_trades_per_day=3` and `per_trade_usd_cap=$250`. Worst-case daily loss without the halt =
3 * $250 = **$750** if all three 0DTE scalps expire worthless (~21% of ~$3.5k equity). Bounded,
survivable, paper. The 15:50 ET EOD flatten + theta cut + entry cutoff all remain (catastrophe
rails, never touched). **Rollback:** set `OA_SCALP_DAILY_LOSS_USD` env to a positive $ on Railway,
or restore the code default.

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

## 2026-08-28 — verified current state + operator explainer PDF

Most mds above are historical. Verified from code + live runtime today:

- Runtime is LOCAL, not Railway: user crontab runs `cron/entry.sh` (self-gated 10:15-10:27 ET,
  once/day lock) and `cron/exits.sh` (every 20 min, 9-16h). Scalp and marketdata publishers are
  OFF (no OA_SCALP_ENABLED / OA_MARKETDATA_ENABLED in .env, no cron lines).
- Paper account was RE-FUNDED to $100,000 today (equity and options BP both 100k via
  `account_state()`). The $5k-era book had drawn down to ~$4,920.
- Phase remains credit_spreads_only; every credit spread must pass the hard in-sample winner
  profile (CCL/SOFI bullish put, F bearish call) in `harness/risk_rails.py`.
- Aug 28 cycle: Claude (sonnet via local CLI) proposed 8 spreads, rails vetoed all 8
  (3 no matching contract, 5 failed winner profile); exit sweep closed July's SOFI spread +$26.58.
- Dashboard: local LaunchAgent `com.optionsagent.dashboard`, 127.0.0.1:8765, read-only.
- NEW: `OptionsAgent-Explained.pdf` (8 pages: how it works + FAQ + 6 live dashboard shots).
  Regen source: `data/pdf_assets/` (explainer.html + CDP capture/print scripts; print via the
  debug-Chrome CDP path, headless CLI hangs on this machine).

## 2026-08-28 (later) — 0DTE scalper ARMED + SIP data-key split

- OptionsAgent's own trading keys have NO real-time SIP (bars 15 min stale, latest-trade 403s).
  Fixed with an eyes/hands split: `OA_DATA_KEY_ID`/`OA_DATA_SECRET_KEY` in `.env` point at MT4's
  SIP-entitled paper key (acct PA3Y17SSOEYM); `PaperClient._data_credentials()` uses them ONLY
  for stock bars/latest-trade. Orders stay on OptionsAgent's own paper key. Verified real-time:
  last bar = current minute, SIP spot live. Public.com sidecar remains options-only (no equity
  endpoints exist on its gateway).
- Scalper enabled: `OA_SCALP_ENABLED=true` + crontab `* 9-15 * * 1-5 cron/scalp.sh`. One real
  tick ran clean 12:25 ET. First live entry window Monday 09:33 ET. 163 tests green.
- Explainer PDF updated throughout (scalper strip, key numbers, FAQ, ARMED chip).
- Other SIP-entitled keys on this machine (SIP-403 test 08-28): AKZZZ5 (MTEdge1, LIVE key, avoid),
  PKA6ON (DriftShort, also serves SwingNotifications), PKSJHP (MT1 eyes), PKDJRT (MT4, now dual-use).

## 2026-08-28 (final) — dashboard reset to activation date

Operator: the bot "started working today," so the dashboard now shows today-forward only.
- Archived to data/archive_pre_2026-08-28/ (gitignored, nothing deleted): structures.jsonl (24,
  0 open), scalp_positions.jsonl (37, 0 open), scalp_decisions.jsonl, pre-08-28 scalp_state day
  files, and 91 pre-08-28 decision lines.
- Kept: today's 11 decision lines and today's scalp state (2026-08-28.json, holds the live
  opening ranges). decisions.jsonl was SPLIT, not moved, to preserve today's vetoes.
- Dashboard restarted (launchd KeepAlive). Verified: 1 process, /api/trades empty, daily_pnl
  empty, equity $100,000. Note: the Aug 28 SOFI +$26.58 close is a true fact (it is in the PDF's
  Today strip) but no longer renders in the dashboard since its July 'opened' row was archived.

## 2026-08-28 (night) — 6-month 0DTE ORB overfit search: NULL RESULT, no scale-up

Operator asked to overfit the scalper on 3-6 months of data and deploy ~$20k/50
contracts. Study (research_scalp_6mo.py, 125 sessions SPY+QQQ, 16,384-combo grid,
IS/OOS by date, per-day stats, random-direction null):
- ALL combos negative. Best: rm30, rvol2.5, cutoff 14:30, tgt 30%, theta 10m
  loses ~$11/contract/day (IS t=-3.6, OOS t=-8.0). Null loses -51.65/day.
- Underlying decomposition kills it at the root: 931 signals, mean signed 15m
  return -0.04bp to +0.01bp. No direction edge, so no size can fix it.
- NOT implemented at $20k. Scalper stays at $250 learning size (armed).
  Raising size on this evidence would scale a proven loser.

## 2026-08-28 (night 2) — 0DTE option scalper RETIRED, EQUITY scalper deployed

Broadened the hunt per operator (mine ANY formula, overfit to the window):
- Stage 1 (underlying, model-free): the morning-fade family and QQQ big-gap
  13:00 follow are the only consistent edges (+10-18bp, day_t 1.5-2.6).
- Stage 2: long 0DTE options CANNOT harvest them (theta+spread 3-10x the edge;
  floating-strike bug found by codex, fixed, rerun: options statistically zero).
- Stage 3 (shares, model-free): rule A morning fade +$23.6/trade 60% win,
  rule C QQQ gap follow +$34.3/trade 64% win OOS t=+3.1. Both halves positive.
- DEPLOYED: run_scalp_equity.py (rules A+C, one slot per rule/day), rails in
  EquityScalpRails ($20k notional, 0.7% intrabar stop, 120m time exit, 15:50
  flatten, -$300 daily halt, orphan adoption, fail-closed reconcile). Cron
  * 9-15 * * 1-5. OA_EQUITY_SCALP_ENABLED=true. First windows Monday 10:15/13:00.
- OA_SCALP_ENABLED=false + option-scalp cron line REMOVED (16,384-combo null).
- Codex review: 3 P1s fixed (orphan routing with 0-entry-price, fail-closed
  broker read, intrabar stops), 4 P2s fixed (rule slot reservation, retry on
  failed entry, BOTH pooling, config wiring). 177 tests green.

## 2026-08-30 — data eyes repointed: MT4's key retired, now on ADMS's SIP key (PKSJHP…)

MT4 was shut down 08-30 and its Alpaca account is being removed, so `OA_DATA_KEY_ID`/
`OA_DATA_SECRET_KEY` in `.env` were repointed from MT4's PKDJRT… key to the ADMS bot's
PKSJHP… key (paper acct PA30WJX0NW6F, same key ~/ManualTrading already borrows as its
data eyes). SIP verified live through `PaperClient` itself: `_data_credentials()` returns
PKSJHP…, `stock_latest_price("SPY", feed="sip")` = 769.35 (matches a direct curl), 797
minute bars with the last bar at Friday 19:59 ET. Orders are untouched (still this
account's own PK4UIM… paper key).

Why no conflict: Alpaca's one-connection-per-account limit (the 406) applies only to
websocket STREAMS. ADMS, MT1's running processes, and OptionsAgent are all REST-only on
this key, sharing the ~200 req/min budget at ~10-15/min worst case. Timing dovetails:
ADMS's burst is 09:15-09:33 and the scalper self-gates to 09:33-15:59. Rule stands: if
anything ever opens a stream on PKSJHP…, it owns the account's only stream slot.

## 2026-08-31 — market data via AlpacaRelay proxy (data path only)
All alpaca-py data clients in harness/alpaca_glue.py now take
`url_override=self._data_url()` (new OA_DATA_URL env var → the relay /data
proxy) and ALL of them use `_data_credentials()` — this also fixes two
pre-existing inconsistencies where stock_daily_bars and the option client
authenticated with the TRADING key. `.env`: OA_DATA_KEY_ID = relay token,
OA_DATA_SECRET_KEY dummy, OA_DATA_URL set. research_scalp_6mo_pull.py gained
the same url_override. Trading unchanged: ALPACA_API_KEY pair, paper=True
hardcoded, _ensure_paper guard intact. Options chains still come from
Public.com when OA_OPTIONS_DATA_PROVIDER=public; the Alpaca fallback path now
rides the relay (OPRA verified working on the relay key). Verified: latest
price, minute bars, daily bars via relay; pytest 177 passed. Cron picks up
.env fresh each run — no restart needed.
**Codex review fix:** OA_DATA_URL added to entrypoint.sh's env allowlist so
the Docker/Railway deployment path propagates the relay URL (local cron reads
.env directly and was unaffected).

## 2026-09-01 — Deployed to Railway (project OptionsAgent); dashboard now public

**What was decided:** run on Railway. The Dockerfile, entrypoint and Railway
cron schedule had been written earlier but never deployed; they are live now.

**The defect that would have made this a silent no-op:** `harness/proposer.py`
shells out to the Claude Code CLI, and its unavailable-CLI path returns "no
proposals" — a fail-closed no-trade. `OA_CLAUDE_CLI` pointed at a `/Users/...`
path that does not exist in a container, so the deploy would have come up green
and never traded. The Dockerfile now installs Node 22 +
`@anthropic-ai/claude-code`, and the build asserts `claude --version` runs, so a
broken install fails the BUILD instead of a trading day. Headless auth is
`CLAUDE_CODE_OAUTH_TOKEN` (same Anthropic account StrategyS uses).

**Why the build asserts rather than trusting the install:** the first attempt
hand-symlinked `cli.js`, which the package no longer ships at that path. The
symlink dangled and clobbered npm's own working shim.

**Container settings that differ from the Mac:** `OA_DASHBOARD_HOST=0.0.0.0`
(Railway must reach it) and `OA_CLAUDE_CLI=/usr/bin/claude`.

**Dashboard:** https://optionsagent-production.up.railway.app (HTTP 200). It was
`127.0.0.1:8765` on the Mac, reachable only from that machine.

**State:** volume at `data/`. decisions/scalp history migrated and row counts
verified (20 decisions, 6 equity-scalp decisions).

**Verified in the container:** all 15 secrets injected, and a real `claude -p`
call returned a completion — the CLI authenticates, it is not merely present.

**Rejected:** rewriting the proposer onto the Anthropic API. It would have
changed the model path, the prompt handling and the billing account, to solve a
packaging problem.

## 2026-09-01 (later) — OptionsAgent alerts moved to #options-agent

Was sharing StrategyS's channel; the operator's rule is one channel per bot.
`NOTIFY_DISCORD_CHANNEL` is a Railway variable, so this is config, not code.

**CLI call budget:** the entry cycle self-gates to 10:15-10:27 ET once per day
via an atomic lock on the volume, and calls the proposer ONCE per cycle with the
whole watchlist in one bundle. So **1 Claude CLI call per trading day**, up to 3
if it fails and retries. Exits, the 0DTE scalper and the equity scalper are all
deterministic and use no LLM.

## 2026-09-01 (evening) — Proposer moved off the Claude CLI onto the DeepSeek API; dashboard reworked

**This overrides the same-day "Rejected: rewriting the proposer onto the Anthropic API"
decision above, by explicit operator instruction** ("replace it with this api ... I want no
error tomorrow"). The premise of that rejection ("it would solve a packaging problem") was
wrong: the CLI's failure mode is a LOGIN, not packaging. Today's 10:15 ET cycle on the Mac
got `Not logged in · Please run /login` three times and failed closed; 08-31's cycle died
the same way (invisible then, because stdout was discarded). Two trading days lost to an
auth state a cron job cannot repair.

**What was decided:**
- `harness/proposer.py` now has two providers behind `OA_LLM_PROVIDER`: `deepseek` (default,
  Railway) and `claude_cli` (Mac only). The key the operator supplied is a **DeepSeek** key
  (`sk-` + 32 hex; `api.deepseek.com/models` = 200, Anthropic and OpenAI both 401), so the API
  is DeepSeek's OpenAI-compatible chat completions, `response_format=json_object`, temp 0,
  `max_tokens` 8192, `finish_reason=length` rejected. Model `deepseek-v4-pro` (one call a day;
  cost is irrelevant, judgment is not; v4-flash was 8 s vs pro 39 s on a 3-name test and
  both made the same CCL-bullish call Claude made on 08-31).
- Every call returns a `ProposeReport`; `run_cycle.py` journals it as a `proposer_result` row
  (provider, model, ok, proposals, attempts, latency_s, error). Config errors (missing/401/402/403
  key, unknown provider, missing CLI) are NOT retried; transient ones retry 3x with 5s/10s
  sleeps; exactly one Discord page per failed cycle.
- Dockerfile no longer installs Node or `@anthropic-ai/claude-code`. entrypoint.sh allowlist
  gained `DEEPSEEK_API_KEY`, `OA_LLM_PROVIDER`, `OA_DEEPSEEK_MODEL`, `OA_LLM_TIMEOUT_SECONDS`,
  `OA_LLM_ATTEMPTS`. config.json `llm` block now says deepseek / deepseek-v4-pro (it said
  anthropic / claude-fable-5 and nothing read it).
- Railway vars set: `DEEPSEEK_API_KEY`, `OA_LLM_PROVIDER=deepseek`,
  `OA_DEEPSEEK_MODEL=deepseek-v4-pro`. `OA_CLAUDE_CLI`, `OA_CLAUDE_MODEL`,
  `CLAUDE_CODE_OAUTH_TOKEN` deleted after the deploy (inert under provider=deepseek anyway).
- Dashboard: Research tab + `/api/research` removed (always 0/0/$0 since the 08-28 reset moved
  `structures.jsonl` out). New "AI proposer · last cycle" card + "Seller, last cycle" stat on
  Overview, AI proposer card on System, both engines get identical Engine/Runs/Decides-with
  rows on Risk rails plus the three allowed profiles rendered from
  `_CREDIT_SPREAD_OVERFIT_RULES` itself. Sticky sidebar, per-section loading
  (`Promise.allSettled`), 60 s auto-refresh, humanized labels.

**Verified:** real full-watchlist call through the new code path: ok, 3 proposals (CCL/AAL/SOFI
bullish), 76.6 s, valid journal row. 221 tests green (test_proposer rewritten: 16 tests incl.
retry/no-retry classes, truncation, invalid JSON, malformed items dropped, CLI path pinned).
Local dashboard rendered on all 5 tabs with zero console errors.

**Why the seller has still never traded (unchanged by this work):** all 14 proposals since 08-28
died at gates that never read the thesis: 7 `no_spread_matched_criteria` (contract picker),
7 `overfit_profile` (only CCL-bullish / SOFI-bullish / F-bearish may ever open). The 08-31
CCL-bullish proposal, which WAS on the allowed list, died at contract selection. Better
inputs (e.g. web search) cannot move this; the funnel is closed downstream.

**Rejected:** web search for the proposer (non-replayable decisions, prompt-injection surface,
and zero effect on the closed funnel above); an Anthropic key (the operator's key is DeepSeek's).

**First live DeepSeek cycle: 2026-09-02 10:15 ET on Railway.** Check `#options-agent` and the
dashboard's AI card; a `proposer_result` row with `ok=true` is the proof.

### 2026-09-01 (evening) — QA pass on the DeepSeek/dashboard change (two adversarial agents)

Proposer review: SAFE TO DEPLOY, with fixes applied before tomorrow's window: (1) the literal
lowercase word `json` now appears in the prompt (DeepSeek's `json_object` precondition; the old
test case-folded the assertion and proved nothing); (2) `OA_CLAUDE_TIMEOUT_SECONDS` /
`OA_CLAUDE_ATTEMPTS` no longer fall through to the DeepSeek path (a leftover Railway var could
have silently changed retry/timeout behaviour); (3) every 4xx except 429 is now a no-retry
config error (400/404/422 were burning up to 6 min of the window); (4) three mutation gaps
closed with tests (sleep backoff `[5, 10]`, config-file model+temperature actually read,
legacy knobs inert); (5) the `proposer_result` journal write in `run_cycle.run()` is now
covered by `tests/test_run_cycle_journal.py` (deleting the line failed nothing before).
Dashboard review: FIX FIRST, fixed: (1) one malformed `proposer_result` row (`proposals:
"many"`) crashed `build_payload` for ALL five endpoints with a dropped socket while `/healthz`
stayed green; now coerced via `_json_number` and the `/api/` branch returns a 500 JSON body
per section; (2) `_read_jsonl` read the HEAD of the file under a 2 MB cap that would have
returned `[]` for the whole journal after ~265 days ("has not run a cycle yet" on a year-old
bot); now a tail `deque` with a 256 MB sanity bound; (3) `attempts` escaped in the JS; (4) a
`cycle_start` without `cycle_id` no longer absorbs other id-less rows; (5) dead research CSS
and a date-stamped empty-state string removed. `.gitignore` now ignores `.env.*` except
`.env.example`. Suite: 233 passed. Both fixes deployed (`railway up`, build 0de84f31).
