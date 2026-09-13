# Wingspan current decisions

Updated 2026-09-13. Historical contradictory status and completed task notes were
removed; Git history retains them.

- Canonical name: Wingspan. Folder `/Users/mo/wingspan`, Railway `wingspan`, Discord
  `#wingspan`. WheelBot is a separate wheel-strategy project and paper account.
- Paper execution uses Alpaca CLI. Gemini via the agy CLI supplies proposals; Public.com and
  AlpacaRelay provide read-only market data. Railway owns the runtime and secrets.
- The active seller gate is `research_rules` with a $3,000 per-position ceiling.
  Six option-leg slots mean three two-leg spreads. The ceiling and gate stay paired.
- The stock scalper is independent of the seller. Its journal must be included in
  portfolio reporting. The 0DTE option scalper remains retired.
- Exits target 50% credit capture, a confirmed 2×-credit stop and 21 DTE closing.
  Keep profit limits working instead of canceling them after a short polling window.
- Persist closing intents, recover lost replies, confirm cancellation before
  replacement, and book quantities/P&L only from broker-confirmed fills.
- Discord V2 uses one card per update with the dashboard button inside it. Explain
  capacity as option legs/spreads; pending profit limits are status updates.

## 2026-09-09 T exit diagnosis

Read directly from the production journal and Alpaca order records:
- Opening: 15 T call spreads, $28/$30 strikes, October 16 expiry, $0.18 credit.
- 09:40, 10:00 and 10:20 ET: $0.08/$0.09/$0.09 closing limits remained unfilled;
  the application canceled each after approximately 33 seconds. No broker rejection.
- 10:40 ET: all 15 spreads filled at $0.08 debit. Gross realized P&L was $150.
- The earlier target observations were quote-based, not fills. Independent quote
  providers and broker execution need not match at every instant; the records do
  not prove the precise market-liquidity cause of each unfilled limit.
- MARA was correctly blocked while six option legs occupied the account. When T
  closed it freed two slots; CMCSA filled those slots in the afternoon cycle.

The fix replaces cancellation churn with durable day orders and actual-fill
accounting. It does not guarantee a fill or loosen entry/risk limits. Offline
regressions cover delayed/partial fills, lost replies, restart replay, missing
prices, cancellation races, dashboard accounting and duplicate prevention.

## 2026-09-13 AI proposer: agy CLI with Gemini 3.8 Flash low

- What was decided: removed the DeepSeek API and the Claude Code CLI. The only
  proposer is the Antigravity CLI (`agy`) running `gemini-3.8-flash-low`
  (`--effort low`). `OA_AGY_MODEL=gemini-3.8-flash-medium` switches to medium; any
  other model fails closed and pages Discord.
- Why: operator request. Bench (RESEARCH_AGY_EFFORT.md, 6 interleaved calls each on
  the Sep 11 close snapshot): both 6/6 OK, both followed every prompt rule, both
  always proposed MARA bearish. Low was about 2x faster (median 7.3s vs 16.4s) and
  always returned two ideas; medium dropped its second idea in 2 of 6 calls.
  Quality of the theses was equivalent. Low was chosen; profitability is NOT
  measured by this bench.
- How it runs on Railway: the Dockerfile uses Google's installer (same as
  ManualTrading2); entrypoint restores `/root/.gemini` from `GEMINI_HOME_TGZ_B64`
  (copied from ManualTrading2's variable, same Google account).
- Rejected: `--dangerously-skip-permissions` (a shell for the model on a box with
  broker keys); running agy inside the repo (it has reverted files where it ran);
  keeping DeepSeek as a fallback (operator asked for removal).
- Risk: the Google login can be revoked or expire. That shows up only as failed
  calls, which journal `proposer_result ok=false` and page Discord.
