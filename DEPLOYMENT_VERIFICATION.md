# Wingspan deployment verification — 2026-09-09

Verified against the running Railway image, Alpaca read-only order/position records,
Discord API and the user's local Chrome.

## Deployment and naming

- Runtime source revision: `e75271b`.
- Final deployment: `808d7ea9-acac-43fc-9736-c14bc8186be5`, SUCCESS.
- Mac/container directory: `/Users/mo/wingspan`.
- Railway project/service: `wingspan`; Discord channel: `wingspan`.
- Persistent data mount: `/Users/mo/wingspan/data`, volume name `wingspan-data`.
- Original volume ID `f2d1a835-debe-472b-b154-7c441fb98bc8` retained.

The structure ledger hash matched before and after the migration:
`7e52a286d751d4fd8b2d05806499b7d4459255da2ae43c25048c4705d4641fdf`.
The same CCL 15, AAL 30 and CMCSA 15 spreads remained tracked, matching six broker
option legs. Daily entry markers were preserved. Paper mode and the $3,000 cap
were verified from production. No account activation or forced entry/exit was used.

## Exit diagnosis and verification

Alpaca confirmed T's first three closing limits were unfilled and canceled by the
application after about 33 seconds, not rejected. The 10:40 ET order filled all
15 spreads at $0.08 against the $0.18 opening credit: **$150 gross realized profit**.
The records establish order outcomes; they do not identify the exact market-liquidity
cause for every unfilled quote-priced limit. MARA's capacity veto was valid.

The new lifecycle preserves tracked day limits, persists intent before submission,
recovers lost replies, prevents duplicate closes and confirms cancellation before
risk-driven replacement. Ledger quantity, gross P&L and captured-profit percentage
come from broker fills. Partial closes reduce exposure in one idempotent ledger event.

- Local complete suite with production-style gate settings: **302 passed**.
- Final deployed image complete suite: **302 passed**.
- Coverage includes delayed/partial fills, restart replay, cancellation races,
  missing/invalid fill prices, lost submission replies and dashboard accounting.
- New qualifying broker fills after deployment are not claimed by these tests.

Production-image QA exposed seven synthetic notifications from older scalp tests.
They were removed. The suite now clears real Discord credentials and blocks external
HTTP by default; the final production test run produced no Discord test messages.
Default-policy fixtures also isolate themselves from production's tighter risk settings.

## Customer experience

The existing channel was renamed in place, preserving channel ID/history. Real
Discord responses confirm flag `32768`, one container and a link-style Open dashboard
button. A factual update card is at:
https://discord.com/channels/1507539055364018326/1544462423111761990/1547325293709107254

The installed `browser-use` CLI connected to local Chrome; native Discord card
rendering was checked, and the dashboard button opened the expected Wingspan URL.
Discord's persistent trust checkbox was left unchanged. Desktop and 390px mobile
Wingspan pages rendered without horizontal page overflow. All five read APIs
(`/api/summary`, `/api/positions`, `/api/trades`, `/api/risk`, `/api/system`) returned
HTTP 200 and current system data. `/healthz` was checked separately.

Markdown runbooks were refreshed, contradictory operating notes and expired task
plans removed, and dated research retained as research. Local Markdown links resolve.
The original public dashboard hostname and GitHub repository URL stay valid.

API contracts used: [Discord Components V2](https://docs.discord.com/developers/components/using-message-components)
and [Alpaca multi-leg options](https://docs.alpaca.markets/us/docs/options-level-3-trading).

## 2026-09-13 agy proposer deployment

- Source revision `e972929`, deployment `b9c3665d-095f-4a4c-93b7-16865498e9ab`, SUCCESS.
- Volume `f2d1a835-debe-472b-b154-7c441fb98bc8` unchanged; structures ledger hash
  `7e52a286...641fdf` identical before and after. Paper gate still `ALPACA_PAPER=true`.
- In the container: `/usr/local/bin/agy` 1.2.2, `/root/.gemini` login restored from
  `GEMINI_HOME_TGZ_B64`, `OA_AGY_MODEL=gemini-3.8-flash-low` in the cron `.env`.
- Real read-only bundle built in the container, then 4 agy calls (2 low, 2 medium):
  4/4 OK, low 9-10s, medium 17-22s. `propose_report` under a cron-like empty
  environment: `agy gemini-3.8-flash-low ok=True attempts=1 6.0s`, 3 ideas.
  No entry cycle was run and no orders were placed.
- Railway `DEEPSEEK_API_KEY`, `OA_DEEPSEEK_MODEL`, `OA_LLM_PROVIDER` deleted after
  verification. `/api/system` reports `agy / gemini-3.8-flash-low`; its "last" row
  stays the Sep 11 DeepSeek cycle until the first agy cycle (Monday 10:15 ET).
- Local suite: 301 passed.
