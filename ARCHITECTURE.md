> **2026-08-28 UPDATE:** the deployed system now has TWO engines: the original
> credit-spread seller described below, plus an equity intraday scalper
> (run_scalp_equity.py, harness/equity_scalp.py, rails in
> harness/risk_rails.py EquityScalpRails) running two rules mined from 6 months
> of SPY/QQQ minute bars. The 0DTE option scalper was retired the same night on
> study evidence. See RESEARCH_SCALP_6MO.md and MEMORY.md for current truth;
> the rest of this file is the original (pre-08-28) design rationale.

# ARCHITECTURE.md — OptionsAgent (original design, 2026-07-03)

> **CURRENT IMPLEMENTATION NOTE — 2026-09-01:** The active runtime is a Railway
> container (see SETUP.md). The DeepSeek API is the proposal boundary since
> 2026-09-01 (evening); the Claude Code CLI is no longer in the image. Public.com remains read-only options data and Alpaca
> remains the paper-only account/order boundary, reached through the official
> Alpaca CLI (`OA_BROKER_TRANSPORT=cli`, `harness/alpaca_cli.py`) since the
> 2026-09-01 hackathon go-live. The credit-spread gate has two modes
> (`OA_CREDIT_SPREAD_GATE`: `winner_profile` default, `research_rules` for the
> hackathon window, coupled to `OA_MAX_POSITION_USD=3000`). The Railway design
> below is once again the live one.

> **Research update 2026-08-27:** The archived 0DTE scalp replay supports a
> hard 11:30 ET entry cutoff and two-entry daily cap, now implemented in `ScalpRails`. The
> requested multi-day credit-spread overfit is implemented as a hard post-selection winner
> profile in `credit_spread_overfit_decision()`. See `OVERFIT_ANALYSIS.md`. These are local
> research changes only. (The "no deployment target" note that stood here was true
> between 2026-08-02 and 2026-09-01; the bot is deployed on Railway again.)

> ⚠️ **PARTIALLY SUPERSEDED — read CLAUDE.md for current truth.** This document is the original
> design and its rationale; it's kept because every threshold number traces back to RESEARCH.md
> through it. Two sections were overridden by operator decisions later the same day:
> 1. **The phased rollout is dead** — all 8 strategies went live at once ("build everything, all
>    phases"). The phase machinery survives in config.json as an off-switch only.
> 2. **The medium-risk percentage caps are dead** — sizing is now a conviction-scaled fraction of
>    available buying power with NO percentage caps ("use all the cash… no cap"). The conviction
>    floor (0.60), max 6 positions, 21 DTE close, and execution-safety rules all survive.
> Everything else here (pipeline shape, per-strategy delta/DTE conventions, execution mechanics,
> covered-straddle cash-backing) is implemented as designed.

Research backing this doc: `RESEARCH.md` (3 passes, verified findings + explicit gaps).

## What this is

A deterministic options-trading bot on Alpaca (paper first), same governing rule as
DeterministicAgent (`/Users/mo/DeterministicAgent/`): **the LLM proposes, deterministic Python
disposes.** No model output ever places an order directly. Options add one wrinkle stock bots
don't have: the LLM can propose a *direction and strategy*, but it must never pick the *strike,
expiration, or delta* — that's rails territory, because that's where "deterministic" actually
has to hold given the research findings (delta/DTE conventions are the load-bearing risk control
here, not just position sizing).

## Pipeline

```
Market context (own screener/watchlist, IV context, upcoming events)   ─┐
                                                                          ├→ LLM PROPOSES ─┐
{underlying, strategy_type, direction, conviction, thesis}               │  (no strike/DTE) │
                                                                          │                  ▼
                                                          ┌───────────────────────────────────────┐
                                                          │        DETERMINISTIC RAILS             │
                                                          │  1. epistemic gate (conf → mult/veto)   │
                                                          │  2. conviction cap                      │
                                                          │  3. CONTRACT SELECTION (new vs DA)      │
                                                          │     per-strategy delta/DTE picker       │
                                                          │  4. hard floors (never widened)         │
                                                          │     - collateral/premium ceiling        │
                                                          │     - undefined-risk exposure cap       │
                                                          │     - per-underlying / correlation cap  │
                                                          │     - margin-utilization buffer         │
                                                          │     - DTE mandatory-close backstop      │
                                                          │     - expiration-day new-position freeze│
                                                          │  5. execution-mechanics checks (new)    │
                                                          │     - mleg vs sequential-leg routing    │
                                                          │     - equity-leg sequencing (cov. call) │
                                                          │     - spread-width sanity check         │
                                                          └───────────────────────────────────────┘
                                                                          ▼
                                                       paper order(s) → decisions.jsonl
```

A **separate, LLM-free rails sweep** runs on its own schedule (every 15-30 min during market hours)
purely to check exits: DTE-close triggers, profit-target/stop-loss hits, dividend-assignment risk,
margin buffer breaches. Exits never need the LLM — they're pure deterministic monitoring, same
"boring and predictable execution layer" philosophy as DeterministicAgent.

## LLM proposal schema (right brain)

Mirrors DA's `{action, conviction, stop, thesis}` shape, adapted:

```
{
  underlying: str,
  strategy_type: enum[csp, covered_call, long_call, long_put, credit_spread, debit_spread,
                       long_straddle, covered_straddle],
  direction: enum[bullish, bearish, neutral, vol_long, vol_short],
  conviction: float [0-1],
  thesis: str
}
```

The LLM never proposes a strike, delta, or expiration. That's the whole point: the research found
concrete, sourced delta/DTE conventions per strategy (below), and those are exactly the numbers a
deterministic rail should own, not a model's discretion.

## Contract selection rail (new stage, options-specific)

Given `{underlying, strategy_type, direction}`, this stage deterministically picks the actual
contract(s) using per-strategy rules pulled from the research. Format: entry (delta/DTE), exit,
sizing, and primary prior-art source.

### Wheel-adjacent (best-verified, Pass 1)

- **Cash-secured put:** delta 0.20-0.30, DTE 21-45. Exit: 50% profit target OR 21 DTE forced
  close/roll, whichever first. Roll-cap: new strike ≤ old strike + premium received (ThetaGang
  pattern). Sizing: full cash collateral, broker-enforced.
- **Covered call:** delta 0.30-0.50 (~5% OTM), DTE 30-45. Requires owning 100 shares first — must
  be submitted as **two separate orders** (Alpaca disallows an equity leg inside an `mleg` order).
  Strike floor: never below the shares' cost basis (wheel-it pattern). Exit: 50% profit target or
  21 DTE.
- Scoring formula (from `alpacahq/options-wheel`, reusable almost as-is):
  `score = (1 - |delta|) × (250 / (DTE + 5)) × (bid / strike)`, filtered by config
  `DELTA_MIN/MAX`, `YIELD_MIN/MAX`, `SCORE_MIN`.

### Vertical spreads (well-verified, independently reconfirmed across 2 passes)

- **Credit spread:** short strike delta 15-30, DTE 30-45. Exit: 50% profit target (of credit
  received) OR 21 DTE forced close — this exact pair (50%/21 DTE) showed up independently in Pass 2
  and Pass 3, treat it as the most solid convention in the whole research set.
  Sizing: max loss = (strike width × 100) − credit received, fully defined and broker-enforced.
- **Debit spread:** mirror structure, exit convention less independently confirmed — start with the
  same 50%/21 DTE pair and tune from paper-trading data.
- **Execution: always submit as a single Alpaca `mleg` order**, never as sequential individual leg
  orders — sequential legs lose the ability to price at the spread midpoint and eat slippage between
  fills (Pass 2 finding).

### Standalone long options (Pass 3, via `optopsy` + practitioner sources)

- **Long call / long put:** delta ~0.5-0.7 for higher-conviction directional bets (no single
  strong convention here — this is inherently a discretionary/thesis-driven pick, use the LLM's
  `conviction` field to scale delta within a config range rather than a fixed point). DTE ~19-21+
  observed average, but long options need theta runway, so err longer (30-45 DTE) unless conviction
  is high and thesis is short-dated (e.g. an imminent catalyst).
  Exit: 100% profit target / 50% stop-loss via OCO (E*TRADE convention), or force-close at 21 DTE if
  neither hit. Sizing: max loss = 100% of premium paid — size small per position (this is the one
  strategy category where the worst case is total loss of the position's capital, not just margin
  pressure).

### Straddles (Pass 3, least-standardized category — treat conservatively)

- **Long straddle:** buy ATM call + ATM put, same strike/expiry, ~45 DTE, ~delta-neutral at entry.
  Exit: close at 25-50% of max potential gain, don't hold to expiration (theta decay compounds
  against a 2-leg long position). Use around a specific known catalyst (earnings, macro event) per
  the LLM's thesis — this strategy is a poor fit for a "no specific reason" proposal.
- **Covered straddle:** long stock + short ATM call + short ATM put. **Flag from research:** the
  short put here is NOT actually cash-covered in the conventional sense, only margin-covered —
  assignment forces an unplanned additional stock purchase. **Decided:** require full cash
  collateral for the short put leg internally, stricter than what Alpaca's margin math requires,
  specifically because this is the one strategy in scope with a real "surprise capital call" failure
  mode. This is the smallest-allocation, most conservative strategy in the initial rollout (see
  phased rollout below), and gets a tighter per-position cap than the portfolio default (10% of
  equity instead of 15%) given it's the least-standardized, highest-uncertainty strategy in scope.

## Risk profile: MEDIUM risk, HIGH conviction (finalized — operator delegated the calibration)

DeterministicAgent runs `risk_profile: high` (a high-frequency directional stock swing bot).
OptionsAgent is deliberately calibrated differently: **fewer, more selective trades, each sized
meaningfully once taken.** Concretely, this means a hard conviction floor gates entry (no trade at
all below it, not just a smaller trade), and position sizing scales up faster within that gate than
a pure high-risk bot would, but the portfolio-level caps stay tighter than DA's own (options are
already leverage; no need to stack a high-risk portfolio policy on top of instruments that are
intrinsically higher-beta than the underlying).

- **Conviction floor: 0.60.** Below this, the rails pass on the trade entirely — this is the
  concrete mechanism behind "high conviction," not just a phrase. No position is ever opened on a
  low-conviction proposal, regardless of how well it otherwise fits a strategy's rules.
- **Conviction-to-size scaling: 0.60 → minimum size, 0.85+ → max size** (linear between). A proposal
  that barely clears the floor gets the smallest allowed position; only strong-conviction proposals
  get sized up to the per-position cap.

## Hard risk floors (in code, never widened by config or by the model)

Mirrors DA's "rails live in code" philosophy — config can only tighten these, never loosen:

- **Margin-utilization buffer:** never use more than 60% of available options buying power (40%
  headroom). Alpaca liquidates without notice on an EOD margin shortfall (Pass 2 finding) — this
  buffer exists so the bot's own check fires before Alpaca's does. Medium-risk calibration: tighter
  than "use it all," looser than the originally-proposed conservative 50%.
- **Per-position cap:** no more than 15% of equity in notional/collateral for any single position.
- **Per-underlying cap:** no more than 20% of equity across all open positions on one underlying
  (matters once multiple strategy phases are live on the same symbol).
- **Gross exposure cap (new, aggregate):** total notional/collateral across ALL open positions never
  exceeds 60% of equity. Options are already leveraged instruments, so this stays well under DA's
  1.5x-of-equity stock-bot analog — this is the primary knob that keeps "medium risk" from drifting
  into "high risk" as position count grows.
- **Max concurrent positions:** 6. Fewer than the originally-proposed 8 — a direct consequence of
  "high conviction": the bot should be selective enough that 6 genuinely good setups is a normal
  full book, not a constraint that's constantly binding.
- **Undefined-risk exposure cap:** given Alpaca disallows naked legs inside `mleg` orders anyway,
  and the covered straddle's short put is required to be cash-backed internally (below), this lands
  at 0% by design for v1 — flag any position that ends up undefined-risk as a bug, not a feature,
  until this bot has a paper track record.
- **DTE mandatory-close backstop:** every short-premium position (CSP, covered call, credit spread,
  covered straddle) force-closes at 21 DTE regardless of P&L, no exceptions. This is the single
  best-supported numeric rule across all three research passes, and isn't a risk-appetite dial —
  it holds regardless of risk profile.
- **Expiration-day new-position freeze:** no new position opened same-day as its own expiration —
  matches both the pin-risk research and Alpaca's own expiration-day order cutoff.
- **Dividend-assignment check:** before any known ex-dividend date, check whether dividend amount
  exceeds the same-strike put's price for any short ITM call; if so, force-close/roll pre-emptively
  rather than risk early assignment.
- **Weekend carry check:** no new short-premium position opened Friday afternoon without accounting
  for weekend borrow-fee accrual on any short exposure (Pass 2 finding).
- **Spread-width sanity check:** reject/hold multi-leg orders where the combo bid-ask spread exceeds
  a configurable % of the midpoint. **Caveat:** no research pass found a verified numeric threshold
  for this — start with a placeholder (10% of midpoint) and tune against real paper-account quotes;
  don't treat the starting number as validated.

## Execution mechanics (Alpaca-specific, from Pass 1)

- Multi-leg strategies (spreads, straddles) → always `mleg` order type, `market` or `limit` only.
- Covered calls → two separate orders (shares first, then the call), with an explicit state check
  between them — never submit the call leg until the share order is confirmed filled, to avoid an
  orphaned naked call if the share order fails or partially fills.
- CSP buying power = broker-enforced; size to clear Alpaca's own gate, don't re-derive the formula.
- Buy-to-close orders don't free margin to fund themselves — the rails sweep needs to check
  available buying power before submitting a close, same as any opening order.

## Tech stack (decided: mirror DeterministicAgent exactly, since "same pattern" was the ask)

- Python 3, `alpaca-py`, PAPER endpoint only for v1 (same `make_client()` refusal-of-live pattern).
- Persistence: flat JSONL under `data/` (`decisions.jsonl`, matching DA — no DB).
- Module layout mirrors DA's `harness/`: `proposer.py` (DeepSeek API call), `contracts.py` (new — the
  contract-selection rail), `risk_rails.py` (hard floors, code not config), `execution.py` (Alpaca
  order submission incl. mleg/equity-leg sequencing), `exits.py` (the LLM-free rails sweep),
  `notify.py` (Discord), `epistemics.py`, `env.py`.
  Self-learning loops (autoresearch/postmortem-style tuning) deferred to after a paper track record
  exists — not part of v1.
  LLM: the DeepSeek API (`OA_LLM_PROVIDER=deepseek`); the Claude CLI path survives for the Mac only.
- Runtime: Railway container cron and the public read-only dashboard. The
  dashboard is a read-only observer on `$PORT`; it uses a
  background-cached broker snapshot and never imports execution modules. Its
  `/healthz` endpoint is for manual/external probes only and is not configured
  as Railway's container healthcheck, so dashboard failure cannot restart cron.

## Phased rollout (decided)

Building and turning on all 7 strategies simultaneously makes it hard to tell which rule is wrong
if paper trading misbehaves. Research confidence also isn't uniform across strategies. Rolling out
in this order, validating each phase in paper trading before adding the next:

1. **CSP + covered call (the wheel).** Best-verified: two existing open-source bots to port from
   directly, clean state machine, most mechanically simple. **Building this phase first.**
2. **Credit/debit spreads.** Second-best-verified (50%/21 DTE independently reconfirmed twice), but
   needs the `mleg` execution path working correctly first.
3. **Long calls / long puts.** Mechanically simplest (single leg, no assignment complexity) but
   least standardized entry rule — most dependent on the LLM's thesis/conviction rather than a firm
   convention.
4. **Straddles / covered straddles, last.** Least standardized, and covered straddle carries the
   flagged "surprise capital call" risk. Smallest allocation cap of any strategy once live.

## All decisions finalized

1. Rollout order above — confirmed.
2. Hard-floor numbers — finalized under "Risk profile: MEDIUM risk, HIGH conviction" above (60%
   margin buffer, 15% per-position / 20% per-underlying / 60% gross exposure, 21 DTE close, 6 max
   positions, 0.60 conviction floor).
3. Covered straddle short put requires full internal cash-backing — confirmed.
4. Stack mirrors DeterministicAgent (Python, `alpaca-py`, flat JSONL, no DB) — confirmed.
5. Repo/Railway project/Discord channel name: **OptionsAgent** — confirmed.
