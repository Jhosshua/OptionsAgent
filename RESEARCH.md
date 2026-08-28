# Options bot research — Phase 1 (in progress)

## 2026-08-27 — archived trade replay

The archived live-paper history is analyzed in `OVERFIT_ANALYSIS.md` and can
be reproduced with `python3 research_scalp_history.py`. The replay found a
strong but small-sample timing split in the isolated 0DTE scalper: all 12
realized entries at/after 11:30 ET lost (-$681), while the 24 earlier entries
returned +$314. Combining a hard 11:30 ET cutoff with a two-entry daily cap
retained 23 known trades and returned +$345 in-sample. These are now hard
scalp rails, but this is a conditional replay of realized fills, not a full
option-chain backtest, and no other feature was promoted. The credit-spread
seller's mixed 8-trade realized sample did not justify fitting new entry or
exit parameters on statistical grounds; the operator nevertheless explicitly
requested an in-sample overfit, which is documented and implemented below.

The multi-day credit-spread ledger has 10 records across 5 entry days; 8
non-zero quote-based closes total -$644. The requested in-sample overfit keeps
only three recorded winner profiles (CCL bullish put >= 1.50 width / >= .29
credit; SOFI bullish put >= 1.00 / >= .23; F bearish call <= .50 / >= .06),
which replays to +$130 across 3 wins. This is implemented as a hard
fail-closed rail, not a configurable JSON filter. It must be prospectively
validated before any broadening.

Status: **Pass 1 + Pass 2 complete; archived replay and requested overfit are local only.**

Target: deterministic (rules-based) options trading bot on Alpaca, "left brain / right brain" hybrid
(LLM proposes, rules engine disposes), same pattern as DeterministicAgent/LiveSwingAgent. Paper trading
first. Own Railway project + Discord channel (not shared with an existing bot).

Strategies in scope: covered calls, cash-secured puts, long calls, long puts, vertical/credit spreads,
covered straddles, multi-leg.

## Known shortfall vs. the original ask

The user asked for 200+ sources including Reddit and X. Pass 1 fetched 21 sources and verified 21 claims,
**zero of which were Reddit/X** despite explicit search attempts. Pass 2 (running) is targeted specifically
at that gap plus failure-mode mechanics (pin risk, early assignment, gamma-near-expiry, multi-leg spread
slippage, weekend margin calls). Treat Pass 1 findings below as solid on API mechanics / prior art, thin
everywhere else, until Pass 2 lands.

## Pass 1 — verified findings (21 confirmed, high confidence unless noted)

### Alpaca API mechanics

- **Approval tiers are cumulative.** Level 1 = covered calls + cash-secured puts (needs owned shares for
  the covered call; sufficient options buying power for the CSP). Level 2 = Level 1 + long calls/long puts
  (buying-power gated only). Level 3 = Levels 1-2 + multi-leg (spreads, straddles, strangles, iron
  butterflies/condors, credit/debit/calendar spreads) via a combined `mleg` order type.
  Paper accounts auto-get Level 3; live accounts need separate approval, and Live vs Paper tier can differ —
  check both environments separately.
  Sources: alpaca.markets/support/what-option-levels-or-tiers-do-you-provide,
  docs.alpaca.markets/us/docs/options-trading, docs.alpaca.markets/docs/options-level-3-trading,
  alpaca.markets/blog/level-3-options-trading-now-available-with-alpacas-trading-api

- **Multi-leg order constraints that directly affect architecture:**
  - `mleg` orders support only `market` or `limit` type (no stop/stop_limit — those are single-leg only).
  - **No equity leg allowed in a multi-leg order.** A covered call cannot be submitted as one combined
    stock+option order — must be two separate orders (own the shares first, then sell the call separately).
    Confirmed against a real developer-forum error report attempting the combined form.
  - Every short leg inside an `mleg` order must be covered by another leg in that same order (no naked
    shorts inside a combo order — naked shorts remain possible only as standalone single-leg orders).
  Sources: docs.alpaca.markets/us/docs/options-trading, docs.alpaca.markets/docs/options-level-3-trading

- **Buying power for CSPs is broker-enforced.** Alpaca computes required buying power as
  (strike × 100 × contracts) − premium received, and hard-rejects orders below that (confirmed via a real
  error payload: required $20,310, available $9,395). The rails engine doesn't need to re-derive the full
  margin formula, just size positions to clear Alpaca's own gate.
  Source: docs.alpaca.markets/us/docs/options-trading-overview

### Prior art (directly reusable)

- **`alpacahq/options-wheel`** (Alpaca's own reference repo): deterministic wheel-strategy bot. Scores
  candidate contracts with `score = (1 − |delta|) × (250 / (DTE + 5)) × (bid / strike)`, filtered by
  config constants `DELTA_MIN`/`DELTA_MAX`, `YIELD_MIN`/`YIELD_MAX`, `SCORE_MIN`. No discretion, no LLM step.
- **`wheel-it`** (community fork): same wheel strategy, adds named risk presets — Conservative 21-45 DTE,
  Moderate 14-60 DTE, Aggressive 7-60 DTE — plus an explicit assignment state machine
  (short_put → long_shares → short_call).
- **ThetaGang** (IBKR only, pattern not code): caps rolled strikes at "old strike + premium received"
  specifically to stop margin usage from ratcheting up on repeated rolls. Worth porting as a rule.

### Strategy mechanics found (wheel-adjacent strategies only — see gaps)

- CSPs: 0.20-0.40 delta range across sources (one source: 0.30-0.40 at 21-35 DTE; another: 0.20-0.30 at
  30 DTE for ~10-17% annualized yield on collateral).
- Covered calls: 0.30-0.50 delta, ~30-45 DTE, roughly 5% OTM.
- Credit spreads: 15-30 delta short strikes, 30-45 DTE (Tastytrade research on 200k+ trades: 45 DTE entries
  managed at 21 DTE had the best risk-adjusted returns; Cboe data: 25-30 delta at 45 DTE ≈ 70-75% win rate).
- No verified conventions found yet for: long calls/puts as standalone directional plays, straddles,
  or vertical spreads outside the CSP/covered-call wheel context.

### Backtesting data reality

- Granular historical options-chain data is gated behind institutional-only vendors: OptionMetrics (IvyDB,
  back to 1996, 10,000+ underlyings — no public pricing, sales-contact/WRDS-subscription only) and ORATS.
- ORATS documents a usable shortcut: snapshot option quotes 14 minutes before market close rather than true
  end-of-day, because true EOD quotes are stale/wide. No free/retail-affordable alternative source verified.

## Pass 2 — verified findings (18 confirmed; 7 killed on citation-precision grounds, see below)

**Data-quality note:** the workflow's automated synthesis step malfunctioned on this run (returned a
literal placeholder stub instead of real content). I caught it by inspecting the raw per-claim verify
votes in the run journal directly rather than trusting the final summary, and reconstructed the findings
below from those raw votes by hand. All 25 claims below reflect genuine 3-vote adversarial verification,
not the broken auto-summary.

**Reddit/X (Gap 1): genuinely not found, not fabricated.** The search agent explicitly reported zero
retrievable Reddit or X/Twitter thread content after 6+ targeted search variations (only unreachable
profile pages / SEO blogs surfaced, no nitter/cache mirrors). Standard web search does not index this
niche discourse. Closest substitute found: a first-person Medium post ("I Tested 23 Systems and Lost
$9,150") describing an automated gamma-scalping bot blown out by a 3-second lagging RSI signal during a
gamma squeeze (64% drawdown) — useful as a cautionary example, explicitly not verified social-media
testimony.

**Assignment / pin risk mechanics:**
- Alpaca has a deterministic cutoff time on expiration day after which no new opening/extending option
  orders are accepted, tied to evaluating that day's expiring positions.
- At expiration, Alpaca auto-exercises ITM positions if buying power is sufficient, or force-liquidates them
  if it isn't — a concrete, broker-side pin-risk resolution mechanism to design around.
- OCC assignment of short contracts is randomized and can happen overnight — a rules engine cannot rely on
  intraday monitoring alone and must treat overnight assignment as unavoidable, guarding with position-level
  buffers (e.g. avoiding deep-ITM shorts heading into known assignment-risk windows).
- Alpaca generates distinct activity codes (OPASN = assignment, OPTRD = paired trade) a bot can poll to
  detect assignment after the fact — reactive, not predictive.
- Early assignment on a short ITM call is likely once the dividend exceeds the same-strike put's price
  (dividend > put price ⇒ near-certain assignment, since the holder can exercise, buy the offsetting put,
  and lock in the dividend). Worked example: stock $188.38, $0.72 dividend, 180-put priced $0.44 → assign.
- SPX-style cash-settled European options carry no assignment/pin risk at all. SPY-style physically-settled
  products do: a spread expiring partially ITM can force an unhedged overnight assigned-share position
  (cited example: $55,800 of unprotected exposure from one unmanaged partial-ITM expiration).
- Credit spreads expiring with the short leg ITM and long leg OTM (partial ITM expiration) can lose
  significantly more than the position's defined max loss, because the long leg stops offsetting the
  assigned short leg.

**Margin / buying-power mechanics:**
- Closing a short option (buy-to-close) is treated as a standard buy order for buying-power purposes — it
  does NOT automatically free up margin to fund itself, even though it's a risk-reducing trade. Alpaca's
  documented workarounds: close unrelated positions to free margin, close spreads via a multi-leg order
  together, or roll covered calls to later expirations for a credit.
- Alpaca liquidates positions without prior notice if an account fails initial/maintenance margin at
  end of day — the rules engine needs its own end-of-day margin-utilization check that fires before
  Alpaca's own trigger does.
- Alpaca raises maintenance margin to 50% on any single security once it's ≥70% of account equity with a
  margin balance ≥$100k — worth mirroring as a position-concentration cap.
- Hard-to-borrow short positions accrue locate/borrow fees for all three weekend days if held through
  Friday settlement — a concrete carrying-cost spike to price into any Friday-close short exposure.

**Multi-leg execution mechanics:**
- Submitting a multi-leg strategy as separate individual leg orders (instead of a true combo order) removes
  the ability to set a limit price at the combined spread's midpoint, exposing the trade to slippage from
  price movement between the first and second leg's fills — a concrete argument for using Alpaca's `mleg`
  order type rather than manually sequencing legs.

**Roll-cap rule (from ThetaGang, already noted in Pass 1, reconfirmed):** cap a rolled put's new strike at
old strike + premium received, to stop buying-power usage from ratcheting up on repeated rolls.

### Claims killed on citation-precision grounds (not necessarily false, just not verbatim-sourced)

Adversarial verification killed 7 claims for being loose paraphrases or unattributed specific numbers
rather than exact-match quotes from the cited source. The general substance may still be directionally
correct, but treat the specific numbers as unverified:
- "TastyTrade research: 21 DTE closes improve risk-adjusted returns 15-20%" — specific % not substantiated.
- "Cboe Options Institute: gamma is 3-5x higher in the final 21 days" — specific multiplier not substantiated.
- The naked-option margin formula (25% of underlying + option ask − OTM amount, floored at two alternate
  minimums) — general shape is a known industry-standard Reg T formula, but this exact source didn't verify
  verbatim; re-derive from Alpaca's own margin docs before hard-coding it.
- Alpaca's exact wording on liquidation-without-notice — the underlying policy is real (see margin section
  above), just the quoted phrasing was a paraphrase, not verbatim.
- ThetaGang's exact ITM-handling behavior — the roll-cap rule itself is confirmed; a secondary claim about
  auto-closing ITM puts specifically wasn't.

## Pass 3 — verified findings (19 confirmed, 6 killed on citation-precision grounds)

Same synthesis-step bug hit again on this run (literal placeholder output). Reconstructed by hand from
raw verify votes again, same method as Pass 2.

**Best find of this pass — a fourth open-source prior-art library, covering exactly the missing strategies:**
- **`goldspanlabs/optopsy`** (formerly `michaelchu/optopsy`): a real, actively maintained, deterministic
  backtesting library implementing 38 distinct built-in strategies including `long_calls`, `long_puts`,
  `long_straddles`/`short_straddles`, `long_strangles`/`short_strangles`, and long/short vertical spreads —
  as standalone strategies, separate from any wheel/CSP/covered-call logic. This is the single most directly
  useful find across all three passes for the four previously-uncovered strategies.
  - Strike/delta selection convention: **per-leg delta targeting** — each leg picked via a target/min/max
    delta parameter, bucketed into delta bands like (0.2, 0.3], (0.3, 0.4] and DTE bands like (0, 7], (7, 14].
  - Deterministic exit logic via three explicit rule types: **stop-loss %**, **take-profit %**, and
    **max-hold-days**, plus a separate **DTE-based forced close** (`exit_dte` param — e.g. enter up to 45
    DTE, force-close at 14 DTE remaining), distinct from the profit/stop rules.

**Straddles / covered straddles:**
- A covered straddle = long stock + short ATM call + short ATM put, same strike/expiration. Both legs sold
  at-the-money (strike = spot at entry) is the strike-selection convention.
- The "covered" in covered straddle is misleading: the short put is NOT covered by cash reserves, only by
  account equity/margin — assignment forces an unplanned additional stock purchase requiring fresh capital.
  This matters directly for a rails engine's buying-power checks.
- A standard **long straddle** = buy ATM call + buy ATM put, same strike/expiration. At initiation it's
  ~delta-neutral (long call ~+0.50 offset by long put ~-0.50).
- Long straddles are conventionally closed early at a predetermined profit/loss relative to premium paid
  (commonly cited: 25-50% of max potential gain), not held to expiration, to avoid further theta decay.
  Example DTE convention seen: ~45 DTE entry (consistent with the general 45 DTE pattern elsewhere), though
  not stated as a mandatory rule.

**Long calls / long puts (standalone directional):**
- E*TRADE's example automated long-call exit strategy: **100% profit target / 50% stop-loss**, executed via
  a one-cancels-other (OCO) order (e.g. enter at $2, exit at $4 profit or $1 loss).
- Option Alpha's aggregated bot data: average entry ~19-21 DTE, average holding period ~15 days before exit
  for long put positions — an observed convention from real trade data, not a stated rule.

**Credit spreads / short premium (recurring pattern, now confirmed from a second independent angle):**
- **21 DTE rule, reconfirmed independently**: short premium positions (straddles, strangles, iron condors,
  credit spreads) conventionally close at or before 21 DTE because gamma risk accelerates non-linearly in
  the final weeks. This is now supported by two independent passes (Pass 2 and Pass 3), though the specific
  numeric magnitude claims attached to it (e.g. "15-20% better returns", "3-5x gamma") keep failing
  verbatim-citation checks — treat the 21 DTE cutoff itself as well-supported, treat any specific percentage
  attached to it as unverified.
- **50% profit-target rule, reconfirmed independently**: close a short premium position once cost-to-close
  reaches 50% of the credit collected (e.g. sold for $4.00, close at $2.00 cost). Cited as "the historical
  standard" for credit spreads by a second, separate source in this pass.

### Claims killed this pass (citation-precision, not necessarily false)

- Covered straddle's exact max-profit/loss ratio wording — the general behavior (leveraged downside because
  both long stock and short put lose together) is real, just the specific "$2 loss per $1 decline" framing
  wasn't verbatim-verified.
- Option Alpha's stated "21 days" average entry for long calls, and a separate claim about long puts having
  a 13.53% win rate — both plausible but not verbatim-sourced; the DTE~19-21 / holding~15-day figures under
  "long puts" above did survive independently.
- A specific short-straddle notional-sizing formula (Index/Spot × Lot Size × 0.5 Delta) — plausible industry
  convention, not verbatim-confirmed.
- The "Tastytrade 200,000 trades" and "25-30 delta → 70-75% win rate" citations for credit spreads —
  same specific-number problem seen in Pass 2, recurring across independent runs. Treat these two exact
  figures as folklore-level, not verified statistics, until traced to an actual Tastytrade publication.

## Remaining gaps (real, still open)

1. No verified data on Alpaca API rate limits or common integration bugs (never came up as a priority
   in any of the three passes' search results).
2. Exact numeric magnitudes attached to the 21 DTE rule (percentage return improvement, gamma multiplier)
   keep failing verbatim verification across two independent passes — the DTE cutoff itself is well
   supported directionally, but don't hard-code a specific "X% better" number without deriving it from
   your own backtest.
3. Optopsy's per-leg delta/DTE bucket defaults are a strong starting point but were extracted from the
   library's documentation, not independently benchmarked against live options data — validate against
   Alpaca's own options chain before hard-coding as production thresholds.

## Research phase: essentially complete

All 7 strategies in scope now have at least one deterministic prior-art reference and a delta/DTE/exit
convention: wheel-adjacent (CSP, covered call) from Pass 1, failure-mode guardrails from Pass 2, and
long calls/puts/straddles/spreads from Pass 3 (via Optopsy + practitioner sources). Ready to move to
architecture design.

## Decisions locked so far

- New Railway project + new Discord channel (not shared with an existing bot).
- Alpaca paper trading first, not live money.
