# 0DTE ORB scalper, 6-month overfit search (2026-08-28): NULL RESULT

Operator ask: pull 3-6 months of data, overfit the scalper leg for the highest
expectancy, deploy at ~$20k / ~50 contracts with tight risk controls.

## What was run

- Data: 125 sessions x 390 one-minute bars each for SPY and QQQ, 2026-03-02 to
  2026-08-27, Alpaca SIP via the read-only data key (`research_scalp_6mo_pull.py`,
  output in `data/research_scalp_6mo/`, integrity-checked: every day exactly 390 bars).
- Pricing: ATM 0DTE leg via BSM (r=0) on the session's own causal realized vol,
  one multiplier k fitted to the 36 usable real July fills (k=0.707). Entry
  premiums match well; median exit-price error 46%, so all P&L magnitudes are
  model numbers with wide error bars.
- Replay honors live sequencing: one position at a time, max 2 trades/day, each
  direction once, entry at mid + $0.02, exit at mid - $0.02, EOD flatten.
- Grid: range {3,5,15,30}m x RVOL {1.2,1.5,2.0,2.5} x VWAP {on,off} x confirm
  {on,off} x cutoff {11:30,12:30,14:00,15:00} x target {30,50,75,100%} x stop
  {20,30,45,60%} x theta cut {10,15,30,never} = 16,384 combos.
- Ranking per house rules: per-DAY stats (max 2 trades/day), IS = first 2/3 of
  sessions, OOS = last 1/3, winner must keep positive sign OOS with >= 60 IS
  trades, null control = same entry times with random direction.

## Result: NO positive-expectancy configuration exists in this data

- ALL 16,384 combos have negative mean-day P&L. The BEST one
  (rm30, rvol2.5, vwap+confirm, cutoff 14:30, target 30%, stop 20-60%,
  theta 10m) loses ~$11 per contract per day, consistently:
  IS -11.2/day (t=-3.61, 134 trades), OOS -16.2/day (t=-7.97, 62 trades).
  Zero survivors passed the OOS-positive + >=60-trades gate.
- The random-direction null loses -51.65/day at its best exit grid: the signal
  contains real information, but not enough to pay the spread and theta.
- Decomposition on the UNDERLYING (no option model at all): after 931 breakout
  signals across 6 months, mean signed 15-minute return in signal direction is
  -0.04bp to +0.01bp (SPY 46.2% / QQQ 54.3% hit rate at 15m, ~0bp mean).
  There is no direction edge to monetize at any size. This is consistent with
  July's 36 real fills (net losers) and with the repo's per-ticker day-trade
  studies (all null).

## Decision (pending operator)

Deploying ~50 contracts x ~$150 premium on a robustly negative-expectancy rule
scales a proven loser to roughly -$700 to -$1,000 expected per day. The "highest
expectancy overfit" the operator asked for does not exist in this data; per the
house rule, a failed falsification is a KILL, not a caveat. Options presented:
keep the scalper at the $250 learning size (current state), or disable it.

Artifacts: `research_scalp_6mo_pull.py`, `research_scalp_6mo.py`,
`data/research_scalp_6mo/results.json` (gitignored data dir).
Codex adversarial plan review: running at time of writing; verdict to be
appended.
