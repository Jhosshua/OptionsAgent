# Task: REDESIGN the OptionsAgent explainer from scratch, Airbnb design language, LIGHT mode

You are designing ONE file: /Users/mo/OptionsAgent/data/pdf_assets/explainer_gemini.html
(replace it entirely). Do not create, edit, or delete any other file. Do not run git. Do not print
the PDF yourself. The previous version of this file is being thrown away; do not build on it.

## Design direction: Airbnb DLS, light mode
- Background: warm off-white / light gray (#FFFFFF and #F7F7F7). Cards: white with soft 1px
  borders (#EBEBEB) or very subtle shadows, 12-16px corner radii. Generous whitespace. Nothing
  dark except the dashboard screenshots themselves (they are dark; frame them on white).
- Type: rounded friendly sans. Use system stack ("Airbnb Cereal", -apple-system, "Helvetica
  Neue"). Big bold headlines (#484848 body text, #222 or darker for headings), secondary text
  #767676. Line height relaxed.
- Color coding the two engines, used consistently: the credit-spread SELLER = Airbnb coral
  (#FF5A5F), the 0DTE SCALPER = Airbnb teal (#00A699). Status/positive = #00A699, warning =
  #FC642D, danger = #D4141A-ish red used sparingly.
- Components to use: pill chips, stat tiles (big number + small label), horizontal step cards,
  simple outlined tables. Rounded, calm, uncluttered. It should feel like an Airbnb product page,
  not a trading terminal.

## CRITICAL feedback on the previous version: page 1 was too convoluted and confusing
Page 1 must be SIMPLE. At most these zones, top to bottom:
1. A clean header: name "OptionsAgent", one-line subtitle, and 3-4 status pills.
2. A short lede (3 sentences max) saying: two engines on one $100,000 Alpaca paper account;
   Claude proposes ideas and code decides everything; most days nothing trades, by design.
3. TWO engine cards side by side (the heart of the page): "Engine 1, Credit-Spread Seller" in
   coral and "Engine 2, 0DTE Scalper" in teal. Each card: a 3-4 bullet summary in plain words,
   its schedule, and its 2-3 most important numbers. Keep bullets short. No pipelines longer
   than 4 steps on this page.
4. One slim "Today, Aug 28" strip along the bottom: the real-day facts below, one line each.
That is all. Move anything else (watchlist, guardrails, detailed rules) to a compact zone at the
top of page 2 above the FAQ, or fold it into the FAQ answers. Whitespace beats density.

## Page structure (exactly 8 pages, 11in x 8.5in landscape)
- Use `@page { size: 11in 8.5in; margin: 0; }`, each page a fixed 11in x 8.5in block with
  `page-break-after: always`. All CSS inline in the file. No external fonts/scripts/libraries.
  `-webkit-print-color-adjust: exact` everywhere.
- PAGE 1: as specified above.
- PAGE 2: title "The rules and the FAQ". Top: one compact strip holding the 13 watchlist tickers
  (F T PFE VZ CMCSA KVUE SOFI CCL AAL WBD MARA EWZ KWEB) and the four "never" rules (below).
  Then the 12-question FAQ in 2-3 columns, light cards, readable (min 9px answers).
- PAGES 3-8: one dashboard screenshot per page, full-width in a white card frame with a small
  caption header (name + one sentence). Image paths (same directory as the HTML):
  dash_overview.png, dash_positions.png, dash_trades.png, dash_research.png, dash_risk.png,
  dash_system.png. Images are 2704x1336 (about 2:1), they fit full-width with caption room.

## VERIFIED FACTS (use exactly these; do not invent numbers)
The bot runs locally on this Mac, weekday cron, Alpaca PAPER only, $100,000 account (re-funded
Aug 28). The code refuses non-paper endpoints. Two engines:

ENGINE 1, the credit-spread seller (coral):
- Weekdays 10:15-10:27 ET, once a day, locked. Fails closed: clock error or closed market = skip.
- Claude (local CLI, sonnet, no tools) reads a market summary and proposes ONLY ticker,
  direction, conviction 0-1, and a one-line thesis. Never strikes, deltas, or sizes. If Claude
  fails: zero trades. Everything else is deterministic Python.
- Gates: conviction floor 0.60; max 6 open positions; credit spreads only. Bullish = put spread,
  bearish = call spread. Short leg 15-30 delta, width max $2.00, 30-45 DTE, one combo limit
  order at the net credit (prefix oa-).
- Sizing: 30% of free buying power at 0.60 conviction, scaling to 100% at 0.85+. Below one
  contract: skip.
- Winner profile gate: must match one of three hard-coded replayed winners, else veto: CCL
  bullish put (credit >= $0.29, width >= $1.50), SOFI bullish put (>= $0.23, >= $1.00), F bearish
  call (>= $0.06, width <= $0.50). Frozen in-sample profile; this is why most days trade nothing.
- Exits every 20 min, no LLM: take profit at 50% of credit; stop at 2x credit only from 10:00 ET
  and only after two consecutive sweeps confirm; force close at 21 DTE; dividend check on short
  calls. Worst case per spread = width minus credit, about $200; worst day near $1,200.

ENGINE 2, the 0DTE ORB scalper (teal), ARMED Aug 28 at 12:25 ET after live verification:
- Every minute 09:33-15:59 ET weekdays. No LLM anywhere. Own files, own order prefix oas-.
- SPY and QQQ same-day (0DTE) ATM options only. Opening range = 09:30-09:33 ET high/low. Entry
  needs a 1-minute close outside the range on 1.5x average volume, then the NEXT bar confirming
  still outside the range and on the right side of VWAP. Break up = buy a call, break down = a
  put. Skips contracts with (ask-bid)/mid above 15%.
- Caps: $250 fixed per trade, max 2 trades a day, one open at a time, each direction once per
  symbol, no entries at/after 11:30 ET (12 of 12 late entries in its archived history lost).
- Exits: +50% target; -30% stop, widening to -60% while the breakout holds; 15-minute theta cut;
  MANDATORY flatten by 15:50 ET so nothing rides into 0DTE auto-exercise. Self-heals vanished
  positions and re-adopts orphans.
- Data: real-time SIP bars and spot via a read-only entitled data key while orders stay on the
  bot's own paper key; option chains and quotes from a read-only Public.com sidecar. First live
  entry window: Monday 09:33 ET.

The four "never" rules (page 2 strip):
- Never let model output pick a strike, delta, or expiration.
- Never loosen a rail by editing config (env vars may only tighten).
- Never place a live-money order.
- Never buy options after an extended move (anti-chase rule).

Today, Aug 28 (page 1 bottom strip, one line each):
- Claude proposed 8 spreads; the rails executed 0 (3 no matching contract, 5 failed the winner
  profile). Vetoing everything is the system working.
- The exit sweep closed July's SOFI spread for +$26.58.
- The scalper was armed at 12:25 ET after its data feed was verified real-time to the minute.

## FAQ (page 2, exactly these 12, answers consistent with the facts above)
1. Is this real money? No, Alpaca paper only, the code refuses non-paper endpoints.
2. What exactly does the LLM control? The idea only (ticker, direction, conviction, thesis);
   schema-checked, malformed = dropped. The scalper uses no LLM at all.
3. Why credit spreads? Day one a MARA long put lost 37.6% of its premium in a session; the bot
   pivoted to selling defined-risk premium with a width-capped worst case.
4. How does sizing work? Conviction-scaled share of free buying power; 30% at the 0.60 floor to
   100% at 0.85+; skips below one contract.
5. 100% of buying power sounds aggressive. Deliberate policy; the brakes are the $2 width cap,
   6 positions, broker rejection, and a tighten-only kill switch (OA_MAX_POSITION_USD).
6. What is the winner profile gate? Three replayed winners, hard-coded, fail closed, a frozen
   in-sample profile held unchanged to collect honest out-of-sample evidence.
7. Walk me through the exits. Seller: 50% profit, 2x credit stop confirmed twice, 21 DTE close,
   dividend check. Scalper: +50% target, -30 or -60% stop, 15-minute theta cut, 15:50 flatten.
8. Assignment and overnight gap risk? Verticals are defined risk, max loss is width minus
   credit; the stop is loss control, not a guarantee; worst day near $1,200; the scalper never
   holds overnight.
9. Is there a daily loss limit? The seller has none, only structural brakes. The scalper is
   bounded at 2 x $250 before exits, with an optional halt switch.
10. What does the 0DTE scalper actually do? Full mechanism from the facts above.
11. How do I know what it did on any given day? Read-only dashboard at 127.0.0.1:8765, plus
    data/decisions.jsonl and data/structures.jsonl for the seller, data/scalp_decisions.jsonl
    and data/scalp_positions.jsonl for the scalper.
12. What stops a bug from doing something catastrophic? Rails hard-coded in Python, env may only
    tighten; the broker client refuses non-paper; one locked entry window a day; the exit sweep
    reconciles the registry against live positions and alerts on anything vanished; the scalper
    force-flattens at 15:50 ET and re-adopts orphans.

## Style rules (strict)
- Plain, confident English. No em dashes or long dashes anywhere; use commas, periods,
  parentheses. No marketing fluff ("delve", "seamless", "cutting-edge").
- Numbers must match the facts exactly.
- Footer on every page: "OptionsAgent explainer, built from the code and live account, Aug 28 2026"
  plus "page N of 8".
- Light mode throughout. The only dark elements are the six screenshots.

When done, reply with a one-paragraph summary of the redesign decisions. Again: write ONLY
explainer_gemini.html. Nothing else.
