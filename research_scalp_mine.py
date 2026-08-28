"""Broad in-sample miner: find ANY causal intraday SPY/QQQ rule with positive
expectancy over 2026-03-02..2026-08-27, to be frozen as an overfit profile
(operator instruction 2026-08-28: find the formula that WOULD have worked in
this window; deploy at size; treat live trading as the out-of-sample test).

Stage 1 (this file): underlying-level mining, no option model. Enumerate
candidate events x direction modes x time filters, score mean signed forward
return (30/60/120m) in bp. Fast, thousands of rules.
Stage 2: top rules replayed in the option model for per-contract dollars.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path

DATA = Path(__file__).parent / "data" / "research_scalp_6mo"
FWD = (30, 60, 120)


def load(sym):
    sessions = {}
    with open(DATA / f"{sym}.csv") as f:
        for row in csv.DictReader(f):
            if not ("09:30" <= row["et_time"] < "16:00"):
                continue
            sessions.setdefault(row["et_date"], []).append({
                "t": row["et_time"], "o": float(row["o"]), "h": float(row["h"]),
                "l": float(row["l"]), "c": float(row["c"]), "v": float(row["v"]),
            })
    for d in sessions:
        sessions[d].sort(key=lambda b: b["t"])
    return sessions


def mi(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def prep(sym):
    """Per session: bars, vwap array, prev close, first-15 return, rvol arrays."""
    sessions = load(sym)
    dates = sorted(sessions)
    out = {}
    prev_close = None
    for d in dates:
        bars = sessions[d]
        if len(bars) < 300 or prev_close is None:
            if bars:
                prev_close = bars[-1]["c"]
            continue
        num = den = 0.0
        vwap = []
        for b in bars:
            tp = (b["h"] + b["l"] + b["c"]) / 3
            num += tp * b["v"]; den += b["v"]
            vwap.append(num / den if den else b["c"])
        gap = (bars[0]["o"] / prev_close - 1) * 100
        r15 = (bars[14]["c"] / bars[0]["o"] - 1) * 100
        out[d] = {"bars": bars, "vwap": vwap, "gap": gap, "r15": r15,
                  "open": bars[0]["o"], "hi15": max(b["h"] for b in bars[:15]),
                  "lo15": min(b["l"] for b in bars[:15])}
        prev_close = bars[-1]["c"]
    return out


def signed_fwd(bars, i, direction, horizon):
    j = min(i + horizon, len(bars) - 1)
    r = (bars[j]["c"] / bars[i]["c"] - 1) * 10000 * direction  # bp
    return r, j < len(bars) - 1 or horizon >= len(bars) - 1 - i


def collect(sym_data, event_fn, times, horizons, modes=("follow", "fade")):
    """event_fn(session, i) -> direction (+1/-1/0) of the RAW move; mode flips."""
    res = {}
    for d, s in sym_data.items():
        bars = s["bars"]
        for t in times:
            i = t - 570
            if not (15 <= i < len(bars) - 130):
                continue
            raw = event_fn(s, i)
            if raw == 0:
                continue
            for mode in modes:
                direction = raw if mode == "follow" else -raw
                for h in horizons:
                    r, _ = signed_fwd(bars, i, direction, h)
                    key = (t, event_fn.__name__, mode, h)
                    res.setdefault(key, []).append((d, r))
    return res


def main():
    spy, qqq = prep("SPY"), prep("QQQ")
    print(f"sessions: SPY {len(spy)} QQQ {len(qqq)}")

    # ---- event definitions (all causal: use data up to bar i inclusive) ----

    def vwap_side(s, i):
        c = s["bars"][i]["c"]
        return 1 if c > s["vwap"][i] * 1.0005 else (-1 if c < s["vwap"][i] * 0.9995 else 0)

    def first15_dir(s, i):
        return 1 if s["r15"] > 0.15 else (-1 if s["r15"] < -0.15 else 0)

    def gap_dir(s, i):
        return 1 if s["gap"] > 0.3 else (-1 if s["gap"] < -0.3 else 0)

    def big_gap_dir(s, i):
        return 1 if s["gap"] > 0.8 else (-1 if s["gap"] < -0.8 else 0)

    def range_break(s, i):
        c = s["bars"][i]["c"]
        if i < 15:
            return 0
        return 1 if c > s["hi15"] else (-1 if c < s["lo15"] else 0)

    def spike_min(s, i):
        if i < 20:
            return 0
        b = s["bars"][i]
        rets = [s["bars"][k]["c"] / s["bars"][k - 1]["c"] - 1 for k in range(i - 20, i)]
        sd = statistics.pstdev(rets) or 1e-9
        r = b["c"] / s["bars"][i - 1]["c"] - 1
        z = r / sd
        return 1 if z > 3 else (-1 if z < -3 else 0)

    def rvol_regime(s, i):
        if i < 30:
            return 0
        avg = statistics.mean([b["v"] for b in s["bars"][:i]]) or 1e-9
        rv = s["bars"][i]["v"] / avg
        if rv < 2.0:
            return 0
        return 1 if s["bars"][i]["c"] > s["bars"][i - 1]["c"] else -1

    def new_high(s, i):
        if i < 30:
            return 0
        c = s["bars"][i]["c"]
        prior_hi = max(b["h"] for b in s["bars"][:i])
        prior_lo = min(b["l"] for b in s["bars"][:i])
        if c > prior_hi:
            return 1
        if c < prior_lo:
            return -1
        return 0

    events = [vwap_side, first15_dir, gap_dir, big_gap_dir, range_break,
              spike_min, rvol_regime, new_high]
    times = [600, 615, 630, 660, 690, 780, 840]  # 10:00,10:15,10:30,11:00,11:30,13:00,14:00

    rows = []
    # pooled universe keyed by (symbol, date) — a plain dict merge would let QQQ
    # sessions overwrite same-date SPY sessions (codex review 2026-08-28)
    both = {(f"{s}|{d}"): sess for s, dd in (("SPY", spy), ("QQQ", qqq))
            for d, sess in dd.items()}
    for label, data in (("SPY", spy), ("QQQ", qqq), ("BOTH", both)):
        for ev in events:
            res = collect(data, ev, times, FWD)
            for (t, name, mode, h), obs in res.items():
                rets = [r for _, r in obs]
                n = len(rets)
                if n < 40:
                    continue
                mean = statistics.mean(rets)
                sd = statistics.stdev(rets) or 1e-9
                tstat = mean / (sd / n ** 0.5)
                # day clustering: mean of daily means
                byd = {}
                for d, r in obs:
                    byd.setdefault(d, []).append(r)
                dmeans = [statistics.mean(v) for v in byd.values()]
                dt = statistics.mean(dmeans) / ((statistics.stdev(dmeans) or 1e-9) / len(dmeans) ** 0.5)
                win = sum(1 for r in rets if r > 0) / n
                rows.append({"universe": label, "event": name, "time": t, "mode": mode,
                             "h": h, "n": n, "mean_bp": mean, "t": tstat, "day_t": dt,
                             "win": win, "days": len(dmeans)})

    rows.sort(key=lambda r: (r["universe"] != "BOTH", -abs(r["mean_bp"])))
    print("\nTOP 30 RULES BY |mean bp| (raw underlying, per-trade, incl. BOTH pool):")
    for r in rows[:30]:
        print(f"  {r['universe']:4s} {r['event']:12s} @{r['time']//60:02d}:{r['time']%60:02d} "
              f"{r['mode']:6s} hold{r['h']:3d}m | n={r['n']:4d} days={r['days']:3d} "
              f"mean {r['mean_bp']:+7.2f}bp t={r['t']:+6.2f} day_t={r['day_t']:+6.2f} win {r['win']:.0%}")

    pos = [r for r in rows if r["mean_bp"] > 0 and r["day_t"] > 1.5 and r["n"] >= 40]
    pos.sort(key=lambda r: -r["mean_bp"])
    print(f"\n{len(pos)} rules positive with day_t>1.5; top 15 by mean bp:")
    for r in pos[:15]:
        print(f"  {r['universe']:4s} {r['event']:12s} @{r['time']//60:02d}:{r['time']%60:02d} "
              f"{r['mode']:6s} hold{r['h']:3d}m | n={r['n']:4d} mean {r['mean_bp']:+7.2f}bp "
              f"day_t={r['day_t']:+6.2f} win {r['win']:.0%}")

    import json
    out = Path(__file__).parent / "data" / "research_scalp_6mo" / "mine_stage1.json"
    out.open("w").write(json.dumps({"rows": rows[:200], "positives": pos[:50]}, indent=1))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
