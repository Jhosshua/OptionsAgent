# Wingspan

Current operating guide, updated 2026-09-09.

Wingspan is a paper-trading bot with two engines: defined-risk options credit spreads
and a deterministic SPY/QQQ stock scalper. DeepSeek proposes options ideas; Python
selects contracts, enforces risk limits and handles all orders and exits.

| Location | Name or link |
|---|---|
| Mac folder | `/Users/mo/wingspan` |
| Railway project and service | `wingspan` |
| Discord | [#wingspan](https://discord.com/channels/1507539055364018326/1544462423111761990) |
| Dashboard | https://optionsagent-production.up.railway.app |
| GitHub repository | https://github.com/Jhosshua/OptionsAgent |

The existing dashboard hostname and GitHub repository URL remain valid. Deployment
is manual from this folder. Railway variables are authoritative. Local trading
schedules remain disabled; do not run another trader against this paper account.

## Engines and limits

- Credit spreads: 30–45 DTE, short absolute delta 0.15–0.30, width at most $2,
  conviction at least 0.60. Production uses `OA_CREDIT_SPREAD_GATE=research_rules`
  and `OA_MAX_POSITION_USD=3000` together. Six option-leg slots accommodate three
  two-leg spreads. This is a portfolio limit, not a broker error.
- Exits: 50% profit target, 2× opening credit stop confirmed on two sweeps after
  10:00 ET, and mandatory closing at 21 DTE. Profit-taking day limits remain
  working and tracked between sweeps. Stops and time exits retain priority.
- Stock scalper: morning reversal on SPY/QQQ and QQQ gap continuation. Default
  $20,000 per trade, two trades/day, 0.7% stop, 120-minute holding limit,
  $300 daily loss halt and 15:50 ET flatten.
- Proposals use the DeepSeek API. Execution uses the official Alpaca CLI on
  Railway. Public.com supplies read-only options data; AlpacaRelay supplies stocks.
- `ALPACA_PAPER=true` is enforced. The retired 0DTE option scalper stays disabled.

## Discord V2

Each update is one Components V2 card with an **Open dashboard** button. Options
opens show both strikes, spread count and total credit. Capacity notices explain
option legs versus spreads. Working profit orders generate a pending update rather
than repeated error messages. Completed spread exits use broker fill prices for
P&L before fees; a missing or ambiguous fill never becomes a booked profit.

## Development and deployment

```bash
cd /Users/mo/wingspan
python3 -m pytest -q tests
railway up --service wingspan
```

Read [SETUP.md](SETUP.md) for volume migration and verification,
[CLAUDE.md](CLAUDE.md) for engineering constraints,
[ARCHITECTURE.md](ARCHITECTURE.md) for code responsibilities and
[MEMORY.md](MEMORY.md) for current decisions. Dated research files explain the
research basis; they are not deployment instructions or performance forecasts.
