# Public.com API vs Alpaca: what each feed gives us

Researched 2026-09-15 evening (after the close). Live probes ran against
`https://api.public.com` with the wingspan `PUBLIC_API_SECRET` and against the
AlpacaRelay (`OA_DATA_URL`, SIP) plus the wingspan paper key. Docs:
https://public.com/api/docs and https://docs.alpaca.markets.

## How wingspan uses Public today (`harness/public_marketdata.py`)

Read-only. Secret -> 60-min bearer token -> pick the BROKERAGE account ->
`option-expirations` (filtered to 30-45 DTE) -> one `option-chain` call per
expiry -> batch `quotes` (50 per call) to refresh bid/ask. Chain Greeks are the
fallback because the quotes endpoint returns `optionDetails: null` for options
(confirmed live). No order methods exist in the adapter. Alpaca paper places
every order.

Public accounts seen: `2OG75006` HIGH_YIELD (no trading) and `5OI20801`
BROKERAGE margin, `optionsLevel: NONE`. Market data works from either account
ID. The BROKERAGE account has no options level, so Public could not execute a
spread even if we wanted it to.

## What Public returns (verified live)

| Endpoint | Works | Notable fields |
|---|---|---|
| `POST /userapigateway/marketdata/{acct}/quotes` | yes | last, bid/ask + sizes, per-field timestamps, volume, openInterest, previousClose, oneDayChange. Types EQUITY, OPTION, CRYPTO, INDEX. |
| `POST .../option-expirations` | yes | every listed expiry, incl. SPX/SPXW index options |
| `POST .../option-chain` | yes | one expiry per call. Per contract: bid/ask/last/sizes/timestamps, **volume, openInterest**, Greeks (delta gamma theta vega rho) + IV, midPrice |
| `GET /userapigateway/option-details/{acct}/greeks?osiSymbols=` | yes | up to 250 contracts per call |
| `GET /userapigateway/historicdata/{EQUITY,OPTION,INDEX,CRYPTO}/{sym}/{period}[/{agg}]` | yes | OHLCV split into preMarket / regularMarket / afterMarket, overnight sessions with `tradingSessionToggle=ALL_SESSIONS` |
| `GET /userapigateway/trading/account`, `/{acct}/portfolio/v2`, `/{acct}/history` | yes | account, positions, orders, transactions |
| `GET /userapigateway/trading/instruments[/{sym}/{type}]` | yes | full universe (22 MB, includes bonds), per-symbol: shortable, hard-to-borrow rate, option tick increments, exchange |
| strategy-quote (multi-leg) | 404 on the path I guessed | docs list it; find the exact path before relying on it |

Indexes that quote: SPX, XSP, NDX, VIX. RUT returns UNKNOWN, DJI is rejected.
Crypto: BTC, ETH, SOL quote with bid/ask.

### Bars: which period + aggregation combos are legal

Public returns 400 for anything not in this table
(`Period YEAR is not compatible with aggregation ONE_MINUTE`).

| Period | Legal aggregations | Bars returned for SPY |
|---|---|---|
| DAY | 1m 5m 15m 30m 1h | 391 one-minute regular-session bars, plus 330 pre, 92 after, 240 overnight |
| WEEK | 5m 15m 30m 1h 1d | 395 five-minute bars |
| MONTH | 1h 1d 1w | 168 hourly |
| QUARTER, HALF_YEAR, YEAR, YTD | 1d 1w 1M | 252 daily for YEAR |
| TEN_YEARS | 1w 1M | 522 weekly |
| ALL | 1M | 405 monthly back to 1993 |
| FIVE_YEAR | none worked | every combo 400 |

So the deepest intraday history on Public is ONE week of 5-minute bars or ONE
day of 1-minute bars. Option contracts get the same treatment (a SPY Oct call
returned 5m bars for the week and daily bars for the quarter).

### Rate limit and freshness

Public docs: 10 requests/second (doubled from 5 on 2026-02-02). 30 back-to-back
quote calls all returned 200 with no rate-limit headers.

Freshness is UNVERIFIED for the regular session. After the close, Public's
SPY `last` matched the SIP trade tape within seconds, but its bid/ask
timestamps sat 15 minutes behind its own last-trade timestamp (21:34 last vs
21:19 bid) and the prices did not match the consolidated SIP quote at that
stamp (Public 757.80 x 200 / 757.93 x 100 vs SIP 757.96 x 1000 / 758.03 x 40).
That could be a single-venue quote, a delayed NBBO, or just after-hours noise.
Run `research_public_freshness_probe.py` during market hours to settle it
before trusting Public bid/ask for fills or stop logic.

## What Alpaca gives that Public does not

- **Streaming.** Websocket trades, quotes, bars, updated bars, trading
  statuses, LULD halts, news. Public has no websocket at all (not in docs,
  not in the changelog). Every Public read is a poll.
- **Deep intraday history.** SIP 1-minute bars back to 2016 (probe pulled
  2017-01-03 1Min bars). Public: one day of 1-minute, one week of 5-minute.
- **Option bars at any timeframe** (1Min to 1Month, 100 symbols per call) and
  option chain snapshots with latestTrade + latestQuote + Greeks + daily bar.
- **News** (`/v1beta1/news`), **screener** (movers, most-actives), corporate
  actions, snapshots, historical trades and quotes tick by tick.
- **Paper trading.** Public has no sandbox; every order is real money.
- **Bracket / OCO on options** via the trading API. Public added BRACKET/OCO/OTO
  classes on 2026-09-10 but the BROKERAGE account here has no options level.

## What Public gives that Alpaca does not

- **Open interest and volume on every contract in the chain.** Alpaca's option
  chain snapshot has no open interest field. This is the single most useful
  extra for a credit-spread seller (liquidity filter).
- **Index options and index quotes.** SPX, SPXW, XSP, NDX chains with Greeks.
  Alpaca does not carry index options or index levels.
- **Session-split bars** (pre, regular, after, overnight) with `ALL_SESSIONS`
  covering the 24/5 overnight ATS session.
- **Per-symbol borrow data**: `shortingAvailability` and
  `hardToBorrowPercentageRate`, plus option tick increments.
- **Bonds and treasuries** (search, details, quotes with markups).
- **Free.** Alpaca's comparable feed is Algo Trader Plus at $99/month.

## Important finding about the wingspan Alpaca key

The wingspan paper key (`PA371G5THNUO`) is on Alpaca's Basic plan:
`GET /v2/stocks/SPY/quotes/latest?feed=sip` -> 403 "subscription does not
permit querying recent SIP data", and the OPRA option snapshot -> 403 "OPRA
agreement is not signed". The $99 Algo Trader Plus subscription is attached to
a different Alpaca account (the ManualTrading data key, see the relay). Wingspan
gets SIP data only because it reads stock bars through AlpacaRelay. Any direct
Alpaca options call from wingspan would be the free indicative feed.

## Public CLI (`pipx install publicdotcom-cli`, then `public auth login`)

Same endpoints as above, nothing extra: `accounts`, `portfolio show`,
`history list`, `instruments get`, `instruments bonds`, `market quotes`,
`market option-expirations`, `market option-chain SYMBOL DATE`,
`options greeks`, `options strategy-quote --file`, `historicdata bars TYPE SYM
PERIOD --aggregation`, `taxlots`, `order preflight-single|place|replace|get|cancel`.
`--json` for machine output. No watch/stream, no paper mode. Env vars
`PUBLIC_PERSONAL_SECRET`, `PUBLIC_ACCOUNT_ID`, `PUBLIC_ACCESS_TOKEN`.

## Bottom line for wingspan

Keep both. Alpaca (via the relay) for streaming, deep history, and execution.
Public for the option chain with open interest, Greeks, and index options at
zero cost. Do not use Public bid/ask for anything time-sensitive until the
market-hours freshness probe passes.
