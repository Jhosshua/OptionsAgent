# Wingspan architecture

Updated 2026-09-13. This describes the implemented production system.

## Options engine

`run_cycle.py` builds market context, asks `harness/proposer.py` for Gemini
proposals through the Antigravity CLI (`agy`, Gemini 3.8 Flash low effort), then applies `risk_rails.py`, `contracts.py` and `execution.py`.
The model never specifies option strikes or sizes. `research_rules` enables the
liquidity/width/DTE/delta gate with a required $3,000 cap. The strict historical
winner-profile mode remains an optional, deliberately narrow research configuration.

`structures.py` records confirmed openings and manages remaining contracts.
`run_exits.py` evaluates deterministic profit, stop and DTE rules. For credit
spreads, `spread_exit_orders.py` saves a submission intent before the broker call,
uses explicit buy-to-close/sell-to-close legs, and keeps a day limit working.
A lost submission response is recovered by its client order ID. An unknown order
state blocks duplicate submission. A risk exit replaces an existing profit order
only after terminal cancellation and accounting for any partial fill.

Each terminal fill produces one idempotent `exit_fill` ledger event containing
broker order ID, actual fill price, closed contracts, remaining contracts and gross
realized P&L. The dashboard and trading registry read the same event. Recovery runs
before missing-leg reconciliation so a completed close is not mislabeled assignment.

## Stock engine

`run_scalp_equity.py` owns its independent journal and daily state. It trades SPY/QQQ
shares using the frozen morning-reversal and gap-continuation rules. The retired
`run_scalp.py` option strategy has a separate disabled flag and registry.

## Adapters and notifications

`alpaca_glue.py` provides the paper broker interface. `alpaca_cli.py` executes and
journals the official CLI calls. Public.com is read-only options data; AlpacaRelay
supplies stocks. `notify.py` renders a single Discord Components V2 container with
an internal dashboard button. Delivery failures do not interrupt trading.

## Dashboard and runtime

`harness/dashboard_server.py` and `dashboard/` expose a read-only public view of
both engines, combining their journals and broker snapshots. ET dates define daily
P&L. A missing journal or failed provider is not rendered as a successful scan.

Railway runs cron and the independently supervised dashboard from one container.
Persistent files live on the existing volume. `entrypoint.sh` writes the cron `.env`,
validates the volume, restores the agy Google login from `GEMINI_HOME_TGZ_B64`
and installs `cron/crontab.railway`. See SETUP.md for operations.
