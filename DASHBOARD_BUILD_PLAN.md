# OptionsAgent dashboard build plan

## Goal

Build the supplied OptionsAgent dashboard as a production-safe, always-on web
surface for the paper credit-spread bot. The dashboard is an observation and
operations surface; it must never place, cancel, or modify orders.

## Reference decisions to preserve

- Daylight UI: white surfaces, `#EBEBEB` hairlines, 16px cards, 12px inner
  surfaces, pill-shaped controls, Nunito Sans with system fallbacks.
- Coral `#E5484D` is the single interface accent.
- Gain/loss colors are reserved for money: gain `#067647`, loss `#C13515`.
- Sidebar navigation: Overview, Positions, Trade history, Research, Risk rails,
  System.
- Overview layout: paper/deployment banner, Today P/L, Open spreads, Buying
  power, Profile status, Equity curve, Daily P/L, Credit spread history,
  Research replay.

## Runtime design

1. Add a dependency-free Python HTTP dashboard server under `harness/`.
2. Serve a responsive static frontend from `dashboard/` with the reference
   layout and an explicit application title, health endpoint, and accessible
   navigation/buttons.
3. Provide read-only JSON endpoints for summary, positions, trade history,
   research replay, risk rails, and system health. Read local JSONL/gzipped
   archives and use a dashboard-local read-only facade exposing only account,
   position, and quote reads; do not pass `PaperClient` into the web process.
   Never import execution modules or touch the trading lock directory. Add a
   static test that dashboard imports contain no `submit_`, `cancel_order`, or
   `harness.execution` references.
4. Require `Authorization: Bearer <OA_DASHBOARD_TOKEN>` for every data API;
   `/healthz` is fixed and unauthenticated, while the static shell contains no
   account data and may render a token-entry state. Validate a minimum 32-byte
   token, compare with `hmac.compare_digest`, return 401 without details, and
   apply a small per-IP failure backoff. The UI keeps a supplied token only in
   session storage, never in the static bundle. The token is environment-only.
5. Keep broker/API calls bounded and fail closed. A single background refresher
   updates a process-local snapshot every 30 seconds with a 10-second broker
   timeout; request handlers only read the last snapshot and never call Alpaca.
   Dashboard failures must not interrupt cron trading; unavailable broker data
   must render as unavailable, never as fabricated zeros.
6. Start the server through a bounded-backoff restart loop as a supervised
   background process from `entrypoint.sh`, bind to `0.0.0.0:$PORT` (default
   8080), and retain cron as the container's foreground process. Dashboard
   restarts must not kill cron. The loop logs to a capped/rotated dashboard log
   and skips startup when the dashboard token is missing. The launch subshell
   must be failure-isolated under `set -euo pipefail` (`|| true`) so a dashboard
   error cannot prevent cron installation. Add `/healthz` for manual/external
   probes only; `railway.json` must not set `healthcheckPath`, and `/healthz`
   returns only `{"status":"ok"}` when the server is alive.
7. Never expose credentials, raw broker responses, order secrets, filesystem
   paths, or write endpoints. Serve only an explicit static-root allowlist and
   fixed API routes; reject all other methods and paths. Read archive files
   only under `data/`, via `realpath` confinement, with streaming and hard
   per-file/row caps. Add no-store headers to authenticated responses.

## Data contracts

- Summary: paper/live mode, deployment status, account equity, buying power,
  today P/L, open spread count/cap, active winner-rule count, last cycle, and
  provider status, snapshot `as_of`, and consecutive refresh failures.
- Positions: normalized symbols, strategy, legs, contracts, entry credit,
  current mark when available, unrealized P/L when derivable, and status.
- History: closed structures and realized P/L from `data/structures.jsonl`,
  reduced by `(structure_id, opened_ts)` rather than ID alone. Preserve null
  P/L as `unknown`, count unavailable closes, and show sparse credit-spread
  history honestly when the archive contains other strategy types.
- Research: archived entry-day count, record count, realized replay, filtered
  profile replay, and rule labels from `OVERFIT_ANALYSIS.md`/research output.
- Risk/system: hard rails, phase, provider, last log/error timestamps, and
  process health. Stale account data is visibly marked stale after 120 seconds
  and switches to unavailable after repeated refresh failures.

## Safety and rollout gates

- `ALPACA_PAPER` must remain true; do not add live-order capability.
- Add `OA_TRADING_ENABLED` as an explicit gate checked by every trading cron
  script; default false in source and deployment templates, enabled only after
  paper credentials and the new OptionsAgent target are verified.
- Dashboard is read-only and defaults to offline-safe placeholders when broker
  credentials are absent.
- Add `OA_DASHBOARD_TOKEN` to the code/config/entrypoint allowlist and require
  it for any non-health dashboard request.
- Do not deploy to the currently linked `tqqq-qqq-paperbot` service. A new
  OptionsAgent Railway project/service/volume must be explicitly created and
  verified with `railway status` before deployment.
- Do not configure Railway's platform health check to restart this combined
  cron container from dashboard health alone. The dashboard owns `$PORT`; the
  market-data relay remains on its separate internal `OA_RELAY_PORT` and is not
  assumed to be publicly routed. Verify trading gate, cron schedule, dashboard
  process, and paper broker mode independently after start.
- Read `OA_TRADING_ENABLED` from `.env` inside every cron script (cron does not
  inherit the container environment), and add it to `entrypoint.sh`'s allowlist.
- The UI clears session storage and returns to token entry on any API 401, with
  a visible clear-token control.
- Before enabling `OA_TRADING_ENABLED=true`, verify in order: `railway status`
  names the new OptionsAgent service (never `tqqq-qqq-paperbot`), in-container
  `ALPACA_PAPER=true`, `/etc/cron.d/optionsagent` exists, dashboard process is
  alive, `/healthz` is 200, and an unauthenticated data API request is 401.
- Run three independent Claude Code critiques of this plan. Build only after
  all three critiques report no blocking issue, or after resolving every
  blocking issue they identify.
- After implementation: unit tests, security/static checks, full pytest, two
  independent QA reviews, local server smoke test, Playwright browser smoke
  test, then deployment health verification.
