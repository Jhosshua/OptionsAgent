# Gemini 3.8 Flash low vs medium effort (agy CLI) — 2026-09-13

Operator asked to replace DeepSeek and the Claude Code CLI with the Antigravity
CLI and to test Gemini 3.8 Flash at low and medium effort for the daily proposal.

## Method

- Input: one real bundle built read-only from the Sep 11 close (13 names,
  phase `credit_spreads_only`, 2.9 KB). No orders; nothing touched the broker.
- Call: the production path, `harness/proposer.py::_propose_with_agy` (same
  prompt, JSON schema and flags), on the Mac with the raw `agy-bin` binary.
- 6 calls per setting, interleaved (low/medium, then medium/low) so time drift
  hits both. Script: `bench_agy_effort.py`. Raw runs:
  `research_agy_effort_2026-09-13.json`.

## Results

| | low | medium |
|---|---|---|
| Calls OK | 6/6 | 6/6 |
| Median / max latency | 7.3s / 21.2s | 16.4s / 41.9s |
| Ideas per call | 2,2,2,2,2,2 | 2,2,1,1,2,2 |
| Outside allowed strategies / neutral credit spread | 0 / 0 | 0 / 0 |
| MARA bearish (call credit spread) | 6/6 | 6/6 |
| Second idea | KVUE bullish 4, CCL bullish 2 | CCL bullish 4, none 2 |

Every thesis matched the numbers in the bundle (MARA +30% over 20 days at the top
of its range; KVUE at its 20-day low on 2.9x volume; CCL -20% near its low) and
followed the prompt's "sell premium after a big move" posture. Neither setting
invented strikes, sizes or disallowed strategies.

## Decision

`gemini-3.8-flash-low` in production: same rule-following and thesis quality,
about half the latency, and a steadier answer count. Switch with
`OA_AGY_MODEL=gemini-3.8-flash-medium` on Railway (no code change).

## Limits

One market snapshot, 12 calls. This measures reliability, speed and rule
following. It does NOT show which setting makes more money; that needs weeks of
live proposals and fills, and most proposals are still vetoed downstream by the
contract picker and the research_rules gate.
