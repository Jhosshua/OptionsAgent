# Task: build a completely fresh, redesigned explainer PDF source for OptionsAgent

You are designing ONE file: /Users/mo/OptionsAgent/data/pdf_assets/explainer_gemini.html
Do not create, edit, or delete any other file. Do not run git. Do not print the PDF yourself.

## What this document is
An operator-facing explainer for OptionsAgent, a local paper-trading options bot. Your HTML will be
printed to an 11in x 8.5in LANDSCAPE PDF by an external renderer afterward, so:
- Use `@page { size: 11in 8.5in; margin: 0; }` and make each page a fixed 11in x 8.5in block with
  `page-break-after: always` (8 pages total, structure below).
- All CSS inline in the file. No external fonts, scripts, or libraries (the renderer is offline
  except local files). System fonts only: -apple-system / "SF Pro" / Menlo for mono.
- Dark theme that visually matches the dashboard screenshots (near-black background like #0a0f16,
  panel cards, green #35d39a for the primary accent, amber for warnings, red for risk).
- Print-safe: `-webkit-print-color-adjust: exact` on everything.

## Page structure (exactly 8 pages)
1. PAGE 1 "How it works": title header with status chips (PAPER ONLY / TWO ENGINES / RUNS ON THIS
   MAC / LLM NEVER PICKS STRIKES), a one-paragraph lede, a numbered pipeline for ENGINE 1 (the
   seller, 6 steps, below), a visually distinct strip or panel for ENGINE 2 (the scalper), a
   key-numbers card covering BOTH engines, a card with the 13-name watchlist as ticker chips
   (F T PFE VZ CMCSA KVUE SOFI CCL AAL WBD MARA EWZ KWEB), a "what it will never do" card, and a
   "a real day" card (Aug 28 facts below).
2. PAGE 2 "FAQ": single FAQ section, 12 questions (list below), two or three columns, dense but
   readable (min 9px answers).
3. PAGES 3-8: one dashboard screenshot per page, full-width inside a bordered frame, each with a
   small header (name + one-sentence caption). Use these exact local image paths (same directory
   as your HTML): dash_overview.png, dash_positions.png, dash_trades.png, dash_research.png,
   dash_risk.png, dash_system.png. The images are 2704x1336 (about 2:1), so they fit full-width
   with room for a caption bar.

## VERIFIED FACTS (use exactly these; do not invent numbers)
Engine 1, the credit-spread seller:
- Runs once per weekday, 10:15-10:27 ET, from a local crontab, with an atomic once-per-day lock.
  Fails closed: broker clock check error or market closed = skip the day.
- Account: $100,000 Alpaca PAPER account (re-funded Aug 28). Orders only on this account's paper
  key; the code refuses non-paper endpoints.
- Watchlist: 13 liquid names under $50 (listed above).
- The LLM is the local Claude Code CLI (model sonnet), invoked with no tools and no web. It
  proposes ONLY {underlying, direction, conviction 0-1, thesis}. It may not name strikes, deltas,
  or sizes. Any CLI/auth/parse failure = zero proposals = no trades (fail closed).
- Deterministic rails: conviction floor 0.60 (below = veto), max 6 concurrent positions, phase
  allowlist = credit_spread only. Size = 30% of available options buying power at 0.60 conviction
  scaling linearly to 100% at 0.85+. Contracts = budget / (width x 100); below 1 contract = skip.
- Contract selection (deterministic, never the LLM): short leg 15-30 delta, long leg further OTM
  same expiry, width capped at $2.00, 30-45 DTE. Bullish = put credit spread, bearish = call
  credit spread. One MLEG combo limit order at the net credit, order IDs prefixed oa-.
- Winner profile gate: the spread must ALSO match one of three hard-coded replayed historical
  winners, else veto: CCL bullish put (credit >= $0.29, width >= $1.50), SOFI bullish put
  (credit >= $0.23, width >= $1.00), F bearish call (credit >= $0.06, width <= $0.50). Deliberate
  in-sample overfit, frozen to collect out-of-sample evidence. This is why most days trade nothing.
- Exit sweep, every 20 minutes market hours, no LLM: profit target 50% of credit; stop at 2x credit
  but only evaluated from 10:00 ET and needs two consecutive 20-minute sweeps to confirm (so one
  wide quote cannot force a liquidation); force close at 21 DTE; ex-dividend check on short calls.
- Worst case per spread = width minus credit, about $200. Six positions bound a worst day near
  $1,200 (about 1.2% of the account).

Engine 2, the 0DTE ORB scalper (ARMED as of Aug 28, 12:25 ET, after live verification):
- Fully isolated: own state files, own registry, own order prefix oas-, zero LLM anywhere.
- Instruments: same-day-expiry (0DTE) ATM options on SPY and QQQ only.
- Signal: opening range = 09:30-09:33 ET high/low. Entry requires a 1-minute bar closing outside
  the range with volume >= 1.5x the session average, THEN the next bar must confirm (still outside
  the range and on the matching side of session VWAP). Break up = buy ATM call, break down = ATM put.
- Liquidity guard: skip any contract whose (ask-bid)/mid > 15%.
- Caps: $250 fixed per trade, max 2 trades per day, 1 open at a time, each direction once per
  symbol per day, no new entries at/after 11:30 ET (12 of 12 late entries in its own archived
  history lost).
- Exits: +50% profit target; -30% stop that widens to -60% while the breakout thesis is intact;
  15-minute theta cut if flat and thesis broken; MANDATORY flatten by 15:50 ET so nothing rides
  into 0DTE auto-exercise. If the broker position vanishes, the registry self-heals and alerts.
- Data: real-time SIP 1-minute bars and spot through a read-only SIP-entitled data key
  (OA_DATA_KEY_ID/OA_DATA_SECRET_KEY in .env) while orders stay on the bot's own paper key.
  Option chains and quotes come from a read-only Public.com sidecar. The bot's own trading key
  lacks real-time SIP (15-minute delayed), which is why the split exists.
- Runs every minute 09:33-15:59 ET weekdays from the same local crontab, self-gated and locked.

A real day (Aug 28, 2026):
- The seller: Claude proposed 8 credit spreads (T, CMCSA, WBD, VZ, PFE, MARA, CCL, AAL). Rails
  executed 0: three found no contract matching the delta/width/credit rules, five failed the
  winner profile. The exit sweep closed July's SOFI spread for +$26.58. Vetoing everything is the
  system working, not failing.
- The scalper was armed at 12:25 ET after its data feed was verified real-time to the minute.
  First live entry window: Monday 09:33 ET.

## FAQ (page 2, exactly these 12, answers consistent with the facts above)
1. Is this real money? (No. Paper only, code refuses non-paper endpoints.)
2. What exactly does the LLM control? (Idea only: ticker, direction, conviction, thesis. Schema-
   checked, malformed = dropped. The scalper uses no LLM at all.)
3. Why credit spreads? (Day-one MARA long put lost 37.6% of premium; pivot to selling defined-risk
   premium with width-capped worst case.)
4. How does sizing work? (Conviction-scaled share of available BP; 30% at floor, 100% at 0.85+;
   skip below one contract.)
5. 100% of buying power sounds aggressive. (Deliberate operator policy; brakes = $2 width cap,
   6 positions, broker BP rejection, tighten-only kill switch OA_MAX_POSITION_USD.)
6. What is the winner profile gate? (Three replayed winners, hard-coded, fail closed, frozen
   in-sample overfit held to collect out-of-sample evidence.)
7. Walk me through the exits. (Seller: 50% / 2x-credit confirmed twice / 21 DTE / dividends.
   Scalper: +50% / -30 or -60% / 15-min theta cut / 15:50 flatten.)
8. Assignment and overnight gap risk? (Verticals = defined risk, max loss width minus credit;
   stop is loss control not a guarantee; worst day near $1,200; scalper never holds overnight.)
9. Is there a daily loss limit? (Seller: no dedicated one, structural brakes only. Scalper: bounded
   by 2 x $250 before exits; optional halt re-enabled via env.)
10. What does the 0DTE scalper actually do? (Full mechanism from the facts above.)
11. How do I know what it did on any given day? (Dashboard at 127.0.0.1:8765 read-only;
    data/decisions.jsonl and data/structures.jsonl for the seller; data/scalp_decisions.jsonl and
    data/scalp_positions.jsonl for the scalper.)
12. What stops a bug from doing something catastrophic? (Rails hard-coded in Python, env can only
    tighten; broker client refuses non-paper; one locked entry window a day; exit sweep reconciles
    the registry against live positions and alerts on anything vanished; scalper force-flattens at
    15:50 ET and re-adopts orphaned positions.)

## Style rules (strict)
- Plain, confident English. No em dashes or long dashes anywhere; use commas, periods,
  parentheses. No marketing fluff, no "delve", no "seamless", no "cutting-edge".
- Numbers must match the facts above exactly.
- Footer on every page: "OptionsAgent explainer, built from the code and live account, Aug 28 2026"
  plus "page N of 8".
- Lean into the design: strong hierarchy, generous spacing where possible, the two engines must be
  visually distinct (suggested: blue family for the seller, green family for the scalper), and the
  whole doc must look like one system with the dark screenshots.

When done, reply with a one-paragraph summary of your design decisions. Again: create ONLY
explainer_gemini.html. Nothing else.
