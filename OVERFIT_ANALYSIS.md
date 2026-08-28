# OptionsAgent historical analysis — 2026-08-27

This report is based on the archived Railway volume in `data/` and is
reproducible with:

```bash
python3 research_scalp_history.py
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

## Seller results

The credit-spread seller had **-$644 realized across 8 filled structures with
non-zero P/L**: 3 winners and 5 losers. The realized results were CCL -$306,
MARA -$25, AAL -$57, VZ -$221, CCL +$45, SOFI +$40, AAL -$165, and F +$45.
The sample is too small and structurally mixed (legacy stop-loss behavior,
changed width, changed exit policy, and one still-open structure) to safely
fit a new seller rule. The existing defined-risk and 21-DTE rails remain in
place.

## Implemented change

`ScalpRails.entry_cutoff_et` is now **11:30 ET** and
`ScalpRails.max_trades_per_day` is now **2**; the documentation mirrors in
`config/config.json` match them. The change is intentionally narrow: it does
not change position size, stop loss, RVOL, direction, underlying, or seller
behavior. Future results should be scored prospectively against both gates,
with at least 30 new round-trips before another parameter change.

This repository remains **not deployed**. The original Railway project,
volume, broker keys, LLM key, and Discord webhook were deleted on 2026-08-02;
restarting requires a new paper account and a new Railway deployment target.
