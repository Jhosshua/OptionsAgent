# SETUP.md — OptionsAgent deployment runbook

> **RETIRED / NOT DEPLOYED (2026-08-27).** The Railway project, volume,
> paper-account keys, LLM key, and Discord webhook described below were deleted
> on 2026-08-02. This file is historical. A restart requires creating a new
> Railway project/service/volume and supplying new paper credentials and a new
> webhook; no restart or deployment was performed by the historical analysis.

Everything operational for the historical deployment: where it ran, the env vars, how to
redeploy, watch, and stop it. The current code also contains an intentionally overfit,
hard-coded credit-spread winner profile documented in `OVERFIT_ANALYSIS.md`.

## Where the historical deployment ran

- **Railway** project `OptionsAgent` (`e312c619-5ac9-4edb-9d57-6ec4d1252ddd`), single service
  `OptionsAgent`, region sfo, deployed from GitHub `Jhosshua/OptionsAgent` branch `main`
  (every push auto-deploys).
- **Volume** `optionsagent-volume` mounted at `/Users/mo/OptionsAgent/data` — holds
  `decisions.jsonl`, `structures.jsonl`, logs, and the cron once-per-day lock markers. Survives
  redeploys; the rest of the container filesystem does not.
- Container runs Linux cron in the foreground (see `Dockerfile`, `entrypoint.sh`,
  `cron/crontab.railway`). System TZ is America/New_York.

## Historical schedule

| Job | When | Guards |
|---|---|---|
| `cron/entry.sh` → `run_cycle.py` | 10:15-10:27 ET weekdays, once/day | ET window + atomic volume lock + broker market clock (fail-closed) |
| `cron/exits.sh` → `run_exits.py` | every 20 min, 9-16h ET weekdays | broker market clock (fail-closed); idempotent, no lock needed |

## Environment variables (Railway service variables)

| Var | What | Notes |
|---|---|---|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Paper account keys | Dedicated paper account (never share another bot's — exposure math tangles) |
| `ALPACA_PAPER` | `true` | Belt-and-suspenders; `make_client()` refuses non-paper anyway |
| `ANTHROPIC_API_KEY` | LLM proposer | Shared fleet key |
| `OA_ANTHROPIC_MODEL` | `claude-fable-5` | Proposer model override |
| `DISCORD_WEBHOOK_URL` | `#options-agent` webhook | Channel 1522587333822513253, StockBot guild |
| `OA_MAX_POSITION_USD` | (unset) | OPTIONAL tighten-only emergency brake: absolute $ ceiling per position |
| `OA_MAX_TOKENS` | (unset, default 4096) | Proposer output ceiling |

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

⚠️ **3-touch-point rule (fleet gotcha):** a NEW env var must be added in (1) code/config,
(2) Railway variables, AND (3) the `secret_keys` allowlist in `entrypoint.sh` — cron jobs read
`.env`, which the entrypoint writes from that allowlist. Missing (3) = the var silently never
reaches the bot.

## Common operations (from the Mac; CLI is authed via RAILWAY_API_TOKEN in ~/.zshrc)

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

## Kill switches, softest to hardest

1. Set `OA_MAX_POSITION_USD=1` + redeploy → every trade skips on sizing (bot alive, trades nothing).
2. Change `config/config.json` `phase` to `"wheel"` (or an empty custom phase) + push → narrows or
   stops new entries; exit sweep keeps managing existing positions.
3. `railway down --service OptionsAgent` → container gone entirely (positions left unmanaged —
   close them in the Alpaca dashboard if any are open).

## First-cycle watch (Monday 2026-07-06)

The integration layer never touched the live API before deployment (operator chose
straight-to-Railway). At 10:15 ET Monday, watch `railway logs` and `#options-agent`. Expected
first-contact failure shapes: alpaca-py field/shape mismatches in `option_chain`/`option_quotes`,
mleg order rejections (limit-price sign convention), proposer schema hiccups. All fail toward
"no trade + loud error", not silent wrong trades.
