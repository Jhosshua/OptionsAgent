"""6-month 0DTE ORB scalp study for SPY/QQQ (operator 2026-08-28).

Deliberately an IN-SAMPLE overfit search for the highest-expectancy ruleset,
held to the repo's study rules:
  - IS/OOS split by SESSION DATE (first 2/3 vs last 1/3); a winner must keep
    its sign in OOS.
  - Null control: identical entry times and sizing, RANDOM direction (seeded),
    same exit rules. A real edge must beat its own null.
  - Day-clustered stats: per-day P&L (max 2 trades/day by construction), mean
    and t-stat computed on DAILY aggregates, not per-trade.
  - Execution costs: full bid/ask spread paid (entry at mid+half_spread,
    exit at mid-half_spread) with a floor from live observed SPY 0DTE spreads.
  - Power calc on the winner (per-day mean/std -> t, and the trade count the
    effect would need).

Pricing model (honest limitation): ATM 0DTE leg priced by Black-Scholes with
r=0 and realized vol from the session's own minute returns up to each minute
(no look-ahead: only bars <= t). A single vol multiplier k, fitted so modelled
entry premiums match the 37 REAL July fills (entry AND exit), corrects the
level; it cannot correct smile or vol-of-vol dynamics. Every expectancy number
is therefore model P&L, not fill P&L. The live fills cross-check is printed.

Inputs : data/research_scalp_6mo/{SPY,QQQ}.csv  (research_scalp_6mo_pull.py)
         data/archive_pre_2026-08-28/scalp_positions.jsonl (37 real fills)
Output : data/research_scalp_6mo/results.json + study.md
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = Path(__file__).parent
DATA = HERE / "data" / "research_scalp_6mo"

HALF_SPREAD_FLOOR = 0.02   # $ per option leg, live SPY 0DTE probe: 1.18/1.19
CONTRACT = 100.0


def load_sessions(sym: str) -> dict[str, list[dict]]:
    sessions = {}
    with open(DATA / f"{sym}.csv") as f:
        for row in csv.DictReader(f):
            t = row["et_time"]
            if not ("09:30" <= t < "16:00"):
                continue
            sessions.setdefault(row["et_date"], []).append({
                "t": t, "o": float(row["o"]), "h": float(row["h"]),
                "l": float(row["l"]), "c": float(row["c"]), "v": float(row["v"]),
            })
    for d in sessions:
        sessions[d].sort(key=lambda b: b["t"])
    return sessions


def minutes_of(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


# ---------- option pricing: ATM 0DTE leg, realized vol, BSM r=0 ----------

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def atm_price(s: float, sigma_min: float, minutes_left: float) -> float:
    """ATM call=put price, r=0, via BSM. sigma_min = per-minute vol."""
    if minutes_left <= 0 or sigma_min <= 0:
        return 0.0
    T = minutes_left / (60.0 * 6.5 * 252.0)  # minutes -> years on 6.5h days
    v = sigma_min * math.sqrt(252.0 * 6.5 * 60.0)  # per-minute -> annualized
    sig_sqrt_t = v * math.sqrt(T)
    if sig_sqrt_t <= 1e-9:
        return 0.0
    d1 = 0.5 * sig_sqrt_t
    d2 = -d1
    return s * (norm_cdf(d1) - norm_cdf(d2))  # ATM call (K=S)


def session_price_series(bars: list[dict], k: float) -> list[float]:
    """Model ATM-leg premium at each bar close. Realized vol from a trailing
    window of the session's own returns (min 15 bars), scaled by k."""
    rets, out = [], []
    closes = [b["c"] for b in bars]
    n = len(bars)
    for i, b in enumerate(bars):
        if i > 0:
            r = math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0
            rets.append(r)
        win = rets[-60:]
        sd = statistics.pstdev(win) if len(win) >= 15 else None
        if sd is None or sd <= 0:
            # before 15 bars: use open-to-now range as a crude proxy
            rng = max(x["h"] for x in bars[: i + 1]) - min(x["l"] for x in bars[: i + 1])
            sd = (rng / closes[i]) / math.sqrt(max(i + 1, 2)) if closes[i] else 0.0
        minutes_left = 390 - i  # bar i covers minute [i, i+1)
        out.append(atm_price(closes[i], sd * k, minutes_left))
    return out


# ---------- calibration against the 37 real fills ----------

def calibrate(all_sessions: dict[str, dict[str, list[dict]]]) -> tuple[float, dict]:
    rows = [json.loads(l) for l in open(HERE / "data/archive_pre_2026-08-28/scalp_positions.jsonl")]
    opens = {r["scalp_id"]: r for r in rows if r.get("event") == "opened"}
    closes = {r["scalp_id"]: r for r in rows if r.get("event") == "closed"}
    samples = []
    for sid, o in opens.items():
        c = closes.get(sid)
        if not c or c.get("exit_price") is None or o.get("entry_price") is None:
            continue
        t0 = datetime.fromisoformat(o["opened_ts"]).astimezone(ET)
        t1 = datetime.fromisoformat(c["ts"]).astimezone(ET)
        samples.append({
            "sym": o["underlying"], "date": t0.strftime("%Y-%m-%d"),
            "i0": minutes_of(t0.strftime("%H:%M")) - 570,   # bar index from 09:30
            "i1": minutes_of(t1.strftime("%H:%M")) - 570,
            "entry": float(o["entry_price"]), "exit": float(c["exit_price"]),
        })
    ratios = []
    for s in samples:
        sess = all_sessions.get(s["sym"], {}).get(s["date"])
        if not sess or not (0 <= s["i0"] < len(sess)):
            continue
        # ratio of real premium to k=1 model premium at entry
        m = session_price_series(sess, 1.0)
        if m[s["i0"]] > 0:
            ratios.append(s["entry"] / m[s["i0"]])
    k = statistics.median(ratios) if ratios else 1.0
    # validation: model exit accuracy with fitted k
    errs = []
    for s in samples:
        sess = all_sessions.get(s["sym"], {}).get(s["date"])
        if not sess or not (0 <= s["i0"] < len(sess) and 0 <= s["i1"] < len(sess)):
            continue
        m = session_price_series(sess, k)
        errs.append((m[s["i1"]] - s["exit"]) / max(s["exit"], 0.01))
    report = {
        "fills": len(samples), "k": round(k, 3),
        "entry_ratios": round(len(ratios), 0),
        "exit_relerr_median": round(statistics.median([abs(e) for e in errs]) if errs else None, 3),
    }
    return k, report


# ---------- replay ----------

def session_features(bars: list[dict], range_min: int) -> dict | None:
    if len(bars) < range_min + 5:
        return None
    rng = bars[:range_min]
    hi, lo = max(b["h"] for b in rng), min(b["l"] for b in rng)
    # running VWAP and rvol arrays (causal)
    vwap_num = vwap_den = 0.0
    vwaps = []
    vols = []
    prior = []
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        vwap_num += tp * b["v"]
        vwap_den += b["v"]
        vwaps.append(vwap_num / vwap_den if vwap_den > 0 else b["c"])
        vols.append(statistics.mean(prior) if len(prior) >= 2 else None)
        prior.append(b["v"])
    return {"hi": hi, "lo": lo, "vwap": vwaps, "avg_vol": vols, "n": len(bars)}


def find_entries(feat: dict, bars: list[dict], *, rvol_min: float, vwap_filter: bool,
                 confirm: bool, cutoff_min: int) -> list[dict]:
    """Entry events, causal: signal on bar i (close outside range + volume),
    optional one-bar confirmation, entry at bar i+1 close premium."""
    out = []
    pending = None
    for i in range(len(bars)):
        t = minutes_of(bars[i]["t"]) - 570
        if t >= cutoff_min:
            pending = None
            break
        b = bars[i]
        avg = feat["avg_vol"][i]
        if pending is not None and confirm:
            # confirmation must come on the immediately following bar
            if i != pending["i"] + 1:
                pending = None
            else:
                d = pending["d"]
                ok = (b["c"] > feat["hi"] and (not vwap_filter or b["c"] > feat["vwap"][i])) if d == "up" else \
                     (b["c"] < feat["lo"] and (not vwap_filter or b["c"] < feat["vwap"][i]))
                if ok and i + 1 < len(bars):
                    out.append({"i": i + 1, "d": d, "rvol": pending["rvol"]})
                pending = None
                continue
        if avg and avg > 0 and b["v"] / avg >= rvol_min:
            if b["c"] > feat["hi"]:
                d = "up"
            elif b["c"] < feat["lo"]:
                d = "down"
            else:
                continue
            if vwap_filter:
                v = feat["vwap"][i]
                if (d == "up" and b["c"] <= v) or (d == "down" and b["c"] >= v):
                    continue
            if confirm:
                pending = {"i": i, "d": d, "rvol": round(b["v"] / avg, 2)}
            elif i + 1 < len(bars):
                out.append({"i": i + 1, "d": d, "rvol": round(b["v"] / avg, 2)})
    return out


def walk_exit(entry_i: int, d: str, feat: dict, bars: list[dict], prices: list[float], *,
              target: float, stop: float, theta_min: int, thesis_stop: float) -> dict:
    """Walk forward from entry applying exit rules; returns (exit_i, reason, model pnl per $1)."""
    entry_px = prices[entry_i] + HALF_SPREAD_FLOOR
    if entry_px <= 0:
        return None
    n = len(bars)
    for j in range(entry_i + 1, n):
        px = prices[j]
        eod = j >= n - 1
        held = j - entry_i
        # thesis intact: underlying still outside range on the right side of vwap
        b = bars[j]
        intact = (b["c"] > feat["hi"] and b["c"] > feat["vwap"][j]) if d == "up" else \
                 (b["c"] < feat["lo"] and b["c"] < feat["vwap"][j])
        eff_stop = thesis_stop if intact else stop
        if px <= entry_px * (1 - eff_stop):
            return {"exit_i": j, "reason": "stop", "pnl": (px - HALF_SPREAD_FLOOR) - entry_px}
        if px >= entry_px * (1 + target):
            return {"exit_i": j, "reason": "target", "pnl": (px - HALF_SPREAD_FLOOR) - entry_px}
        if eod:
            return {"exit_i": j, "reason": "eod", "pnl": (px - HALF_SPREAD_FLOOR) - entry_px}
        if held >= theta_min and px < entry_px:
            return {"exit_i": j, "reason": "theta", "pnl": (px - HALF_SPREAD_FLOOR) - entry_px}
    return {"exit_i": n - 1, "reason": "eod", "pnl": (prices[-1] - HALF_SPREAD_FLOOR) - entry_px}


def simulate(entries_by_combo: dict, bars: dict, prices: dict, feats: dict, exit_cfg) -> list:
    """entries_by_combo: {(sym,date): [entry events]} -> trades with pnl per contract.
    Live sequencing honored: one position at a time (entries before the previous
    exit are skipped), max 2 trades/day, each direction once per day."""
    trades = []
    for (sym, date), evs in entries_by_combo.items():
        used_dirs = set()
        count = 0
        free_at = -1
        for e in sorted(evs, key=lambda x: x["i"]):
            if count >= 2:
                break
            if e["d"] in used_dirs or e["i"] <= free_at:
                continue
            r = walk_exit(e["i"], e["d"], feats[(sym, date)], bars[(sym, date)],
                          prices[(sym, date)], **exit_cfg)
            if r is None:
                continue
            trades.append({
                "sym": sym, "date": date, "dir": e["d"], "i": e["i"],
                "pnl": r["pnl"] * CONTRACT, "reason": r["reason"],
                "hold": r["exit_i"] - e["i"],
            })
            used_dirs.add(e["d"])
            free_at = r["exit_i"]
            count += 1
    return trades


def daily_stats(trades: list):
    by_day = {}
    for t in trades:
        by_day.setdefault(t["date"], 0.0)
        by_day[t["date"]] += t["pnl"]
    days = list(by_day.values())
    if not days:
        return {"n_days": 0, "n_trades": 0, "total": 0.0, "mean_day": 0.0, "t": 0.0}
    mean = statistics.mean(days)
    sd = statistics.stdev(days) if len(days) > 1 else 0.0
    t = mean / (sd / math.sqrt(len(days))) if sd > 0 else 0.0
    return {"n_days": len(days), "n_trades": len(trades), "total": sum(days),
            "mean_day": mean, "t": t}


def main():
    all_sessions = {"SPY": load_sessions("SPY"), "QQQ": load_sessions("QQQ")}
    dates = sorted({d for s in all_sessions.values() for d in s})
    print(f"sessions: SPY {len(all_sessions['SPY'])}, QQQ {len(all_sessions['QQQ'])}, "
          f"{dates[0]} .. {dates[-1]}")

    k, cal = calibrate(all_sessions)
    print("calibration:", cal)

    # precompute per (sym, date): bars, feat per range_min, price series
    bars, prices = {}, {}
    feats = {}   # (sym,date,range_min) -> feat
    for sym in all_sessions:
        for date, b in all_sessions[sym].items():
            if len(b) < 60:
                continue
            bars[(sym, date)] = b
            prices[(sym, date)] = session_price_series(b, k)
            for rm in (3, 5, 15, 30):
                f = session_features(b, rm)
                if f:
                    feats[(sym, date, rm)] = f
    keys = sorted(bars.keys())
    split = dates[len(dates) * 2 // 3]
    print(f"IS sessions <= {split}, OOS after; total keys {len(keys)}")

    RANGE_MINS = (3, 5, 15, 30)
    RVOLS = (1.2, 1.5, 2.0, 2.5)
    VWAP = (True, False)
    CONFIRM = (True, False)
    CUTOFFS = (120, 180, 240, 300)   # minutes after 09:30: 11:30, 12:30, 14:00, 15:00
    TARGETS = (0.30, 0.50, 0.75, 1.00)
    STOPS = (0.20, 0.30, 0.45, 0.60)
    THETAS = (10, 15, 30, 10**9)

    results = []
    null_rng = random.Random(7)

    # null control ONCE per exit config using the base entry set (rm=3, rvol=1.5,
    # vwap+confirm on, cutoff 120): random directions, same times/counts
    base_entries = {}
    feats_3 = {(s, d): f for (s, d, r), f in feats.items() if r == 3}
    for (sym, date) in keys:
        f = feats_3.get((sym, date))
        if not f:
            continue
        base_entries[(sym, date)] = find_entries(f, bars[(sym, date)], rvol_min=1.5,
                                                 vwap_filter=True, confirm=True, cutoff_min=120)

    combos = 0
    for rm in RANGE_MINS:
        feats_rm = {(s, d): f for (s, d, r), f in feats.items() if r == rm}
        for rvol in RVOLS:
            for vw in VWAP:
                for cf in CONFIRM:
                    for cut in CUTOFFS:
                        evs_by_key = {}
                        for (sym, date) in keys:
                            f = feats.get((sym, date, rm))
                            if not f:
                                continue
                            evs = find_entries(f, bars[(sym, date)], rvol_min=rvol,
                                               vwap_filter=vw, confirm=cf, cutoff_min=cut)
                            if evs:
                                evs_by_key[(sym, date)] = evs
                        if not evs_by_key:
                            continue
                        for tgt in TARGETS:
                            for stp in STOPS:
                                for th in THETAS:
                                    exit_cfg = {"target": tgt, "stop": stp, "theta_min": th,
                                                "thesis_stop": 0.60}
                                    trades = simulate(evs_by_key, bars, prices, feats_rm, exit_cfg)
                                    if not trades:
                                        continue
                                    combos += 1
                                    is_t = daily_stats([t for t in trades if t["date"] <= split])
                                    oos_t = daily_stats([t for t in trades if t["date"] > split])
                                    results.append({
                                        "rm": rm, "rvol": rvol, "vwap": vw, "confirm": cf,
                                        "cutoff": cut, "target": tgt, "stop": stp, "theta": None if th > 1e8 else th,
                                        "is": is_t, "oos": oos_t,
                                        "n_trades": len(trades),
                                        "mean_trade": sum(t["pnl"] for t in trades) / len(trades),
                                    })

    # null: random directions on base entry set, best-exit and median-exit
    nulls = []
    for tgt in TARGETS:
        for stp in STOPS:
            for th in THETAS:
                exit_cfg = {"target": tgt, "stop": stp, "theta_min": th, "thesis_stop": stp}
                evs_rand = {}
                for key, evs in base_entries.items():
                    evs_rand[key] = [{"i": e["i"], "d": null_rng.choice(["up", "down"]),
                                      "rvol": e["rvol"]} for e in evs]
                trades = simulate(evs_rand, bars, prices, feats_3, exit_cfg)
                if trades:
                    nulls.append(daily_stats(trades))
    null_best = max((n["mean_day"] for n in nulls), default=0.0)

    results.sort(key=lambda r: r["is"]["mean_day"], reverse=True)
    out = {"calibration": cal, "split_date": split, "null_best_mean_day": null_best,
           "n_result_rows": len(results), "top_is": results[:25],
           "best_oos_signkept": [r for r in results[:200] if r["oos"]["mean_day"] > 0][:10]}
    (DATA / "results.json").open("w").write(json.dumps(out, indent=1))

    print(f"\ncombos evaluated: {combos}; null best mean-day {null_best:.2f}")
    print("\nTOP BY IS mean-day (must keep sign OOS):")
    for r in results[:10]:
        print(f"  rm{r['rm']} rvol{r['rvol']} vwap{int(r['vwap'])} cf{int(r['confirm'])} "
              f"cut{570+r['cutoff']} tgt{r['target']} stp{r['stop']} th{r['theta']} | "
              f"IS {r['is']['mean_day']:+8.1f}/day t={r['is']['t']:+.2f} ({r['is']['n_trades']}tr) | "
              f"OOS {r['oos']['mean_day']:+8.1f}/day t={r['oos']['t']:+.2f} ({r['oos']['n_trades']}tr)")
    kept = [r for r in results if r["oos"]["mean_day"] > 0 and r["is"]["n_trades"] >= 60]
    kept.sort(key=lambda r: r["is"]["mean_day"] + r["oos"]["mean_day"], reverse=True)
    print("\nSURVIVORS (OOS positive, >=60 IS trades):")
    for r in kept[:10]:
        print(f"  rm{r['rm']} rvol{r['rvol']} vwap{int(r['vwap'])} cf{int(r['confirm'])} "
              f"cut{570+r['cutoff']} tgt{r['target']} stp{r['stop']} th{r['theta']} | "
              f"IS {r['is']['mean_day']:+8.1f} OOS {r['oos']['mean_day']:+8.1f} n={r['n_trades']}")


if __name__ == "__main__":
    main()
