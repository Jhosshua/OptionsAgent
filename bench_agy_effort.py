"""Bench: Gemini 3.8 Flash low vs medium effort through agy on one real bundle.

Operator 2026-09-13. Runs the production proposer call (harness/proposer.py
_propose_with_agy, same prompt, schema and flags) N times per model,
interleaved so time-of-day drift hits both arms equally. Places no orders:
the proposer is read-only and nothing here touches the broker.

    python3 bench_agy_effort.py BUNDLE.json OUT.json [ROUNDS]

BUNDLE.json is the {phase, allowed_strategies, watchlist} dict run_cycle.py
builds. Set OA_AGY_CLI to the agy binary (on the Mac: ~/.local/bin/agy-bin,
the raw binary, not the shell wrapper that adds --dangerously-skip-permissions).
"""

from __future__ import annotations

import json
import sys
import time

from harness import proposer

MODELS = proposer.ALLOWED_MODELS


def one_call(bundle: dict, model: str) -> dict:
    started = time.monotonic()
    try:
        proposals = proposer._propose_with_agy(bundle, model=model)
        error = None
    except Exception as exc:  # a failure is a result here, not a crash
        proposals, error = [], f"{type(exc).__name__}: {exc}"[:400]
    return {
        "model": model,
        "ok": error is None,
        "latency_s": round(time.monotonic() - started, 1),
        "error": error,
        "proposals": [
            {
                "underlying": p.underlying,
                "strategy_type": p.strategy_type,
                "direction": p.direction,
                "conviction": p.conviction,
                "thesis": p.thesis,
            }
            for p in proposals
        ],
    }


def summarize(runs: list[dict], bundle: dict) -> dict:
    allowed = set(bundle.get("allowed_strategies") or [])
    out = {}
    for model in MODELS:
        mine = [r for r in runs if r["model"] == model]
        ok = [r for r in mine if r["ok"]]
        latencies = sorted(r["latency_s"] for r in ok)
        ideas = [p for r in ok for p in r["proposals"]]
        sets = [
            tuple(sorted((p["underlying"], p["direction"]) for p in r["proposals"] if p["conviction"] >= 0.60))
            for r in ok
        ]
        modal = max(set(sets), key=sets.count) if sets else ()
        out[model] = {
            "calls": len(mine),
            "ok": len(ok),
            "median_latency_s": latencies[len(latencies) // 2] if latencies else None,
            "max_latency_s": latencies[-1] if latencies else None,
            "ideas_per_call": [len(r["proposals"]) for r in ok],
            "tradeable_per_call": [len(s) for s in sets],
            "outside_allowed_strategies": sum(1 for p in ideas if p["strategy_type"] not in allowed),
            "credit_spread_neutral": sum(
                1 for p in ideas if p["strategy_type"] == "credit_spread" and p["direction"] == "neutral"
            ),
            "same_as_modal_answer": sum(1 for s in sets if s == modal),
            "modal_answer": list(modal),
        }
    return out


def main() -> None:
    bundle = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    runs = []
    for i in range(rounds):
        order = MODELS if i % 2 == 0 else tuple(reversed(MODELS))
        for model in order:
            run = one_call(bundle, model)
            run["round"] = i + 1
            runs.append(run)
            print(
                f"round {i + 1} {model}: ok={run['ok']} {run['latency_s']}s "
                f"ideas={len(run['proposals'])} {run['error'] or ''}",
                flush=True,
            )
    report = {"summary": summarize(runs, bundle), "runs": runs}
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
