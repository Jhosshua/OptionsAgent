# ERRORS.md — OptionsAgent

## 2026-08-28 — Proposer moved to local Claude Code CLI

The local runtime no longer checks `ANTHROPIC_API_KEY` or imports the Anthropic Python SDK.
`harness/proposer.py` invokes the authenticated `claude` executable with structured JSON output,
no tools, no session persistence, and `--safe-mode`. The CLI connection and the OptionsAgent
proposer boundary were tested successfully. The unavailable-CLI path remains fail-closed with zero
proposals. When a local proposal call fails, check `claude --version`, `OA_CLAUDE_CLI`, and the
local Claude Code login instead of looking for an API key.

Railway references later in this file are historical and do not describe the active runtime.

## DeepSeek/claude-ds review attempt (2026-08-27)

The local `claude-ds` shell wrapper and headless `/Users/mo/ManualTrading2/bin/ds` shim were
found. Both accepted the request but remained silent until stopped; a direct request to the
DeepSeek Anthropic-compatible endpoint reset the connection. No model output was used as a
recommendation. The read-only prompt is preserved in `DEEPSEEK_CREDIT_SPREAD_PROMPT.md`.

## Credit-spread winner profile is deliberately overfit

The current seller gate matches only three historical winner shapes and replayed +$130 across
three records. It was requested despite the tiny sample. This is not a full backtest and may
reject all future candidates or select a coincidental pattern; do not relax it until a
prospective sample is collected.

## Public.com is an optional read-only data sidecar

Public API credentials must stay in environment variables. The adapter never submits Public
orders, and `OA_OPTIONS_DATA_PROVIDER` defaults to `alpaca`; a missing or malformed Public
credential must fail the data call closed rather than silently switching providers. Public's
Individual API is personal-use only, so its market data must not be redistributed through a
public dashboard or relay without permission.

## Dashboard and cron safety gates

The dashboard is intentionally separate from order execution. It binds to loopback by default,
its broker snapshot is refreshed off-request, and its process must not be
used as a trading healthcheck. Cron reads `OA_TRADING_ENABLED` and `ALPACA_PAPER` from `.env`; both
must be exactly `true` before entry, exit, or scalp scripts can act. The entrypoint removes stale
allowlisted variables from `.env` when they are absent and writes the file mode `0600`.

## Historical replay limitation: realized-fill filtering is not a full backtest

The 2026-08-27 study uses the archived scalp registry and decision log. It can
measure how old realized P/L slices by entry time, RVOL, direction, and
underlying, but it cannot reconstruct historical option bid/ask paths or fills
for trades that were skipped. Treat the 11:30 ET cutoff as a prospective
hypothesis supported by a small sample, not proof of a durable edge. Require a
fresh sample before further tuning.

## `railway ssh "... | base64"` silently truncates a large stream (11 MB came back as 353 KB)

**What did not work:** backing up the Railway volume in one shot —
`railway ssh "tar czf - data | base64 -w0" > out.b64`. It exited 0 and produced a plausible-looking
471 KB base64 file. It was garbage: the stream started mid-file (no `H4sI` gzip header), and the
real archive was 11 MB, not 353 KB. Nothing errored. A backup that exits 0 and is silently
truncated is worse than one that fails loudly — this would have been discovered only when the data
was needed, long after the source was deleted.

**What worked instead:** stage the archive INSIDE the container, split it, fetch chunk by chunk,
and checksum everything.
1. `railway ssh "tar czf /tmp/oabk/vol.tgz data && md5sum vol.tgz && base64 -w0 vol.tgz > vol.b64
   && split -b 500000 -d -a 3 vol.b64 part"` (note: `-a 2` blew up at 147 chunks —
   "output file suffixes exhausted"; needs 3 suffix digits).
2. Fetch each `partNNN` with its own `railway ssh cat`. One of 30 chunks came back at 182 bytes
   instead of 500000 — same silent truncation, caught only because the sizes were printed.
   Refetching it fixed it.
3. `md5sum part*` in the container vs `md5 -q` locally, compared per chunk, then reassemble and
   verify the final tarball md5 against the one taken at step 1. Only then treat the source as
   deletable.

**Note for next time:** never trust a single-shot `railway ssh` pipe for anything bigger than a few
hundred KB, and never delete a remote source until a checksum taken ON THE SOURCE matches the local
copy. Also: macOS `base64` has no `-d file` form — it's `base64 -d -i in -o out` (GNU-style
`base64 -d file` errors with "invalid argument"), and macOS has no `timeout`.


## run_cycle crashed on an ADJUSTED contract: chain snapshot includes untradable roots (CCL1)

**What did not work:** `alpaca_glue.option_chain()` trusted every symbol in Alpaca's market-data
chain snapshot. The 2026-07-08 10:15 ET cycle picked `CCL1260821P00022500` for a CCL credit
spread — root `CCL1`, an ADJUSTED contract created by a Carnival corporate action (deliverable is
no longer 100 plain shares). Alpaca's market data returns these, but the trading API rejects any
order on them: `{"code":42210000,"message":"contract ... is not active"}`. The submit raised,
run_cycle crashed, and the remaining 2 proposals of the day were never processed. Worse than
random: the selector actively PREFERS adjusted contracts because their quotes look mispriced
against their nominal strike (fat premium relative to nominal strike wins the score).

**What worked instead:** filter at the adapter — `_adapt_chain()` drops every row whose parsed OCC
root differs from the requested underlying. Standard contracts only, by construction. Regression
tests feed a fake chain containing a `CCL1` row and assert it's excluded.

**Note for next time:** market-data endpoints and trading endpoints disagree about what exists.
Anything selected from a data feed must be validated as tradable before submit, or filtered to a
class that is tradable by construction. Fleet-wide: any sibling bot that ever consumes an option
chain needs the same root-match filter (grep for `get_option_chain`).

## Exit sweep saw ZERO option positions: enum leaked through the adapter as "AssetClass.US_OPTION"

**What did not work:** `str(enum_member)` on alpaca-py's `AssetClass` gives `"AssetClass.US_OPTION"`,
not `"us_option"`. `list_positions()` used `str()` while every consumer compared lowercase plain
values, so membership checks silently failed (no crash, no log — reconcile just saw an empty set
and declared the MARA structure vanished 11 minutes after its first fill). The 62-test suite never
caught it because fixtures hand-write `"asset_class": "us_option"` — the tests validated the
consumers, never the adapter's output shape.

**What worked instead:** `_status_str(p.asset_class)` (the existing normalizer built for order
statuses, which unwraps `.value` first). Regression test added that feeds a real `str`-Enum through
the helper.

**Note for next time:** every enum-ish field crossing the alpaca_glue boundary must go through
`_status_str`. When a broker adapter returns dicts consumed by string comparison, test the ADAPTER's
output values against the consumers' expected literals, not just consumers against hand-written
fixtures. Fleet-wide: grep sibling bots for `str(p.asset_class)` / raw enum serialization when
touching their Alpaca glue.


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

## 2026-08-31 — Proposer CLI failure was undiagnosable because stdout was discarded

**What did not work:** Reading the entry log to find why the Claude Code CLI
proposer exited 1. The error said `status 1: (no stderr captured)` on both
08-28 and 08-31. Reproducing the exact call by hand (real 13-underlying bundle,
same flags) returned rc=0 and valid proposals, as did runs under a cron-like
minimal env (`env -i`), with stdin from /dev/null, and with stdin closed. None
of those reproduced it, so the environment is NOT the cause.

**What worked instead:** Noticing that `--output-format json` makes the CLI
report its own failures on **stdout** (`{"is_error":true,...}`), while
`_propose_with_claude_cli` only put stderr in the RuntimeError and threw stdout
away. The failure text was there the whole time and was being deleted.

**Note for next time:** When a subprocess wrapper reports "(no stderr
captured)", check which stream that tool actually writes errors to before
hunting the environment. Also: the entry cycle runs ONCE per day, so any single
transient proposer failure silently costs the entire trading day. `propose()`
now retries `OA_CLAUDE_ATTEMPTS` (default 3) times with linear backoff before
degrading to no-trade. Root cause of the exit-1 itself is still UNKNOWN; the
next occurrence will log the CLI's own stdout error.

## 2026-08-31 — Equity scalper could open positions but never close them

**What did not work:** `_flatten_position` read `pos["symbol"]`, but the state
blocks in `state["symbols"]` are keyed BY symbol and never carry a "symbol"
field — neither the `_open_position` writer nor the orphan-adoption writer sets
it. Every exit raised `KeyError: 'symbol'`, so the 0.7% stop, the 120-minute
time exit AND the mandatory 15:50 EOD flatten all failed identically. Caught
live: today's 10:15 SPY entry hit its 12:15 time exit and retried the same crash
every minute, leaving a real position unmanaged.

**What worked instead:** pass the symbol explicitly
(`_flatten_position(client, symbol, blk, ...)`). The one call site already has
it as the loop variable.

**Note for next time:** 177 tests passed with this bug live because every exit
test covered only the pure `evaluate_equity_exit` decision, never the code that
ACTS on the decision. A "should_close" test proves nothing about whether the
close can execute. Regression tests now build the state block exactly as the two
writers produce it and drive `_flatten_position` end to end; reintroducing the
bug fails 4 of them. Note the failure mode: the runner catches per-symbol
exceptions and logs "step failed (continuing)", so the tick line kept printing a
healthy-looking `halted=False` while no exit could ever run.
