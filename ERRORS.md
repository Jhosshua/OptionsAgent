# ERRORS.md — OptionsAgent

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
