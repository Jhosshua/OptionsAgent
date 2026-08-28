"""Stage 2: monetization check. Take the stage-1 rule families and replay them
in the option model (calibrated k) with exits, costs, and the live sequencing,
to get per-contract dollar expectancy. Operator wants the best in-sample
formula frozen as the profile; IS/OOS is reported for context.

Rules under test (all causal, fire at most once per symbol/day):
  A) morning_fade_1015: at 10:15, if close > VWAP AND close > 15m-open-range-high
     -> buy PUT; if below both -> buy CALL. (fade the morning move)
  B) morning_fade_first15: at 10:15, fade the sign of the first-15m return when
     |r15| > 0.15%.
  C) gap_follow_1300: at 13:00, if |gap| > 0.8% follow the gap direction, exit
     at 15:00 (120m) or stops.
  D) morning_fade_vwap_only: at 10:00 fade the VWAP side (0.05% band).
Exit grid per rule: target {25,40,60,80%}, stop {20,30,45%}, hard 15:50 flatten.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from research_scalp_6mo import CONTRACT, HALF_SPREAD_FLOOR, calibrate, \
    load_sessions, session_price_series, norm_cdf

HERE = Path(__file__).parent
DATA = HERE / "data" / "research_scalp_6mo"


def prep(sym, k):
    out = {}
    dates = sorted(load_sessions(sym))
    prev_close = None
    for d in dates:
        bars = load_sessions(sym)[d]
        if len(bars) < 300 or prev_close is None:
            if bars:
                prev_close = bars[-1]["c"]
            continue
        hi15 = max(b["h"] for b in bars[:15])
        lo15 = min(b["l"] for b in bars[:15])
        r15 = (bars[14]["c"] / bars[0]["o"] - 1) * 100
        gap = (bars[0]["o"] / prev_close - 1) * 100
        out[d] = {
            "bars": bars, "gap": gap, "r15": r15, "hi15": hi15, "lo15": lo15,
            "prices": session_price_series(bars, k),
            "vwap": None,  # filled below via signals.session_vwap is whole-day; need per-bar
        }
        # per-bar vwap
        num = den = 0.0
        vw = []
        for b in bars:
            tp = (b["h"] + b["l"] + b["c"]) / 3
            num += tp * b["v"]; den += b["v"]
            vw.append(num / den if den else b["c"])
        out[d]["vwap"] = vw
        prev_close = bars[-1]["c"]
    return out


def rule_signal(sess, rule):
    bars, vw = sess["bars"], sess["vwap"]
    if rule == "A":  # morning_fade_1015
        i = 45  # 10:15
        if i >= len(bars):
            return None
        c = bars[i]["c"]
        if c > vw[i] and c > sess["hi15"]:
            return (i, "put")     # extended up -> fade with put
        if c < vw[i] and c < sess["lo15"]:
            return (i, "call")
        return None
    if rule == "B":  # fade first15
        i = 45
        if i >= len(bars):
            return None
        if sess["r15"] > 0.15:
            return (i, "put")
        if sess["r15"] < -0.15:
            return (i, "call")
        return None
    if rule == "C":  # gap follow at 13:00
        i = 210
        if i >= len(bars) or abs(sess["gap"]) <= 0.8:
            return None
        return (i, "call" if sess["gap"] > 0 else "put")
    if rule == "D":  # fade vwap side at 10:00
        i = 30
        if i >= len(bars):
            return None
        c = bars[i]["c"]
        if c > vw[i] * 1.0005:
            return (i, "put")
        if c < vw[i] * 0.9995:
            return (i, "call")
        return None
    raise ValueError(rule)


def bs_price(s, k_strike, minutes_left, sigma_min, right):
    """Fixed-strike BSM (r=0) priced on realized per-minute vol. `right` in
    call/put — the strike is FIXED at the entry bar's close, unlike the earlier
    floating-ATM series (codex: floating strikes make calls and puts identical
    and cannot monetize direction)."""
    if minutes_left <= 0 or sigma_min <= 0 or s <= 0:
        return 0.0
    T = minutes_left / (60.0 * 6.5 * 252.0)
    v = sigma_min * math.sqrt(252.0 * 6.5 * 60.0)
    vt = v * math.sqrt(T)
    if vt <= 1e-9:
        return max(0.0, (s - k_strike) if right == "call" else (k_strike - s))
    d1 = (math.log(s / k_strike)) / vt + 0.5 * vt
    d2 = d1 - vt
    if right == "call":
        return s * norm_cdf(d1) - k_strike * norm_cdf(d2)
    return k_strike * norm_cdf(-d2) - s * norm_cdf(-d1)


def fixed_price_series(sess, i0, right, k_mult):
    """Option premium path from the entry bar i0 onward at a FIXED strike
    (the entry close), causal realized vol per bar."""
    bars = sess["bars"]
    strike = bars[i0]["c"]
    out = [0.0] * len(bars)
    rets = []
    closes = [b["c"] for b in bars]
    for i, b in enumerate(bars):
        if i > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
        if i < i0:
            continue
        win = rets[-60:]
        sd = statistics.pstdev(win) if len(win) >= 15 else None
        if sd is None or sd <= 0:
            sd = 1e-4
        out[i] = bs_price(closes[i], strike, 390 - i, sd * k_mult, right)
    return out


def replay(sess, sig, target, stop, k, theta_min=10**9):
    """Long option from sig bar; walk exits on FIXED-STRIKE model prices with costs."""
    i0, right = sig
    prices = fixed_price_series(sess, i0, right, k)
    bars = sess["bars"]
    entry = prices[i0] + HALF_SPREAD_FLOOR
    if entry <= 0.05:
        return None
    # 'thesis' for a fade: underlying returning toward VWAP (move against the fade)
    for j in range(i0 + 1, len(prices)):
        px = prices[j]
        eod = j >= len(bars) - 1 or bars[j]["t"] >= "15:50"
        held = j - i0
        if px <= entry * (1 - stop):
            return {"pnl": (px - HALF_SPREAD_FLOOR - entry) * CONTRACT, "reason": "stop", "hold": held}
        if px >= entry * (1 + target):
            return {"pnl": (px - HALF_SPREAD_FLOOR - entry) * CONTRACT, "reason": "target", "hold": held}
        if eod:
            return {"pnl": (px - HALF_SPREAD_FLOOR - entry) * CONTRACT, "reason": "eod", "hold": held}
        if held >= theta_min and px < entry:
            return {"pnl": (px - HALF_SPREAD_FLOOR - entry) * CONTRACT, "reason": "theta", "hold": held}
    return {"pnl": (prices[-1] - HALF_SPREAD_FLOOR - entry) * CONTRACT, "reason": "eod",
            "hold": len(prices) - 1 - i0}


def main():
    all_sessions = {"SPY": load_sessions("SPY"), "QQQ": load_sessions("QQQ")}
    k, cal = calibrate(all_sessions)
    print("calibration:", cal)
    data = {s: prep(s, k) for s in ("SPY", "QQQ")}
    dates = sorted(set(d for s in data for d in data[s]))
    split = dates[len(dates) * 2 // 3]

    results = []
    for rule in "ABCD":
        for tgt in (0.25, 0.40, 0.60, 0.80):
            for stp in (0.20, 0.30, 0.45):
                trades = []
                for sym in ("SPY", "QQQ"):
                    for d, sess in data[sym].items():
                        sig = rule_signal(sess, rule)
                        if not sig:
                            continue
                        r = replay(sess, sig, tgt, stp, k)
                        if r:
                            trades.append({"sym": sym, "date": d, **r})
                if not trades:
                    continue
                def daystats(ts):
                    byd = {}
                    for t in ts:
                        byd[t["date"]] = byd.get(t["date"], 0.0) + t["pnl"]
                    v = list(byd.values())
                    if not v:
                        return {"n": 0, "mean": 0, "t": 0}
                    m = statistics.mean(v)
                    sd = statistics.stdev(v) if len(v) > 1 else 1e-9
                    return {"n": len(v), "mean": m, "t": m / (sd / math.sqrt(len(v)))}
                is_s = daystats([t for t in trades if t["date"] <= split])
                oos_s = daystats([t for t in trades if t["date"] > split])
                results.append({
                    "rule": rule, "target": tgt, "stop": stp,
                    "n": len(trades), "total": sum(t["pnl"] for t in trades),
                    "mean_trade": sum(t["pnl"] for t in trades) / len(trades),
                    "win": sum(1 for t in trades if t["pnl"] > 0) / len(trades),
                    "is": is_s, "oos": oos_s,
                })
    results.sort(key=lambda r: -r["mean_trade"])
    print(f"\nALL {len(results)} configs, top 15 by mean $/contract/trade:")
    for r in results[:15]:
        print(f"  rule {r['rule']} tgt{r['target']:.2f} stp{r['stop']:.2f} | n={r['n']:3d} "
              f"mean {r['mean_trade']:+7.2f} win {r['win']:.0%} total {r['total']:+9.1f} | "
              f"IS {r['is']['mean']:+7.2f}/day t={r['is']['t']:+.2f} | OOS {r['oos']['mean']:+7.2f}/day t={r['oos']['t']:+.2f}")
    (DATA / "mine_stage2.json").open("w").write(json.dumps(
        {"calibration": cal, "results": results}, indent=1))
    print("wrote", DATA / "mine_stage2.json")


if __name__ == "__main__":
    main()
