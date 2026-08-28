# DeepSeek prompt: OptionsAgent credit-spread overfit review

> **CURRENT RUNTIME NOTE — 2026-08-28:** This is a read-only research prompt, not the runtime
> proposal path. The active local bot uses the authenticated Claude Code CLI, Public.com read-only
> data, and Alpaca paper execution. No Anthropic API key or Railway deployment is required.

Run this from `/Users/mo/OptionsAgent` with the local DeepSeek wrapper. Do not
edit files. Return a recommendation only.

```text
You are reviewing the OptionsAgent repository at /Users/mo/OptionsAgent.
This is an Alpaca paper options bot whose active strategy phase is
credit_spreads_only. Focus on the multi-day credit-spread seller, not the
separate 0DTE scalp module.

Read these files and inspect the archived data:
- CLAUDE.md, MEMORY.md, RESEARCH.md, ARCHITECTURE.md, OVERFIT_ANALYSIS.md
- config/config.json
- run_cycle.py, harness/contracts.py, harness/risk_rails.py
- data/structures.jsonl and data/decisions.jsonl

The credit-spread archive has 5 entry days and 10 credit-spread records. The
8 non-zero quote-based realized results are:
CCL bullish put width 1.0 credit .17: -306
MARA bullish put width 1.0 credit .23: -25
AAL bullish put width 1.0 credit .19: -57
VZ bullish put width 1.0 credit .17: -221
CCL bullish put width 1.5 credit .29: +45
SOFI bullish put width 1.0 credit .23: +40
AAL bullish put width 1.0 credit .19: -165
F bearish call width .5 credit .06: +45
There is also one opening order that never filled ($0) and one still-open
SOFI spread with unknown P/L. These are conditional registry outcomes, not a
full quote/fill backtest.

The operator explicitly wants maximum in-sample P/L through overfitting, even
though the sample is tiny. Derive the narrowest deterministic entry profile
that maximizes replayed realized P/L. Consider underlying, bullish/bearish
direction, put/call family, width, minimum credit, DTE, delta, entry date/time,
and exit rules. Be exact about what is and is not identifiable from this data.

Return exactly:
1. Winning profile with explicit inequalities.
2. Replayed trade IDs/records included and excluded.
3. In-sample P/L, win rate, and number of observations.
4. Concrete code/config changes required in run_cycle.py and/or
   harness/risk_rails.py.
5. Three failure modes caused by overfitting and the minimum prospective sample
   you recommend before relaxing or changing the profile.
Do not claim statistical significance, do not invent unavailable quotes, and do
not recommend deployment credentials or live trading.
```

Suggested invocation:

```bash
cd /Users/mo/OptionsAgent
/Users/mo/ManualTrading2/bin/ds "$(sed -n '/^```text$/,/^```$/p' DEEPSEEK_CREDIT_SPREAD_PROMPT.md | sed '1d;$d')"
```

If that wrapper hangs, use the `claude-ds` shell function from `~/.zshrc` in an
interactive terminal and paste only the prompt block above. The current repo
has no valid Railway deployment target, so keep the review read-only.
