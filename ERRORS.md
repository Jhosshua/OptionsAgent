# ERRORS.md — OptionsAgent

## Deep-research workflow: synthesis step returns a placeholder stub instead of real content

**What did not work:** trusting the `deep-research` workflow's top-level `result.findings` /
`result.summary` directly. On 2 of 3 research passes for this project, the final synthesis agent
call returned a literal `{"summary": "test", "findings": [{"claim": "test claim", ...}]}` stub —
a genuine bug in that run, not a sign the research found nothing.

**What worked instead:** read the run's `journal.jsonl` directly, find the individual claim-verify
agent calls (3 votes per claim), and hand-tally survive/kill per claim from the raw `refuted`
booleans. Cross-check against the top-level `result.refuted` array where present — it sometimes
reflects genuine per-claim votes even when `result.findings` doesn't.

**Note for next time:** if a `deep-research` (or similar workflow) result's summary/findings look
templated, generic, or suspiciously short given the `agent_count`/`tool_uses` stats, don't report it
to the user at face value — inspect the journal before drawing any conclusion about what the
research did or didn't find.
