# ERRORS.md — OptionsAgent

## Proposer STILL returned 0 proposals after the 07-06 fixes: `anthropic` was never in requirements.txt

**What did not work:** the 2026-07-06 fixes were verified with `railway run`, which executes on
the MAC with Railway env vars — the Mac has the `anthropic` package installed globally, so the
proposer worked in that test. The container never had it: `requirements.txt` listed alpaca-py,
requests, python-dotenv, yfinance, pytest — no `anthropic`. Inside the container the proposer hit
its `except ImportError` path and degraded to no-trade on every cycle, logging
`anthropic package not installed — proposer degrading to no trade` (visible in `railway logs`,
2026-07-07 10:15 ET cycle).

**What worked instead:** added `anthropic==0.104.1` to `requirements.txt` (same pin as the sibling
bots), pushed, redeploy rebuilt the image. Verified INSIDE the container via `railway ssh`: import
OK, live proposer smoke call returned 200. Then ran a manual `python3 run_cycle.py` in the
container: 3 proposals, rails filtered 2 (no matching contract / no shares for covered call),
1 executed — first-ever trade, 8x MARA 2026-08-07 $13 puts @ $2.18.

**Note for next time:** `railway run` proves nothing about the container — it runs on the Mac.
Container-truth checks go through `railway ssh`. After ANY dependency-related fix, verify with
`railway ssh "python3 -c 'import <pkg>'"`. Fleet-wide: every runtime import in a bot must appear
in its requirements.txt; the Mac's global site-packages hides these misses locally.

## Proposer silently returned 0 proposals: `temperature=0` 400s on claude-fable-5

**What did not work:** `proposer.py` called `client.messages.create(..., temperature=0, ...)`. On
`claude-fable-5` (the default model) that returns HTTP 400 `temperature is deprecated for this
model` — Fable 5 removed `temperature`/`top_p`/`top_k` entirely. Worse, the call was wrapped in
`except Exception: return stub_proposals()`, so every failed call logged identically to a genuine
"model proposed nothing." The bot looked healthy and simply never traded.

**What worked instead:** delete the `temperature` param (the rails enforce determinism, not
sampling params — see the proposer docstring). Also added `log.exception`/`log.warning` in the
fallback paths so a broken LLM call is now distinguishable from a real no-trade in Railway logs.

**Note for next time:** Fable 5 / Opus 4.8 / 4.7 / Sonnet 5 all reject `temperature`, `top_p`,
`top_k` (400) and `thinking:{type:"enabled",budget_tokens}`; Fable 5 also 400s on an explicit
`thinking:{type:"disabled"}` — omit `thinking` entirely. When pointing ANY fleet bot at a Fable/
Opus-4.7+ model, grep its LLM call site for these params first. And never let an LLM call's
`except` swallow the error without logging — a silent fail-closed hides config bugs for days.

## Proposer got empty context, so it (correctly) proposed nothing every cycle

**What did not work:** `run_cycle.py` built the LLM bundle with `"context": {}` per ticker — no
prices, no news, nothing. The proposer's own prompt says "it is normal to propose nothing," so with
zero data a conservative model proposed nothing on every cycle. There was no context-builder module
at all; the empty dict had shipped since day one and would never have traded.

**What worked instead:** `harness/market_context.py` derives per-ticker context (price, %-moves,
20-day range position, relative volume) from Alpaca daily bars (`PaperClient.stock_daily_bars`,
IEX feed, fail-open per ticker). Wired into `run_cycle.py` with a `context built for N/13` log line.

**Note for next time:** an LLM "propose nothing" result is only trustworthy if the model was
actually given something to reason on. When a proposer/analyst agent is quiet, check what context
it's being fed BEFORE assuming the model is just being conservative.

## Railway: first deploy ran railpack, not the Dockerfile

**What did not work:** creating the Railway service from the GitHub repo BEFORE the
Dockerfile/railway.json were pushed. Railway immediately built the repo as-is with railpack
(auto-detection), found no start command, and the deployment failed.

**What worked instead:** push the Dockerfile + railway.json first (or right after), and the next
auto-deploy picks up the DOCKERFILE builder from railway.json.

**Note for next time:** when standing up a new bot, commit the Railway files BEFORE
`railway add --repo ...`, or expect one throwaway failed deployment. Harmless but confusing in the
dashboard.

## railway ssh: multi-line python -c does not survive argument passing

**What did not work:** `railway ssh --service X -- python3 -c "<multi-line script>"` — the
newlines get mangled into separate shell words inside the container ("from: command not found").

**What worked instead:** single-line python with semicolons, wrapped in an EXTRA layer of quotes:
`railway ssh --service X -- python3 -c "'import x; print(x.y)'"` (outer double quotes for the
local shell, inner single quotes so the remote shell passes one argument to python).

## Discord channel + webhook CAN be created without operator action

Not an error — the opposite: the fleet bot token (`~/.hermes/.env` DISCORD_BOT_TOKEN, bot
"StockBot") has Manage Channels + Manage Webhooks in the StockBot guild, so a new bot's channel
and webhook can be created via the Discord REST API directly (POST /guilds/{id}/channels, then
POST /channels/{id}/webhooks). No dashboard clicking needed. Used for #options-agent 2026-07-03.

## Deep-research workflow: synthesis step returns a placeholder stub instead of real content

**What did not work:** trusting the `deep-research` workflow's top-level `result.findings` /
`result.summary` directly. On 2 of 3 research passes for this project, the final synthesis agent
call returned a literal `{"summary": "test", "findings": [{"claim": "test claim", ...}]}` stub —
a genuine bug in that run, not a sign the research found nothing.

**What worked instead:** read the run's `journal.jsonl` directly, find the individual claim-verify
agent calls (3 votes per claim), and hand-tally survive/kill per claim from the raw `refuted`
booleans. Cross-check against the top-level `result.refuted` array where present — it sometimes
reflects genuine per-claim votes even when `result.findings` doesn't.

**Note for next time:** if a `deep-research` (or similar workflow) result's summary/findings look
templated, generic, or suspiciously short given the `agent_count`/`tool_uses` stats, don't report it
to the user at face value — inspect the journal before drawing any conclusion about what the
research did or didn't find.
