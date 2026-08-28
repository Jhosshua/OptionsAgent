"""Stage 3: share-based replay of the mined rules. Model-free: bar prices plus
a realistic spread cost (SPY/QQQ ~$0.01 round trip on ~$700-770 = 1.3bp).
Position = $20,000 notional. Live rails: one position at a time, max 2 trades
per day per account, hard 15:50 ET flatten, stop options.

Rules (causal, once per symbol/day):
  C  QQQ gap-follow: at 13:00, if |gap|>0.8% hold WITH the gap until 15:00.
  A  morning fade: at 10:15, if close above VWAP and above the 15m opening
     range high, hold SHORT until 12:15; below both, LONG. (SPY+QQQ)
  B  SPY first15 fade: at 10:15 fade the first-15m return when |r15|>0.15%.
  D  vwap fade: at 10:00 fade the VWAP side (0.05% band), exit 12:00. (SPY+QQQ)
Stops: none / 0.4% / 0.7% from entry. Reports mean $/trade, per-day stats,
IS/OOS (first 2/3 vs last 1/3 of sessions) and the total on $20k sizing.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from research_scalp_6mo import load_sessions

HERE = Path(__file__).parent
NOTIONAL = 20_000.0
ROUND_TRIP_BP = 1.3   # spread cost, bp of notional
HORIZON = {"A": 120, "B": 120, "C": 120, "D": 120}  # minutes held if no stop


def prep(sym):
    dates = sorted(load_sessions(sym))
    bars_by_day = {d: load_sessions(sym)[d] for d in dates}
    out, prev_close = {}, None
    for d in dates:
        bars = bars_by_day[d]
        if len(bars) < 300 or prev_close is None:
            if bars:
                prev_close = bars[-1]["c"]
            continue
        num = den = 0.0
        vw = []
        for b in bars:
            tp = (b["h"] + b["l"] + b["c"]) / 3
            num += tp * b["v"]; den += b["v"]
            vw.append(num / den if den else b["c"])
        out[d] = {"bars": bars, "vwap": vw,
                  "gap": (bars[0]["o"] / prev_close - 1) * 100,
                  "hi15": max(b["h"] for b in bars[:15]),
                  "lo15": min(b["l"] for b in bars[:15]),
                  "r15": (bars[14]["c"] / bars[0]["o"] - 1) * 100}
        prev_close = bars[-1]["c"]
    return out


def rule_signal(sess, rule, sym):
    bars, vw = sess["bars"], sess["vwap"]
    if rule == "C":
        if sym != "QQQ":
            return None
        i = 210
        if i >= len(bars) or abs(sess["gap"]) <= 0.8:
            return None
        return (i, 1 if sess["gap"] > 0 else -1)
    if rule in ("A", "B"):
        i = 45
        if i >= len(bars):
            return None
        if rule == "A":
            c = bars[i]["c"]
            if c > vw[i] and c > sess["hi15"]:
                return (i, -1)
            if c < vw[i] and c < sess["lo15"]:
                return (i, 1)
            return None
        if sess["r15"] > 0.15:
            return (i, -1)
        if sess["r15"] < -0.15:
            return (i, 1)
        return None
    if rule == "D":
        i = 30
        if i >= len(bars):
            return None
        c = bars[i]["c"]
        if c > vw[i] * 1.0005:
            return (i, -1)
        if c < vw[i] * 0.9995:
            return (i, 1)
        return None
    raise ValueError(rule)


def replay_share(sess, sig, stop_pct):
    bars = sess["bars"]
    i0, side = sig
    entry = bars[i0]["c"]
    exit_i = min(i0 + 120, len(bars) - 1)
    for j in range(i0 + 1, i0 + 121):
        if j >= len(bars):
            break
        px, lo = bars[j]["c"], bars[j]["l"]
        move = (lo / entry - 1) * side if side > 0 else (bars[j]["h"] / entry - 1) * side
        if stop_pct and move <= -stop_pct:
            exit_i = j
            break
        if bars[j]["t"] >= "15:50":
            exit_i = j
            break
    else:
        exit_i = min(i0 + 120, len(bars) - 1)
    exit_px = bars[exit_i]["c"]
    gross_bp = (exit_px / entry - 1) * 10000 * side
    net_bp = gross_bp - ROUND_TRIP_BP
    return net_bp * NOTIONAL / 10000, exit_i - i0


def main():
    data = {"SPY": prep("SPY"), "QQQ": prep("QQQ")}
    dates = sorted(set(d for s in data for d in data[s]))
    split = dates[len(dates) * 2 // 3]
    rows = []
    for rule in "ABCD":
        for stop in (None, 0.004, 0.007):
            trades = []
            for sym in data:
                for d, sess in data[sym].items():
                    sig = rule_signal(sess, rule, sym)
                    if not sig:
                        continue
                    pnl, hold = replay_share(sess, sig, stop)
                    trades.append({"sym": sym, "date": d, "pnl": pnl, "hold": hold})
            if not trades:
                continue

            def ds(ts):
                byd = {}
                for t in ts:
                    byd[t["date"]] = byd.get(t["date"], 0.0) + t["pnl"]
                v = list(byd.values())
                m = statistics.mean(v)
                sd = statistics.stdev(v) if len(v) > 1 else 1e-9
                return {"days": len(v), "mean": m, "t": m / (sd / math.sqrt(len(v)))}
            is_t, oos_t = (ds([t for t in trades if t["date"] <= split]),
                           ds([t for t in trades if t["date"] > split]))
            rows.append({
                "rule": rule, "stop": stop, "n": len(trades),
                "mean": statistics.mean([t["pnl"] for t in trades]),
                "total": sum(t["pnl"] for t in trades),
                "win": sum(1 for t in trades if t["pnl"] > 0) / len(trades),
                "is": is_t, "oos": oos_t,
                "avg_hold": statistics.mean([t["hold"] for t in trades]),
            })
    rows.sort(key=lambda r: -r["mean"])
    print(f"NOTIONAL ${NOTIONAL:,.0f}/position, spread {ROUND_TRIP_BP}bp round trip\n")
    for r in rows:
        print(f"  rule {r['rule']} stop={r['stop'] or 'none':>5} | n={r['n']:3d} "
              f"mean {r['mean']:+8.2f} win {r['win']:.0%} total {r['total']:+9.0f} "
              f"hold {r['avg_hold']:.0f}m | IS {r['is']['mean']:+8.2f}/day t={r['is']['t']:+5.2f} | "
              f"OOS {r['oos']['mean']:+8.2f}/day t={r['oos']['t']:+5.2f}")
    (HERE / "data/research_scalp_6mo/mine_stage3.json").open("w").write(
        json.dumps(rows, indent=1))
    print("\nwrote mine_stage3.json")


if __name__ == "__main__":
    main()
