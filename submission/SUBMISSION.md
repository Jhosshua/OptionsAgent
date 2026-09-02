# Hackathon submission pack (drafts, 2026-09-01 night)

Everything the lablab form asks for, in the order the form asks. Numbers marked
`[[…]]` get filled in Thursday after the close from the account snapshot.

## 1. Project title
Wingspan: an options agent that mostly says no

## 2. Short description (max 255 chars)
Autonomous options agent on Alpaca. DeepSeek proposes, code decides every strike, size and exit, and the official Alpaca CLI places every order. Defined risk credit spreads plus a no AI share scalper, a $3k cap per position, every refusal journaled.

## 3. Long description (≥ 100 words)
Wingspan (repo: OptionsAgent) is an autonomous options-trading agent built on
Alpaca's Trading API through the official Alpaca CLI, running on a $100,000
paper account created for this hackathon (account ID PA371G5THNUO).

The governing rule is simple: the AI proposes, the code disposes. Once a day
DeepSeek reads a 13-name watchlist with fresh market context and answers one
question per name: is there a trade, which strategy, which direction, how
convinced? It may not name a strike, a size or an exit. A deterministic
pipeline then picks the contracts (short strike at 0.15 to 0.30 delta, 30 to 45 days out, at most $2 wide), sizes the position (conviction-scaled, hard-capped
at $3,000 of defined risk), checks that the spread is liquid enough that the
exit rule will not stop it out on the same quotes it was opened on, and sends
one multi-leg limit order through `alpaca order submit`. A separate exit sweep
runs every 20 minutes with no AI in it: 50% profit target, a 2x credit stop
confirmed over two sweeps after 10:00 ET, forced close at 21 days to expiry.
A second engine has no AI at all: two rules on SPY and QQQ mined from six months
of minute bars, $20k a trade, two trades a day, a 0.7% stop, flat by 15:50 ET.
Both engines trade the same account through the same CLI path.

What makes it different is what it refuses. Every proposal that dies at a gate
is journaled with the gate that killed it and the thresholds it was judged
against, every CLI call is journaled with its exit code and latency, and the
public dashboard shows the refusals next to the fills. The design goal was an
agent a stranger could audit in ten minutes, not one that trades a lot.

## 4. Tags
Alpaca · Alpaca CLI · DeepSeek · Python · Railway · Options · Credit spreads · Autonomous agent

## 5. Cover image
16:9 PNG from the Wingspan brand (dashboard/brand/Main.dc.html). To render.

## 6. Video (MP4, ≤ 5 min), script
0:00 Who I am, what this is (20 s). "An options agent where the AI is the
     least trusted part."
0:20 The rule (30 s). Slide: AI proposes {name, strategy, direction,
     conviction, thesis}. Code picks strike, size, exit. CLI places the order.
0:50 Live dashboard (90 s). Overview: equity, today's P/L. AI trade ideas card:
     today's proposals and which gate killed each. Risk rails tab: gate mode,
     $3k cap, broker path = Alpaca CLI. Trade history.
2:20 The journals (60 s). Terminal: tail decisions.jsonl (a decision row with
     judged_against), tail cli_calls.jsonl (an order submit through the CLI),
     `alpaca order list` on the competition account.
3:20 What went wrong and what we changed (60 s). The gate that vetoed
     everything for a week; the replay that showed 8 of 22 spreads were losers
     at entry; the liquidity floor; the cap. Honest about a quiet day = zero
     trades.
4:20 Results + close (40 s). [[equity, fills, refusals]] and the one-line
     lesson: robustness is a feature judges can verify, P/L on two days is not.

## 7. Slide deck (PDF), outline, 8 slides
1. Title: Wingspan. One line. Account ID.
2. The problem: LLMs generate plausible trades and cannot refuse bad ones.
3. The rule: proposes vs disposes (diagram from README).
4. The pipeline: proposer → rails → contract picker → liquidity gate → CLI order → exit sweep.
5. Risk gates table: conviction floor, phase menu, $3k cap, 6 slots, delta/DTE/width, liquidity floor, 21-DTE close, paper-only, fail-closed.
6. Alpaca infrastructure: Trading API via official CLI (journaled), option chains, data relay, Railway cron, dashboard.
7. Evidence: journal excerpts, replay table (5/26 admitted, 0 past stop), test count, mutation checks.
8. Results and what's next: [[equity curve, fills, refusals]]; disclosure of pre-event work.

## 8. Links for the form
- GitHub: https://github.com/Jhosshua/OptionsAgent (public + MIT once approved)
- Demo platform: Railway
- Application URL: https://optionsagent-production.up.railway.app
- Alpaca paper account ID: PA371G5THNUO

## 9. One-page write-up (AI logic, risk gates, Alpaca infrastructure)

**AI logic.** One DeepSeek call per trading day (deepseek-v4-pro, JSON mode,
temperature 0) over a 13-name sub-$50 watchlist with recent bars and context.
Output is a list of proposals, each `{underlying, strategy_type, direction,
conviction, thesis}`, validated against a schema; anything malformed is
dropped, never repaired. The model cannot name a strike, a size, an exit, or
place an order. A failed or empty call is journaled as a `proposer_result` row
so a dead model cannot pass for a quiet market.

**Risk gates (deterministic, in code, env may only tighten).**
Conviction floor 0.60; phase menu (credit spreads only); one position per
underlying, watchlist names only, no re-entry on an open name; six concurrent
positions max; sizing = conviction-scaled share of buying power, hard-capped at
$3,000 of defined risk per position; contract picker: short strike 0.15 to 0.30
delta, 30 to 45 DTE, width ≤ $2; liquidity floor: credit ≥ $0.10 and unwind-now
cost < 1.5× credit (so the exit rule cannot stop the trade out on its own entry
quotes); fills are confirmed and the unfilled remainder cancelled before
anything is booked. Exits, no AI: 50% profit, 2× credit stop confirmed over two
20-minute sweeps after 10:00 ET, forced close at 21 DTE. Paper-only by
construction; every broker or model error fails closed and pages Discord.

**Alpaca infrastructure.** Orders, positions, account and clock go through the
official Alpaca CLI (`alpaca … -q`, JSON out), pinned to v0.0.14 in the Docker
image and journaled per call. Spreads are one `order submit --order-class mleg`
limit order at the net credit. Option chains come from a read-only market-data
sidecar; stock bars from a hosted Alpaca data relay. Runs on Railway as Linux
cron (entry 10:15 ET, exits every 20 min, scalper every minute) with state on a
volume; the dashboard is a read-only observer of the same journals.

**Disclosure.** The harness predates the hackathon (July 2026). Built inside
the window: the equity scalper and its study, the Railway deployment, the
DeepSeek proposer, the dashboard rework, the CLI transport, and the gate/cap
changes. The competition account was created 2026-08-30 and nothing else has
traded on it.

## 10. Social posts (optional, up to 5; tag @lablabai @AlpacaHQ)
1. Day 1: "Entering the Alpaca AI Trading Agents Hackathon with an options
   agent whose AI can't place an order. Code picks every strike, size and exit."
2. The bug: "Replayed yesterday's option chains: 8 of 22 spreads my gate would
   have opened were already past their own stop on the entry quotes. Fixed
   before the first trade. Build in public means showing the misses."
3. The CLI: "Every order now goes through Alpaca's official CLI, journaled with
   exit code and latency. One binary, one subprocess, no silent fallback."
4. The dashboard: screenshot of the Risk rails tab.
5. Results: [[Thursday]].
