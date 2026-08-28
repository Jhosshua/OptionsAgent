# OptionsAgent historical analysis — 2026-08-27

This report is based on the archived Railway volume in `data/` and is
reproducible with:

```bash
python3 research_scalp_history.py
python3 research_credit_spread_history.py
```

## Scope and limits

The archive covers 2026-07-07 through 2026-07-31. It contains 37 scalp
registry pairs across 15 trading days: 36 with realized P/L and one vanished
position with unknown P/L. The seller registry contains 11 unique structure
IDs (12 opening-event records because one legacy MARA event is duplicated),
including 8 filled structures with realized non-zero P/L, one never-filled order
recorded at $0, one still-open structure, and one legacy long put with unknown
P/L.

The scalp replay is a conditional replay of fills that actually occurred. It
does not recreate historical option bid/ask paths, so it cannot claim that a
filtered rule would have entered every trade it selects or that skipped trades
would have been available. The result is research evidence, not a complete
options backtest.

## Scalp results

Overall realized P/L was **-$367 across 36 trades**, with a 27.8% win rate.
The daily results were:

| ET date | Trades | Realized P/L | Wins |
|---|---:|---:|---:|
| 2026-07-10 | 3 | -$154 | 0 |
| 2026-07-13 | 2 | -$140 | 0 |
| 2026-07-14 | 3 | -$151 | 0 |
| 2026-07-15 | 2 | -$135 | 0 |
| 2026-07-16 | 3 | -$118 | 0 |
| 2026-07-17 | 2 | +$44 | 1 |
| 2026-07-20 | 2 | +$27 | 1 |
| 2026-07-21 | 2 | -$156 | 0 |
| 2026-07-22 | 2 | +$53 | 1 |
| 2026-07-23 | 2 | +$76 | 1 |
| 2026-07-24 | 3 | -$17 | 1 |
| 2026-07-27 | 2 | +$213 | 2 |
| 2026-07-28 | 3 | +$20 | 1 |
| 2026-07-30 | 2 | -$167 | 0 |
| 2026-07-31 | 3 | +$238 | 2 |

Every realized entry at or after 11:30 ET lost: **12 trades, -$681, 0 wins**.
Entries before 11:30 ET were **24 trades, +$314, 10 wins**. This is the only
simple filter with enough observations and a clear enough separation to ship
as a hard timing gate. The independent review also tested the existing
three-trade daily cap: retaining at most two pre-cutoff entries kept 23 known
trades, 10 winners, and **+$345** in-sample. That cap is now shipped alongside
the cutoff, but remains selection-biased and must be held unchanged during the
next prospective sample.

Other slices were not promoted: QQQ was -$52 over 14 realized trades, SPY was
-$315 over 22; down trades were -$116 over 20 and up trades were -$251 over
16. High-RVOL slices looked better only because they contained 7 or fewer
trades and still included losses. These are not sufficient grounds for
underlying, direction, or RVOL overfitting.

## Per-trade record

The script prints every trade with ET entry/exit time, underlying, direction,
RVOL, quantity, P/L, and exit reason. The raw source of truth is
`data/scalp_positions.jsonl`, joined to entry metadata in
`data/scalp_decisions.jsonl`.

## Multi-day credit-spread seller results

The credit-spread seller had **-$644 realized across 8 filled structures with
non-zero P/L**: 3 winners and 5 losers. The realized results were CCL -$306,
MARA -$25, AAL -$57, VZ -$221, CCL +$45, SOFI +$40, AAL -$165, and F +$45.
There are 5 distinct entry days, one never-filled order at $0, and one still-
open structure with unknown P/L. This is a conditional registry replay, not a
full quote/fill backtest.

At the operator's explicit request to maximize in-sample P/L, the hard
historical-winner profile is:

| Underlying | Direction | Width | Minimum credit | Archived result |
|---|---|---:|---:|---:|
| CCL | bullish put | >= $1.50 | >= $0.29 | +$45 |
| SOFI | bullish put | >= $1.00 | >= $0.23 | +$40 |
| F | bearish call | <= $0.50 | >= $0.06 | +$45 |

Conditional replay of those 3 realized records is **+$130, 3/3 wins**. Every
other known non-zero record is rejected by the profile. That 100% result is
selection-biased and has no statistical significance; it is the requested
overfit, not a claim that these symbols or thresholds have a durable edge.

## Implemented change

`ScalpRails.entry_cutoff_et` is now **11:30 ET** and
`ScalpRails.max_trades_per_day` is now **2**. The credit-spread seller now
also applies `credit_spread_overfit_decision()` as a hard post-selection gate
in `run_cycle.py`; the config mirror documents the profile but cannot loosen
it. The profile must remain unchanged for a prospective sample of at least 30
credit-spread round-trips before it is relaxed or refit.

The local `claude-ds` wrapper was found and attempted, but the requested
DeepSeek session hung without output and a direct API fallback reset the
connection. No DeepSeek recommendation was received or represented as fact;
`DEEPSEEK_CREDIT_SPREAD_PROMPT.md` contains the exact independent-review prompt.

This repository remains **not deployed**. The original Railway project,
volume, broker keys, LLM key, and Discord webhook were deleted on 2026-08-02;
restarting requires a new paper account and a new Railway deployment target.
