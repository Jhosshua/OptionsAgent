# Task: UPDATE the OptionsAgent explainer (Airbnb light design already chosen)

You are updating ONE file: /Users/mo/OptionsAgent/data/pdf_assets/explainer_gemini.html
Do not create, edit, or delete any other file. Do not run git. Do not print the PDF.

Keep the existing Airbnb-DLS light-mode design language (white cards, #F7F7F7 background,
coral #FF5A5F for Engine 1, teal #00A699 for Engine 2, relaxed type, 11x8.5in landscape,
8 pages, same structure: simplified page 1, rules+FAQ page 2, six screenshot pages 3-8 using
dash_overview.png, dash_positions.png, dash_trades.png, dash_research.png, dash_risk.png,
dash_system.png in the same directory). Update the CONTENT to the facts below.

## What changed since the last version (make sure ALL of these are reflected)
1. There are now THREE engines? No, TWO active engines, and one retired:
   - ENGINE 1 (coral): credit-spread seller, unchanged.
   - ENGINE 2 (teal): REPLACED. The 0DTE option scalper was studied over 6 months
     (125 sessions, 16,384 parameter combos) and NO positive-expectancy configuration
     exists; long 0DTE options cannot harvest the tiny underlying edges because theta
     plus spread costs exceed them. It has been switched OFF.
   - ENGINE 2 (teal) is now the EQUITY intraday scalper: share positions in SPY and
     QQQ (no options), built from the same 6-month study. Two rules, mined in-sample
     and frozen to collect live out-of-sample evidence:
     a) "Morning fade": at 10:15 ET, if price is above BOTH session VWAP and the
        15-minute opening-range high, SHORT; below both, LONG. Exit after 120 minutes,
        on a 0.7% stop, or at the 15:50 ET flatten. In-sample: +$23.6 per trade, 60%
        win, positive in both halves of the data.
     b) "Gap follow": QQQ only, at 13:00 ET, when the day gapped more than 0.8% at
        the open, hold WITH the gap direction until ~15:00, same exits. In-sample:
        +$34.3 per trade, 64% win, out-of-sample t=+3.1.
   - Risk controls: $20,000 notional per position, max 2 trades a day, max 2 open,
     0.7% stop, 120-minute time exit, MANDATORY 15:50 ET flatten, -$300 daily halt
     (halt re-arms next day), orphan adoption (a crashed tick cannot strand a position).
2. The account: $100,000 Alpaca paper (re-funded Aug 28). The dashboard was reset to
   the Aug 28 activation date, so history is empty by design and the equity curve is
   a flat $100k. Screenshots show this clean state.
3. Data plumbing worth one FAQ answer: stock bars and spot run through a read-only
   SIP-entitled data key (the bot's own trading key only gets 15-minute-delayed data);
   option chains and quotes come from a read-only Public.com sidecar; orders stay on
   the bot's own paper key.

## PAGE 1 (keep it simple, four zones)
- Header: name + one-line subtitle + pills (PAPER ONLY / TWO ENGINES / RUNS ON THIS
  MAC / LLM ONLY ADVISES ENGINE 1).
- Lede, max 3 sentences: two engines on one $100,000 Alpaca paper account. Engine 1
  sells credit spreads after Claude proposes and deterministic rails dispose. Engine 2
  trades SPY/QQQ shares intraday on two frozen, data-mined rules, no LLM anywhere.
- Two engine cards side by side (coral seller, teal equity scalper), each with a short
  bullet summary, its schedule, and its 2-3 key numbers. Engine 2 card should note the
  6-month study and that the 0DTE option scalper was retired with evidence (one line).
- Slim "Today, Aug 28" strip, one line each:
  * Claude proposed 8 spreads, the rails executed 0 (three had no matching contract,
    five failed the winner profile). Vetoing everything is the system working.
  * A 6-month study retired the 0DTE option scalper (no positive expectancy) and
    armed its share-based replacement for Monday.
  * The scalper's first live windows are Monday 10:15 and 13:00 ET.

## PAGE 2: rules strip + FAQ (keep the 13-ticker watchlist chips + four never-rules
strip at top, then the FAQ). FAQ list, exactly these 12:
1. Is this real money? No, Alpaca paper only; the broker client refuses non-paper endpoints.
2. What exactly does the LLM control? The idea only (ticker, direction, conviction,
   thesis) for the seller. The equity scalper uses no LLM at all.
3. Why credit spreads? Day one a MARA long put lost 37.6% of premium; pivot to selling
   defined-risk premium with a width-capped worst case.
4. How does the seller size? Conviction-scaled share of free buying power; 30% at the
   0.60 floor to 100% at 0.85+; skips below one contract.
5. 100% of buying power sounds aggressive. Deliberate policy; brakes = $2 width cap,
   6 positions, broker rejection, tighten-only kill switch OA_MAX_POSITION_USD.
6. What is the winner profile gate? Three replayed winners (CCL/SOFI bullish puts,
   F bearish calls), hard-coded, fail closed, frozen in-sample profile.
7. What does the equity scalper actually do? The two rules with their numbers, exits,
   sizing, flatten, daily halt. Note honestly: these rules are in-sample overfits,
   deliberately frozen; live trading IS the out-of-sample test.
8. Why shares instead of 0DTE options? The same 6-month study found real but tiny
   underlying edges (10-18bp); long 0DTE theta plus spread costs are 3-10x that, so
   every option configuration lost. Shares cost ~1.3bp round trip, leaving the edge.
9. Walk me through the exits. Seller: 50% profit, 2x credit stop confirmed twice,
   21 DTE close, dividend check. Equity scalper: 0.7% stop, 120-minute time exit,
   15:50 flatten, -$300 daily halt.
10. Overnight risk? The seller holds defined-risk spreads (max loss = width minus
    credit, about $200 each, worst day near $1,200). The equity scalper never holds
    overnight: everything flattens by 15:50 ET.
11. How do I know what it did on any given day? Read-only dashboard at
    127.0.0.1:8765; decisions in data/decisions.jsonl and structures.jsonl (seller);
    equity scalper in data/equity_scalp_decisions.jsonl and equity_scalp_state/.
12. What stops a bug from doing something catastrophic? Rails hard-coded in Python,
    env may only tighten; broker client refuses non-paper; one locked entry window a
    day for the seller; the equity scalper adopts orphaned positions, flattens
    everything by 15:50 ET, and halts at -$300.

## Style rules (strict)
- Plain, confident English. No em dashes or long dashes; commas, periods, parentheses.
- No marketing fluff. Numbers must match this brief exactly.
- Footer on every page: "OptionsAgent explainer, built from the code and live account,
  Aug 28 2026" plus "page N of 8".
- Update screenshot captions where the content changed (Overview now shows the clean
  reset: flat $100k equity, no history; System shows the current runtime flags).

Reply with a one-paragraph summary of your content updates when done.
