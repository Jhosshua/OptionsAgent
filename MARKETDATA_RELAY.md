# Wingspan market-data connections

Updated 2026-09-09.

Production stock bars use AlpacaRelay through `OA_DATA_URL`, `OA_DATA_KEY_ID` and
`OA_DATA_SECRET_KEY`. Options chains/quotes use the read-only Public.com adapter
when `OA_OPTIONS_DATA_PROVIDER=public`. Execution always uses the separate Alpaca
paper credentials. Data adapters never place orders.

The optional publisher `run_marketdata.py` and `harness/marketdata_relay.py`
remain in the repository for shared snapshot delivery. `OA_MARKETDATA_ENABLED`
controls the publisher; it is not required for normal seller or stock execution.
Use the implemented routes and authentication in the server module if enabling
that separately authorized integration. Do not infer feed health from a dashboard
liveness response. Check timestamps, quote validity and provider error logs.

New feed variables must reach the entrypoint allowlist as well as Railway and code.
See SETUP.md for the current deployment and credential names.
