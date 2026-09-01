# SETUP.md — OptionsAgent deployment runbook

> **CURRENT SETUP — 2026-09-01:** OptionsAgent runs on **Railway**, in project
> `OptionsAgent` (`cc393b70-4ef5-48d5-8299-253b914cc219`), service `OptionsAgent`,
> region sfo. Linux cron in the container is the scheduler; the volume at
> `/Users/mo/OptionsAgent/data` holds all state. Proposals come from the **DeepSeek
> API** (`OA_LLM_PROVIDER=deepseek`, `DEEPSEEK_API_KEY`, `OA_DEEPSEEK_MODEL=deepseek-v4-pro`)
> since 2026-09-01 evening. The image no longer carries the Claude Code CLI (its login
> expired twice and each time the daily cycle failed closed).
> Public.com is read-only options data, AlpacaRelay serves stock bars, Alpaca is
> the paper execution broker. **Railway variables are authoritative**, and
> `entrypoint.sh` writes them into `.env` at boot because cron does not inherit
> the container environment. Alerts go to Discord `#options-agent`.
> Dashboard: https://optionsagent-production.up.railway.app
> Redeploy with `railway up --service OptionsAgent`. The Mac's launchd plist and
> user-crontab lines are disabled; do not restart this bot locally.

## Runtime

- Container working directory: `/Users/mo/OptionsAgent` (the image mirrors the Mac path)
- Proposal model: DeepSeek API (`harness/proposer.py`), one JSON-mode call per trading day,
  ~40-80 s, 3 attempts on transient errors, no retry on key errors, Discord page on failure
- Market data: Public.com read-only sidecar (`OA_OPTIONS_DATA_PROVIDER=public`)
- Paper account and order execution: Alpaca (`ALPACA_PAPER=true`)
- Entry scheduler: container cron (`cron/crontab.railway`) invokes `cron/entry.sh` every five
  minutes; the script self-gates to 10:15–10:27 ET weekdays, paper mode, and Alpaca's market clock.
- Exit scheduler: container cron invokes `cron/exits.sh` every 20 minutes from 09:00–16:00 ET.
- Logs: `data/logs/` on the volume (`railway logs` for the container stream)

The proposer's outcome is journaled as a `proposer_result` row in `data/decisions.jsonl`
(provider, model, ok, proposals, attempts, latency_s, error) and shown on the dashboard's
"AI proposer" card. Any API/key/parse failure returns no proposal and submits no order.
`OA_LLM_PROVIDER=claude_cli` selects the Mac-only Claude Code CLI path (resolved from
`OA_CLAUDE_CLI`, PATH, or `~/.npm-global/bin/claude`); the container cannot use it.

### Restart / verification (Railway)

```bash
cd /Users/mo/OptionsAgent
python3 -m pytest -q                       # locally, before deploying
railway up --service OptionsAgent          # build + deploy
railway logs --service OptionsAgent         # boot, secrets injected, alert transport
railway ssh --service OptionsAgent 'claude --version'
railway ssh --service OptionsAgent 'grep -E "^[0-9*]" /etc/cron.d/optionsagent'
```

`claude --version` matters more than it looks: `harness/proposer.py` FAILS CLOSED without the
CLI, so a container missing it comes up green and never trades. The Dockerfile asserts it at
build time for the same reason. Never run `run_cycle.py` merely as a connectivity test because it can
submit paper orders when proposals, gates, and market conditions all pass.

> **SUPERSEDED (2026-09-01).** The paragraph below describes the FIRST Railway
> deployment (project `e312c619`), which was deleted on 2026-08-02. A new Railway
> project was created on 2026-09-01 — see the banner at the top of this file. The
> section is kept because the volume layout, cron design and env-var mechanics it
> describes are still exactly how the current deployment works.

Everything operational: where it runs, the env vars, how to redeploy, watch, and stop it. The current code also contains an intentionally overfit,
hard-coded credit-spread winner profile documented in `OVERFIT_ANALYSIS.md`.

## Where it runs

- **Railway** project `OptionsAgent` (`cc393b70-4ef5-48d5-8299-253b914cc219`), single service
  `OptionsAgent`, region sfo. Deployed with `railway up --service OptionsAgent` from this
  directory — deliberately NOT wired to GitHub auto-deploy, because Railway ignores
  `[skip ci]` and a docs-only push would restart a live bot mid-session.
- **Volume** `optionsagent-volume` mounted at `/Users/mo/OptionsAgent/data` — holds
  `decisions.jsonl`, `structures.jsonl`, logs, and the cron once-per-day lock markers. Survives
  redeploys; the rest of the container filesystem does not.
- Container runs Linux cron in the foreground (see `Dockerfile`, `entrypoint.sh`,
  `cron/crontab.railway`). System TZ is America/New_York.

## Schedule

| Job | When | Guards |
|---|---|---|
| `cron/entry.sh` → `run_cycle.py` | 10:15-10:27 ET weekdays, once/day | ET window + atomic volume lock + broker market clock (fail-closed) |
| `cron/exits.sh` → `run_exits.py` | every 20 min, 9-16h ET weekdays | broker market clock (fail-closed); idempotent, no lock needed |

## Environment variables (local `.env`)

| Var | What | Notes |
|---|---|---|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Paper account keys | Dedicated paper account (never share another bot's — exposure math tangles) |
| `ALPACA_PAPER` | `true` | Belt-and-suspenders; `make_client()` refuses non-paper anyway |
| `DEEPSEEK_API_KEY` | (secret) | AI proposer key. Missing = fail-closed no-trade every day, paged |
| `OA_LLM_PROVIDER` | `deepseek` | `deepseek` (Railway) or `claude_cli` (Mac only) |
| `OA_DEEPSEEK_MODEL` | `deepseek-v4-pro` | Overrides `config.json` `llm.model` |
| `OA_LLM_TIMEOUT_SECONDS` | `180` | Per-attempt call timeout |
| `OA_LLM_ATTEMPTS` | `3` | Attempts on transient errors (key errors are not retried) |
| `OA_CLAUDE_CLI` / `OA_CLAUDE_MODEL` | — | Only read when `OA_LLM_PROVIDER=claude_cli` |
| `DISCORD_WEBHOOK_URL` | `#options-agent` webhook | Channel 1522587333822513253, StockBot guild |
| `OA_MAX_POSITION_USD` | (unset) | OPTIONAL tighten-only emergency brake: absolute $ ceiling per position |
| `OA_MAX_TOKENS` | (unset, default 4096) | Proposer output ceiling |
| `OA_TRADING_ENABLED` | `false` in template; `true` locally | Explicit cron trading gate; paper-only local run |
| `OA_DASHBOARD_HOST` | `127.0.0.1` | Dashboard bind address. **Railway sets `0.0.0.0`** so the router can reach it; `127.0.0.1` is loopback-only and correct for a local run |

## Optional Public market-data sidecar

The default `OA_OPTIONS_DATA_PROVIDER=alpaca` uses Alpaca market data. To avoid relying on
Alpaca's paid market-data tier for the options chain, create a personal Public API secret in
Public settings and set:

- `OA_OPTIONS_DATA_PROVIDER=public`
- `PUBLIC_API_SECRET=<your Public personal API secret>`
- `PUBLIC_ACCOUNT_ID=<your Public brokerage account ID>` (optional; the adapter can discover the first brokerage account)

The adapter exchanges the secret for a short-lived Public access token, reads option expirations,
chains, and per-contract quotes/Greeks, then returns the same `OptionQuote` shape used by the
deterministic selector. It has no Public order methods; all paper orders, account state, and
positions remain Alpaca. Public's official flow is documented at its
[API quickstart](https://public.com/api/docs/quickstart), [option-chain guide](https://public.com/api/docs/templates/place-options-order),
and [quote endpoint](https://public.com/api/docs/resources/market-data/get-quotes).

Start with `PUBLIC_OPTIONS_DTE_MIN=30` and `PUBLIC_OPTIONS_DTE_MAX=45` for the current seller.
The first live check should be read-only: verify authentication, retrieve one chain, and compare
timestamps/bid/ask/delta against Alpaca before enabling the provider in a paper cycle. Never put
either broker's secrets in config JSON, source control, Discord, or a dashboard.

## Always-on dashboard (Railway)

The dashboard runs in the Railway container, supervised by `entrypoint.sh` alongside cron:

```bash
open https://optionsagent-production.up.railway.app
```

It restarts after a crash and serves read-only APIs without an access token. The dashboard and
trading scheduler remain separate processes; dashboard availability never enables trading.
`/healthz` returns a fixed liveness JSON response. It is deliberately NOT the Railway healthcheck:
a dashboard crash must not bounce cron mid-trade.

⚠️ It binds `0.0.0.0` on Railway's `$PORT` so the router can reach it, which means **anyone with
the URL can read it** — positions, P&L, account identifiers. That is a real change from the old
loopback-only setup. There is no password.

**Retired:** the per-user macOS `launchd` service
(`zsh deploy/install_local_dashboard.sh`, `launchctl kickstart -k gui/$UID/com.optionsagent.dashboard`,
`http://127.0.0.1:8765`). Its plist is `com.optionsagent.dashboard.plist.disabled` on the Mac,
booted out and disabled, as of 2026-09-01. Do not use `launchctl` to restart this bot; redeploy
with `railway up --service OptionsAgent`.

The trading gate is separate from dashboard availability. Cron reads `OA_TRADING_ENABLED` from the
generated `.env` because cron does not inherit the container environment. Keep it `false` while
running the dashboard; the local dashboard cannot submit orders.

⚠️ **3-touch-point rule (fleet gotcha):** a NEW env var must be added in (1) code/config,
(2) Railway variables, AND (3) the `secret_keys` allowlist in `entrypoint.sh` — cron jobs read
`.env`, which the entrypoint writes from that allowlist. Missing (3) = the var silently never
reaches the bot.

## Historical Railway operations (not used by the local runtime)

```bash
railway status                      # deployment state
railway logs                        # live container logs (cron output included)
railway redeploy --service OptionsAgent -y     # restart/redeploy current image
railway variables --service OptionsAgent       # list vars
railway variables --service OptionsAgent --set "KEY=VALUE" --skip-deploys
railway ssh --service OptionsAgent -- <cmd>    # one-off command inside the container
# NOTE: multi-line python -c does not survive ssh; single-line + double-wrapped quotes only
# (see ERRORS.md).
```

Secrets flow (operator preference — keep secrets out of the conversation): copy value to
clipboard, then `railway variables --set "KEY=$(pbpaste)" --skip-deploys` with output suppressed.

## Historical Railway kill switches

1. Set `OA_MAX_POSITION_USD=1` + redeploy → every trade skips on sizing (bot alive, trades nothing).
2. Change `config/config.json` `phase` to `"wheel"` (or an empty custom phase) + push → narrows or
   stops new entries; exit sweep keeps managing existing positions.
3. `railway down --service OptionsAgent` → container gone entirely (positions left unmanaged —
   close them in the Alpaca dashboard if any are open).

## Historical first-cycle watch (Monday 2026-07-06)

The integration layer never touched the live API before deployment (operator chose
straight-to-Railway). At 10:15 ET Monday, watch `railway logs` and `#options-agent`. Expected
first-contact failure shapes: alpaca-py field/shape mismatches in `option_chain`/`option_quotes`,
mleg order rejections (limit-price sign convention), proposer schema hiccups. All fail toward
"no trade + loud error", not silent wrong trades.


## Local runtime keys (2026-08-28)

Required in `.env` for the current local setup (beyond the original keys):
- `OA_TRADING_ENABLED=true`, `ALPACA_PAPER=true` (hard gates in every cron script)
- `DEEPSEEK_API_KEY` + `OA_LLM_PROVIDER=deepseek` (proposer; `OA_CLAUDE_*` only for `claude_cli`)
- `OA_DATA_KEY_ID` / `OA_DATA_SECRET_KEY` — read-only SIP-entitled stock-data key
  (the bot's own trading key gets only 15-minute-delayed SIP)
- `OA_OPTIONS_DATA_PROVIDER=public` + `PUBLIC_API_SECRET` (option chains/quotes)
- `OA_EQUITY_SCALP_ENABLED=true` (equity scalper master switch; tighten-only
  rails: OA_EQUITY_NOTIONAL_USD, OA_EQUITY_MAX_TRADES, OA_EQUITY_DAILY_LOSS_USD,
  OA_EQUITY_STOP_PCT)
- `OA_SCALP_ENABLED` is FALSE: the 0DTE option scalper is retired.

Crontab (local): entry `*/5 10 * * 1-5`, exits `*/20 9-16 * * 1-5`,
equity scalper `* 9-15 * * 1-5`, all via cron/*.sh with fail-closed market checks.
