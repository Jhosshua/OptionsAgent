# Alpaca AI Trading Agents Hackathon: research + submission plan

Researched 2026-09-01 22:15 ET from the lablab event page, the lablab Guide /
Submission Guidelines / Rule Book, the Discord `#updates`, `#official-updates`
and `#participants-chat` channels, the official Alpaca FAQ Google Doc
(docs.google.com/document/d/13XWsMvW3mFm26xGlBLvdzzJ_eZQ33T4ZrP-vd9eat50),
the Alpaca MCP server, CLI and Skills repos, and both paper accounts via the
Alpaca API.

## The rules that actually bind (verified, quoted where it matters)

| Rule | Source | Status for us |
|---|---|---|
| Deadline: **Sep 4, 11:00 AM EDT** (lablab form closes) | event page | ~61 h from now |
| P&L window: Mon Aug 31 09:30 ET to Fri Sep 4 09:30 ET. Judges read **total equity as of EOD Thu Sep 3**; Sep 3 expiries' exercise/assignment count | Alpaca FAQ | 2 trading days left (Wed, Thu) |
| **Fresh** $100k paper account, no pre-existing positions, agent starts trading Mon Aug 31 09:30 ET. "Projects run on an existing or reused account will not be eligible" | event page + FAQ | OptionsAgent PA371G5THNUO created Aug 30 22:26 UTC, $100k, first fill Aug 31 10:18 ET: **qualifies**. Wheel PA3NADVG8LL3 created Aug 28 02:50 UTC, $100k, first fill Sep 1: qualifies |
| Must use Alpaca Trading API **and** MCP server **or** CLI. "If you want to use an SDK to implement your bot explain clearly your reasons and prioritize the official SDKs" | event page + FAQ | **NEITHER repo uses MCP or CLI.** Both use alpaca-py only. HARD GAP |
| "All strategies must incorporate options trading" | event page | OptionsAgent: **0 option fills** on the comp account (6 equity scalps, seller vetoed every day). Wheel: 2 short puts filled Sep 1 (WFC, XLE) |
| Autonomous agent | event page | both are cron/loop bots, OK |
| One-page write-up: AI logic, risk gates, Alpaca infra | event page | not written |
| Pre-event work allowed but **must be disclosed** in README/submission | FAQ | must add a disclosure section |
| Repo: lablab says public; Alpaca FAQ says "may remain private during the hackathon". Private lowers lablab score; prize terms say "MIT-compliant" | lablab + FAQ + prize terms | both repos private, **no LICENSE file** |
| Hosting/UI not required; hosted link only if you submit a demo app | FAQ | both dashboards already on Railway (bonus) |
| Judging: total equity + "creativity, autonomy, robustness of the agent trading workflow"; "not P&L alone"; no Sharpe, no scoreboard | FAQ | |
| Submission fields: title, short desc (255 chars), long desc (100+ words), tags, cover image 16:9 PNG/JPG, **video MP4 max 5 min**, **slide PDF**, GitHub URL, demo platform + app URL, **Alpaca paper account ID**, up to 5 social post links | event page + Submission Guidelines | none prepared |
| Social prize (2 teams x $500 + Algo Trader Plus): posts on X / LinkedIn tagging @lablabai + @AlpacaHQ | event page | optional |
| Featherless: $25 credits, coupon `ALPACA26`; only matters for the 1st-place bonus | Discord | optional, skip unless cheap |
| Prizes paid to an individual; W-9 + ID + bank needed; 1099 above $600 | prize terms | later |

## Team situation (this changes who can submit)

- lablab team **Convexity**: Sachal Khalid (sachal_990), Faruque Amin (futureisnow), Jhoshua (CreationOfAi).
- The team page shows Jhoshua only a "Leave team" button and no "Call for help" control, and the Submit Project link bounces back to the team page. The FAQ says the leader uses "Calling for help". So **Jhoshua is not the team leader**; the leader (probably Sachal, listed first) is the only one who can submit, and there is one submission per team.
- The team idea text describes an MCP-based three-layer agent with a "fresh repo on the 28th". That may be a different codebase than OptionsAgent. Must be reconciled with the teammates before any code work.
- Options: (a) teammates submit OptionsAgent, (b) merge, (c) Jhoshua leaves and creates a solo team (allowed, teams are 1 to 6). Leaving means the team's Discord channel and chat history stay with them.

## The two candidate bots, honestly

| | OptionsAgent (Wingspan) | AlpacaHackAThon wheel bot |
|---|---|---|
| Comp account | PA371G5THNUO, equity $100,034.43 (+$34) | PA3NADVG8LL3, equity $99,959.96 (-$40) |
| Options fills in window | **0** | 2 short puts (WFC Oct 16 82.5P, XLE Oct 2 61.5P) |
| Why | seller's overfit-profile gate vetoes all 14 proposals; equity scalper is the only engine trading | IVR gate binds; AI catalyst pillar vetoes on news |
| MCP / CLI | none | none |
| LICENSE | none | none |
| Repo | private, 40 commits since Aug 27 | private, 50 commits, built Aug 30 |
| Dashboard | Railway, public | Railway, public |
| Write-up material | OptionsAgent-Explained.pdf, RESEARCH.md | BUILD_LOG.md, plain-English PDF, 7 spec docs |

Fit for the rules as written: the wheel bot is an options bot on a fresh account
with option fills. OptionsAgent is the operator's pick but has not placed one
option order on the comp account; submitting it as-is fails "incorporate
options trading" on the evidence judges will look at (the account's orders).

## TODO list for submittal (ordered; blockers first)

### 0. Decisions tonight (Tue Sep 1)
- [ ] **D1** Which bot: OptionsAgent, wheel bot, or OptionsAgent with the wheel's option engine bolted in. Operator's call.
- [ ] **D2** Team: message Sachal + Faruque (lablab team chat or Discord) tonight. Ask: who is leader, what have they built, will they submit this bot. If no answer by Wed noon ET, leave and create a solo team so the submit button is ours.
- [ ] **D3** Public repo + MIT license, or keep private (allowed by Alpaca, penalized by lablab). Recommend public + MIT, secrets already gitignored (verify `.env` history first).

### 1. Code (DONE 2026-09-01 night, live for the Wed 10:15 ET cycle)
- [x] **C1 CLI in the order path.** `harness/alpaca_cli.py` + `OA_BROKER_TRANSPORT=cli`; Dockerfile installs Alpaca CLI v0.0.14 (sha256 pinned). Account/positions/clock/order submit (incl. `mleg`)/get/cancel all go through `alpaca …`, journaled to `data/cli_calls.jsonl`, fail-closed. Verified against the real account (read-only) and with `--dry-run` for the spread body.
- [x] **C2 Gate opened + cap set together.** `OA_CREDIT_SPREAD_GATE=research_rules` bypasses the CCL/SOFI/F winner table; `OA_MAX_POSITION_USD=3000` caps each position (≤ 15 contracts of a $2 spread). Whether a spread FILLS still depends on the picker finding a 0.15–0.30-delta, 30–45-DTE, ≤ $2-wide pair: watch Wed 10:15.
- [x] **C3** README hackathon section: disclosure, account ID, requirements mapping, the two deliberate changes.
- [x] **C5** 276 tests green, 7 mutation checks caught; deployed to Railway 2026-09-01 23:00 ET (416c1fea) and verified in-container (CLI binary, env, adapter smoke, dry-run mleg, cron). Adversarial review findings (immediate-stop spreads, no dedupe, scalper bypassing the CLI, fills booked unconfirmed) fixed BEFORE deploy; see MEMORY.md.
- [ ] **C4** LICENSE (MIT) + public repo: still the operator's call (D3).
- [ ] **C4** Add LICENSE (MIT) if going public. Scrub: `git log -p --all -S 'PK' | head`, `.env*` never committed, dashboard has no secrets.
- [ ] **C5** Tests green after C1/C2 (233 currently). Deploy to Railway, verify the first cron cycle Wed 10:15 ET through the new path in the journal.

### 2. Trading window (Wed Sep 2, Thu Sep 3)
- [ ] **T1** Watch every cycle on the comp account; confirm option fills appear in `/v2/orders` on PA371G5THNUO.
- [ ] **T2** Thu Sep 3: no positions expiring Sep 3 unless intended (assignment counts in the EOD equity). Decide whether to flatten before Thu close or hold.
- [ ] **T3** Snapshot the account (equity, orders, positions) Thu after close for the write-up.

### 3. Submission assets (Thu Sep 3)
- [ ] **S1** One-page write-up: AI logic (DeepSeek proposer, JSON schema, fail-closed), risk gates (rails, sizing, halts), Alpaca infra (Trading API + CLI/MCP, paper account, relay). Reuse OptionsAgent-Explained.pdf content.
- [ ] **S2** Slide PDF (5 to 8 slides): problem, strategy, architecture, risk gates, live results, what it refused and why, next steps.
- [ ] **S3** Video MP4, max 5 min: intro, walk the slides, show the dashboard and a journaled cycle, show the account orders page.
- [ ] **S4** Cover image 16:9 PNG (Wingspan brand exists in `dashboard/brand/`).
- [ ] **S5** Short description (255 chars) + long description (100+ words) + tags (Alpaca, DeepSeek, Railway, Python).
- [ ] **S6** Demo platform + URL: Railway dashboard optionsagent-production.up.railway.app.
- [ ] **S7** Optional: up to 5 posts on X/LinkedIn tagging @lablabai and @AlpacaHQ (build-in-public prize).

### 4. Submit (Thu night, hard stop Fri Sep 4 11:00 AM EDT)
- [ ] **F1** Team leader fills the lablab form with all fields plus account ID `PA371G5THNUO` (or the wheel's `PA3NADVG8LL3`).
- [ ] **F2** Verify the submission appears on the event page "Submissions" list.
- [ ] **F3** Keep the bot running through Fri 09:30 ET (the FAQ takes a snapshot then too).

## Links
- Event: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
- Team: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/convexity
- Submit: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/convexity/submission (leader only)
- Discord: server 877056448956346408, channels `#official-updates` 1542534892842385600, `#participants-chat` 1537121600523214878
- Alpaca FAQ doc: https://docs.google.com/document/d/13XWsMvW3mFm26xGlBLvdzzJ_eZQ33T4ZrP-vd9eat50
- MCP: https://github.com/alpacahq/alpaca-mcp-server (`uvx alpaca-mcp-server`; tools get_option_contracts, get_option_chain, place_option_order, get_option_snapshot)
- CLI: https://github.com/alpacahq/cli, docs https://docs.alpaca.markets/us/docs/alpacas-cli (`alpaca option contracts`, `alpaca data option chain`, `alpaca order ...`, `--jq`, `--csv`)
- Skills: https://github.com/alpacahq/alpaca-skills (`npx skills add alpacahq/alpaca-skills`)
