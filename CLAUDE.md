# Wingspan engineering guide

Updated 2026-09-09. Read this and SETUP.md before editing or operating the bot.

- Canonical local folder: `/Users/mo/wingspan`. Railway project/service: `wingspan`.
- This is the options credit-spread and stock-scalper bot. WheelBot is a separate
  project in `/Users/mo/wheelbot` with a separate paper account.
- Railway runs the trader. Keep local launchd and cron trading disabled.
- Paper only. Preserve the existing trading gate, account separation and risk caps.
  A deployment or health check never authorizes a change to live-money trading.
- DeepSeek proposes only underlying, direction, strategy, conviction and thesis.
  Deterministic code owns strike selection, size, orders and exits.
- Keep `research_rules` paired with the $3,000 absolute cap. Six option-leg slots
  represent at most three two-leg spreads. Do not loosen rails to increase fills.
- Alpaca CLI is the production order transport; no silent SDK fallback. The stock
  scalper's existing emergency flatten exception is separately journaled.
- Keep market data and execution credentials separate. Never log or commit secrets.
- Persist an exit intent before submission, reconcile existing orders before
  missing-leg classification, and book only confirmed quantities and fill prices.
  A cancellation request is not proof that an order stopped working.
- An exit ledger event must update realized P&L and remaining exposure together.
  Preserve idempotency by broker order ID and the independent engine journals.
- Discord uses one V2 container per update with a dashboard link. Keep messages
  understandable without strategy IDs, environment names or unexplained jargon.
- A new cron setting needs code support, a Railway variable and the entrypoint
  `.env` allowlist. Railway variables are the production source of truth.
- Tests use temporary state and fake brokers. Do not run an entry cycle as a
  connectivity check; it can submit orders.
- Run relevant tests, commit and push changes, then deploy when authorized.
  Verify deployment state, volume identity, loaded code and read-only broker data.
  Distinguish synthetic tests, actual market scans and broker-confirmed fills.

Current modules, schedules and persistent files are listed in ARCHITECTURE.md
and SETUP.md. Obsolete deployment/retirement notes were removed on 2026-09-09;
Git history retains the historical change record.
