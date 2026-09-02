# OptionsAgent

> **Where this runs (since 2026-09-01):** Railway, project `OptionsAgent`, not this Mac.
> Linux cron in the container is the scheduler; state lives on the volume at `data/`.
> Proposals come from the **DeepSeek API** (`DEEPSEEK_API_KEY`, since 2026-09-01 evening);
> the image no longer carries the Claude Code CLI. `harness/proposer.py` fails CLOSED on
> any API/key error and pages Discord, and every call is journaled as a `proposer_result` row.
> Dashboard: https://optionsagent-production.up.railway.app (public, no password).
> Alerts: Discord `#options-agent`. Redeploy: `railway up --service OptionsAgent`.
> The Mac's launchd plist and its three user-crontab lines are disabled.

A deterministic options-trading bot on Alpaca (paper first). LLM proposes a direction and strategy;
deterministic Python picks the actual contract, sizes it, and executes. See `CLAUDE.md` for the
full picture, `ARCHITECTURE.md` for the design rationale, `RESEARCH.md` for the research it's built
on.

> **OPERATING MODE — 2026-09-01:** A paper-trading robot on Railway. The DeepSeek
> API (`OA_LLM_PROVIDER=deepseek`, model `deepseek-v4-pro`) supplies proposals;
> no Anthropic key and no Claude CLI login are involved any more. Public.com is read-only options
> data, AlpacaRelay serves stock bars, Alpaca remains paper execution. **Railway
> variables are authoritative** — `entrypoint.sh` writes them into `.env` at boot,
> because cron does not inherit the container environment.
> (Until 2026-09-01 this ran locally, with the Mac `.env` and user crontab
> authoritative. Those crontab lines are now commented out.)

## Alpaca AI Trading Agents Hackathon (lablab.ai, Aug 28 – Sep 4, 2026)

This repo is the submission of team **Convexity**. Competition paper account:
**PA371G5THNUO** (created 2026-08-30, $100,000 start, options level 3; first
order 2026-08-31 10:18 ET; nothing else has ever traded on it).

**Pre-event disclosure (required by the hackathon FAQ).** OptionsAgent existed
before kick-off: the deterministic harness (contract picker, risk rails, exit
sweep, journal, dashboard) was built July 2026 and reactivated 2026-08-28. Work
done inside the hackathon window: the equity intraday scalper and its 6-month
study (08-28), the Railway deployment (09-01), the DeepSeek proposer (09-01),
the dashboard rework (09-01), and the two changes below (09-01 night). The
credit-spread seller had **zero fills** on the competition account before
09-02 because its gate only admitted three historical winner shapes.

**How the agent meets the requirements.**
- *Autonomous:* Linux cron in the container runs the daily proposal cycle,
  the 20-minute exit sweep and the per-minute scalper; no human in the loop.
- *Options:* the seller opens defined-risk vertical credit spreads (short
  strike 0.15–0.30 delta, 30–45 DTE, width ≤ $2), exits at 50% profit, 2x-credit
  stop, or 21 DTE.
- *AI logic:* DeepSeek (`deepseek-v4-pro`, JSON mode, temperature 0) proposes
  `{underlying, strategy_type, direction, conviction, thesis}` once a day over a
  13-name watchlist. It never picks a strike, size, or exit; it cannot place an
  order. Every call is journaled (`proposer_result` rows).
- *Risk gates (deterministic, in code):* 0.60 conviction floor, phase menu,
  6 max concurrent positions, per-position dollar cap (`OA_MAX_POSITION_USD`,
  **$3,000** for the competition ⇒ ≤ 15 contracts of a $2 spread), the contract
  picker's delta/DTE/width rules, skip-below-one-contract, paper-only by
  construction, fail-closed on any broker or model error.
- *Alpaca infrastructure:* Trading API through the **official Alpaca CLI**
  (`OA_BROKER_TRANSPORT=cli`, `harness/alpaca_cli.py`): account, positions,
  clock, order submit (single-leg and `mleg` spreads), order status and cancel
  all run as `alpaca …` subprocesses inside the container; every call is
  journaled to `data/cli_calls.jsonl`. Option chains come from a read-only
  Public.com sidecar, stock bars from a hosted Alpaca market-data relay.

**Two deliberate changes for the competition window (2026-09-01 night):**
1. `OA_CREDIT_SPREAD_GATE=research_rules`: the frozen in-sample winner table
   (CCL bullish / SOFI bullish / F bearish only) is bypassed; any watchlist name
   whose spread passes the picker's research rules may open. Every decision row
   records the gate mode it was judged under (`judged_against`).
2. `OA_MAX_POSITION_USD=3000`: sizing is a share of buying power (30%–100%),
   which on a $100k account would have meant ~178 contracts per idea. The cap
   makes the worst case ≈ $3,000 minus credit per position, ≈ $18k across all
   six slots. The two changes ship together on purpose.

## Status (2026-09-01)

**ACTIVE ON RAILWAY, PAPER ONLY, TWO ENGINES on a $100,000 Alpaca paper account.**
- Engine 1, credit-spread seller: the DeepSeek API proposes, deterministic rails
  dispose, once daily 10:15-10:27 ET (cron/entry.sh), exits every 20 min
  (cron/exits.sh). Gate: `OA_CREDIT_SPREAD_GATE` (winner profile by default;
  `research_rules` for the hackathon window, see the section above).
- Engine 2, EQUITY intraday scalper (run_scalp_equity.py, NEW tonight): two
  rules mined from 6 months of SPY/QQQ minute bars and frozen (morning fade at
  10:15; QQQ gap follow at 13:00). $20k notional, 0.7% intrabar stop, 120m time
  exit, 15:50 ET flatten, -$300 daily halt. Cron * 9-15 * * 1-5.
- The 0DTE OPTION scalper was retired tonight: a 16,384-combination study over
  125 sessions found no positive-expectancy configuration (RESEARCH_SCALP_6MO.md).
- Stock data runs through a read-only SIP-entitled key (OA_DATA_* in .env);
  option chains/quotes via the Public.com sidecar; execution paper-only.
- Dashboard: https://optionsagent-production.up.railway.app — read-only, reset to
  the 08-28 activation date. (Was a local LaunchAgent on 127.0.0.1:8765 until
  2026-09-01; it is now public to anyone with the link, with no password.) Operator explainer PDF: OptionsAgent-Explained.pdf.

## Docs map

| File | What it's for |
|---|---|
| `CLAUDE.md` | Read FIRST every session: constraints, locked stack, current status |
| `MEMORY.md` | Decision log: what was decided / why / what was rejected |
| `ERRORS.md` | Approaches that failed and what worked instead |
| `ARCHITECTURE.md` | The original design + rationale (superseded parts are banner-marked) |
| `RESEARCH.md` | The 3-pass deep research every threshold number traces back to |
| `OVERFIT_ANALYSIS.md` | Archived per-day/per-trade replay and the documented local research changes |
| `research_credit_spread_history.py` | Replays the archived multi-day credit-spread ledger and winner profile |
| `DEEPSEEK_CREDIT_SPREAD_PROMPT.md` | Read-only prompt for an independent DeepSeek/claude-ds review |
| `SETUP.md` | Railway runbook, scheduler, the DeepSeek proposer, logs, and paper-trading gates |

## Local dev

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in paper credentials, `DEEPSEEK_API_KEY`, and the
   read-only Public secret. (`OA_LLM_PROVIDER=claude_cli` uses the Mac's Claude CLI instead.)
4. `python3 -m pytest tests/` — all tests pass without broker or model calls.
4. The bot itself runs on Railway; the Mac crontab lines are commented out. Run
   `python3 run_cycle.py` locally only when intentionally performing a paper entry cycle
   (it would trade the same paper account).

## Config

`config/config.json` holds tunables (strategy phase allowlist, delta/DTE targets, conviction
thresholds, exit targets). The rails in `harness/risk_rails.py` (conviction floor, max positions,
DTE close, the credit-spread gate in both its modes, the research_rules liquidity floor) live in
code by design. Sizing is full-deploy per operator decision 2026-07-03: conviction-scaled fraction
of available buying power, no percentage caps — `OA_MAX_POSITION_USD` is the tighten-only absolute
ceiling, set to $3,000 on Railway since 2026-09-01 and mandatory while the gate is `research_rules`.

## Optional Public market-data sidecar

The default provider is Alpaca. Set `OA_OPTIONS_DATA_PROVIDER=public` to source option chains,
Greeks, bid/ask quotes, and exit marks from Public.com while Alpaca remains the paper execution
broker. This requires a personal Public API secret and account ID in environment variables; the
adapter is read-only and never submits Public orders. See `SETUP.md` for the credential flow and
`harness/public_marketdata.py` for the boundary.

## Dashboard

The supplied daylight dashboard is implemented under `dashboard/` and served by the
`harness.dashboard_server` process, which the Railway entrypoint supervises alongside cron.
It is read-only and defaults to paper trading disarmed. Its on-page brand is **Wingspan**
(W-wing mark, chosen 2026-09-01, working files in `dashboard/brand/`); the system itself is
still OptionsAgent everywhere else.

**Live at https://optionsagent-production.up.railway.app.** In the container it binds
`0.0.0.0` on Railway's `$PORT` (`OA_DASHBOARD_HOST=0.0.0.0`), so unlike the old
loopback-only setup it is reachable by anyone with the URL and has no password.
A dashboard crash never bounces cron mid-trade — it is deliberately not the healthcheck.

Enable `OA_TRADING_ENABLED` only after the deployment verification sequence in `SETUP.md`.
