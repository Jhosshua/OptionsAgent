# Wingspan diagnostic lessons

Updated 2026-09-09. Resolved one-off build narratives and obsolete setup advice removed.

- A profit target is a quote observation until a broker order fills. Do not report
  an unfilled limit as a rejected trade or book a quoted gain as realized P&L.
- Cancellation is asynchronous. A request or `pending_cancel` cannot authorize a
  replacement order. Persist and reconcile the original order first.
- A filled exit can remove both legs before the next sweep. Reconcile pending
  closes before interpreting absent broker positions as assignment/manual action.
- Use terminal filled quantity and actual net fill price. Update remaining exposure
  and realized P&L in one idempotent ledger event keyed by broker order ID.
- Cron does not inherit Railway variables: maintain the entrypoint allowlist.
- A volume rename must preserve the volume ID, data and daily execution markers.
- The public dashboard reads both seller and stock journals. Missing state is not
  a zero-activity success. `/healthz` alone is insufficient verification.
- Tests must freeze dates for same-day scalp fixtures; wall-clock drift otherwise
  makes correctly expired fixtures look like regressions.
- Discord webhook errors can contain credential-bearing URLs. Log the exception
  class, not raw exception text. Disable mentions in automated card payloads.

- Production-image QA exposed older scalp tests that inherited real Discord
  credentials and sent synthetic notifications. The seven test messages were
  removed. `tests/conftest.py` now clears notification credentials after dotenv
  loads and rejects external HTTP unless a test installs a fake. Production
  tests must keep broker adapters and state isolated as well as notifications.
