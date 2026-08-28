"""Alpaca PAPER wiring for OptionsAgent.

HARD RULE: paper=True is enforced at construction; make_client() refuses to
build unless ALPACA_PAPER=true. Mirrors DeterministicAgent's alpaca_glue.py.
The real alpaca-py client is constructed lazily so the rest of the harness
imports/tests without the dependency installed.

Order client_order_id prefix is `oa-` so this bot's orders never collide with
the sibling bots' (`da-`, `sa-`, etc.).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from harness.contracts import OptionQuote
from harness.env import env
from harness.occ import parse_occ_symbol

ORDER_PREFIX = "oa-"


def _f(val: Any) -> float | None:
    """Optional numeric -> float, None-safe (alpaca-py fields are Optional and
    getattr defaults never fire on present-but-None — the fleet's known
    float(None) gotcha)."""
    return None if val is None else float(val)


def _status_str(status: Any) -> str:
    """alpaca-py order statuses are enums whose str() is 'OrderStatus.FILLED';
    callers must compare against the plain lowercase value ('filled'), so
    normalize at the single point every status passes through."""
    return str(getattr(status, "value", status)).lower()


def _adapt_chain(chain: dict, underlying: str) -> list[OptionQuote]:
    """Adapt an alpaca-py chain snapshot dict into OptionQuote rows.

    2026-07-08 incident: the CCL chain included CCL1260821P00022500 — an
    ADJUSTED contract (root CCL1, renamed after a corporate action, deliverable
    no longer 100 plain shares). Alpaca's market-data chain returns adjusted
    contracts, but the trading API rejects orders on them
    ({"code":42210000,"message":"contract ... is not active"}), which crashed
    run_cycle. The selector had actually favored it because adjusted contracts'
    quotes look mispriced against their nominal strike. So: drop every row
    whose OCC root differs from the requested underlying — standard contracts
    only, by construction."""
    from datetime import date

    quotes: list[OptionQuote] = []
    today = date.today()
    for symbol, snap in chain.items():
        greeks = getattr(snap, "greeks", None)
        quote = getattr(snap, "latest_quote", None)
        if greeks is None or quote is None or greeks.delta is None:
            continue
        try:
            parts = parse_occ_symbol(symbol)
        except ValueError:
            continue  # malformed/non-OCC symbol -> skip, never guess
        if parts.underlying != underlying.strip().upper():
            continue  # adjusted contract (e.g. CCL1) -> not tradable, skip
        quotes.append(
            OptionQuote(
                symbol=symbol,
                underlying=underlying,
                right=parts.right,
                strike=parts.strike,
                dte=(parts.expiry - today).days,
                delta=float(greeks.delta),
                bid=float(quote.bid_price or 0.0),
                ask=float(quote.ask_price or 0.0),
            )
        )
    return quotes


@dataclass(frozen=True)
class PaperClient:
    """Single import-point for the broker. Paper-only by construction."""

    key_id: str
    secret_key: str
    _public_data: Any = field(default=None, init=False, repr=False, compare=False)

    def _public_market_data(self):
        """Return the optional read-only Public data sidecar, if enabled."""
        if (env("OA_OPTIONS_DATA_PROVIDER", "alpaca") or "alpaca").lower() != "public":
            return None
        if self._public_data is None:
            from harness.public_marketdata import PublicMarketDataClient

            object.__setattr__(self, "_public_data", PublicMarketDataClient.from_env())
        return self._public_data

    def _data_credentials(self) -> tuple[str, str]:
        """Credentials for STOCK market-data REST calls (bars / latest trade).

        The trading key's user may lack real-time SIP entitlement (the local
        reactivation keys 403 on recent SIP data, leaving bars 15 min stale —
        fatal for the 0DTE scalper). OA_DATA_KEY_ID / OA_DATA_SECRET_KEY let an
        entitled READ key do the looking while orders stay on this account's
        own paper key (same eyes/hands split as ~/ManualTrading). Defaults to
        the trading pair, so absence changes nothing."""
        key = env("OA_DATA_KEY_ID", "") or self.key_id
        secret = env("OA_DATA_SECRET_KEY", "") or self.secret_key
        return key, secret

    def _ensure_paper(self) -> None:
        if (env("ALPACA_PAPER", "true") or "true").lower() != "true":
            raise RuntimeError("ALPACA_PAPER is not 'true'. Refusing to construct any client.")

    def _trading_client(self):
        self._ensure_paper()
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("alpaca-py not installed. pip install alpaca-py before live calls.") from e
        return TradingClient(self.key_id, self.secret_key, paper=True)

    def _option_historical_client(self):
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("alpaca-py not installed. pip install alpaca-py before live calls.") from e
        return OptionHistoricalDataClient(self.key_id, self.secret_key)

    # -- account / positions ------------------------------------------------

    def account_state(self) -> dict[str, Any]:
        acct = self._trading_client().get_account()
        # options_buying_power exists on TradeAccount but is Optional and can
        # come back None (e.g. options level not enabled) — a getattr default
        # never fires for that, so handle None explicitly. Fail SAFE: treating
        # missing buying power as 0 makes the margin rail veto everything
        # rather than trade blind.
        raw_obp = getattr(acct, "options_buying_power", None)
        if raw_obp is None:
            raw_obp = acct.buying_power
        return {
            "equity_usd": float(acct.equity),
            "available_options_buying_power_usd": float(raw_obp) if raw_obp is not None else 0.0,
        }

    def list_positions(self) -> list[dict[str, Any]]:
        """Returns ALL positions (equities and options) — the equity legs
        matter too, e.g. to read a covered call's cost basis."""
        positions = self._trading_client().get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "asset_class": _status_str(p.asset_class),
                "cost_basis": float(p.cost_basis),
                "market_value": float(p.market_value),
            }
            for p in positions
        ]

    # -- option chain snapshot ------------------------------------------------

    def option_chain(self, underlying: str) -> list[OptionQuote]:
        """Fetch a chain snapshot and adapt it into OptionQuote rows. Kept as
        a thin adapter so harness/contracts.py stays broker-agnostic and
        testable without network access.

        alpaca-py's OptionsSnapshot carries NO strike/expiry/right fields
        (verified on 0.43.4: only symbol/latest_trade/latest_quote/IV/greeks)
        — all three must be parsed from the OCC symbol via harness/occ.py."""
        public = self._public_market_data()
        if public is not None:
            return public.option_chain(underlying)

        from alpaca.data.requests import OptionChainRequest

        client = self._option_historical_client()
        req = OptionChainRequest(underlying_symbol=underlying)
        chain = client.get_option_chain(req)
        return _adapt_chain(chain, underlying)

    def option_chain_0dte(
        self, underlying: str, *, right: str, spot: float, strike_pct: float = 0.03
    ) -> list[dict]:
        """Focused 0DTE chain fetch for the ORB scalper: today's-expiry contracts
        of one right (call/put) within +/- strike_pct of spot. Filtered SERVER-SIDE
        (expiration_date=today, type, strike range) so it's light + fast, and it
        keeps rows even when greeks/IV are None (0DTE greeks come back None when the
        indicative feed hasn't computed them — the probe confirmed this, and the lean
        option_chain() would drop those rows). Returns [{symbol, strike, right, bid,
        ask, mid, spread_pct}, ...]. Empty list on error or nothing listed."""
        public = self._public_market_data()
        if public is not None:
            return public.option_chain_0dte(underlying, right=right, spot=spot, strike_pct=strike_pct)

        from datetime import date

        from alpaca.data.requests import OptionChainRequest
        from alpaca.trading.enums import ContractType

        if right not in ("call", "put"):
            raise ValueError(f"right must be call or put, got {right!r}")
        today = date.today()
        try:
            client = self._option_historical_client()
            req = OptionChainRequest(
                underlying_symbol=underlying,
                expiration_date=today,
                strike_price_gte=spot * (1.0 - strike_pct),
                strike_price_lte=spot * (1.0 + strike_pct),
                type=ContractType.CALL if right == "call" else ContractType.PUT,
            )
            chain = client.get_option_chain(req)
        except Exception:
            return []
        rows: list[dict] = []
        for symbol, snap in chain.items():
            try:
                parts = parse_occ_symbol(symbol)
            except ValueError:
                continue
            if parts.underlying != underlying.strip().upper():
                continue  # adjusted contract (e.g. SPY7) -> not tradable
            if parts.right != right or parts.expiry != today:
                continue
            quote = getattr(snap, "latest_quote", None)
            bid = _f(getattr(quote, "bid_price", None)) if quote is not None else None
            ask = _f(getattr(quote, "ask_price", None)) if quote is not None else None
            if not bid or not ask or bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2.0
            rows.append(
                {
                    "symbol": symbol,
                    "strike": parts.strike,
                    "right": right,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "spread_pct": (ask - bid) / mid if mid > 0 else 1.0,
                }
            )
        return rows

    def option_chain_raw(self, underlying: str) -> list[dict]:
        """Full chain snapshot with EVERYTHING Alpaca sends (quotes with
        sizes, last trade, implied volatility, all greeks) — for
        harness/chain_capture.py's daily persistence. option_chain() above
        stays the lean trading adapter; this one exists because the dropped
        fields (IV, gamma/theta/vega) are exactly what a future replay
        harness / IV-rank signal needs and cannot be recovered later."""
        public = self._public_market_data()
        if public is not None:
            return public.option_chain_raw(underlying)

        from alpaca.data.requests import OptionChainRequest

        client = self._option_historical_client()
        req = OptionChainRequest(underlying_symbol=underlying)
        chain = client.get_option_chain(req)
        rows: list[dict] = []
        for symbol, snap in chain.items():
            row: dict = {"symbol": symbol, "underlying": underlying}
            try:
                parts = parse_occ_symbol(symbol)
                row.update(strike=parts.strike, expiry=parts.expiry.isoformat(), right=parts.right)
            except ValueError:
                pass  # keep the raw row anyway; the replayer can re-parse
            quote = getattr(snap, "latest_quote", None)
            if quote is not None:
                row.update(
                    bid=_f(quote.bid_price), ask=_f(quote.ask_price),
                    bid_size=_f(quote.bid_size), ask_size=_f(quote.ask_size),
                    quote_ts=str(getattr(quote, "timestamp", None)),
                )
            trade = getattr(snap, "latest_trade", None)
            if trade is not None:
                row.update(
                    last_price=_f(trade.price), last_size=_f(trade.size),
                    trade_ts=str(getattr(trade, "timestamp", None)),
                )
            row["implied_volatility"] = _f(getattr(snap, "implied_volatility", None))
            greeks = getattr(snap, "greeks", None)
            if greeks is not None:
                row.update(
                    delta=_f(greeks.delta), gamma=_f(greeks.gamma), theta=_f(greeks.theta),
                    vega=_f(greeks.vega), rho=_f(getattr(greeks, "rho", None)),
                )
            rows.append(row)
        return rows

    # -- order submission ------------------------------------------------

    def submit_single_leg_order(
        self, *, option_symbol: str, side: str, qty: int, limit_price: float, decision_id: str,
        prefix: str = ORDER_PREFIX,
    ) -> dict[str, Any]:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest

        if side not in ("buy", "sell"):
            raise ValueError(f"side must be buy or sell, got {side!r}")
        client_order_id = f"{prefix}{decision_id}-{uuid.uuid4().hex[:8]}"
        req = LimitOrderRequest(
            symbol=option_symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
            client_order_id=client_order_id,
        )
        order = self._trading_client().submit_order(req)
        return {"id": str(order.id), "client_order_id": client_order_id, "status": _status_str(order.status)}

    def submit_equity_order(
        self, *, symbol: str, side: str, qty: int, decision_id: str
    ) -> dict[str, Any]:
        """Used for the covered-call share leg — Alpaca disallows an equity
        leg inside an mleg order, so shares are always a separate order
        submitted (and confirmed filled) before the call leg."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        client_order_id = f"{ORDER_PREFIX}{decision_id}-{uuid.uuid4().hex[:8]}"
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        order = self._trading_client().submit_order(req)
        return {"id": str(order.id), "client_order_id": client_order_id, "status": _status_str(order.status)}

    def submit_mleg_order(
        self,
        *,
        legs: list[dict[str, Any]],  # [{"symbol": str, "side": "buy"|"sell", "ratio_qty": int}]
        qty: int,
        limit_price: float,
        decision_id: str,
    ) -> dict[str, Any]:
        """Multi-leg combo order (spreads, long straddles). Always LIMIT —
        research: sequential single legs lose midpoint pricing and eat
        slippage between fills. Alpaca's mleg net-price convention: positive
        limit_price = net debit, negative = net credit."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

        if not legs or len(legs) < 2:
            raise ValueError("mleg order needs at least 2 legs")
        leg_requests = [
            OptionLegRequest(
                symbol=leg["symbol"],
                side=OrderSide.BUY if leg["side"] == "buy" else OrderSide.SELL,
                ratio_qty=leg["ratio_qty"],
            )
            for leg in legs
        ]
        client_order_id = f"{ORDER_PREFIX}{decision_id}-{uuid.uuid4().hex[:8]}"
        req = LimitOrderRequest(
            qty=qty,
            order_class=OrderClass.MLEG,
            legs=leg_requests,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
            client_order_id=client_order_id,
        )
        order = self._trading_client().submit_order(req)
        return {"id": str(order.id), "client_order_id": client_order_id, "status": _status_str(order.status)}

    def option_quotes(self, option_symbols: list[str]) -> dict[str, dict[str, float]]:
        """Latest bid/ask per OCC symbol — the exit sweep's mark source."""
        public = self._public_market_data()
        if public is not None:
            return public.option_quotes(option_symbols)

        from alpaca.data.requests import OptionLatestQuoteRequest

        if not option_symbols:
            return {}
        client = self._option_historical_client()
        req = OptionLatestQuoteRequest(symbol_or_symbols=option_symbols)
        quotes = client.get_option_latest_quote(req)
        return {
            sym: {"bid": float(q.bid_price or 0.0), "ask": float(q.ask_price or 0.0)}
            for sym, q in quotes.items()
        }

    def get_order(self, order_id: str) -> dict[str, Any]:
        order = self._trading_client().get_order_by_id(order_id)
        return {
            "id": str(order.id),
            "status": _status_str(order.status),
            "filled_qty": float(order.filled_qty or 0),
            "filled_avg_price": _f(getattr(order, "filled_avg_price", None)),
        }

    # -- underlying stock data (proposer market context) -------------------

    def stock_daily_bars(
        self, symbols: list[str], *, lookback_days: int = 40
    ) -> dict[str, list[dict[str, float]]]:
        """Recent daily bars per symbol, for the proposer's market context.

        Uses the free IEX feed explicitly so a paper account with no
        market-data subscription doesn't 403 on recent SIP data. Returns
        {symbol: [{"c": close, "v": volume}, ...]} oldest-first; a symbol with
        no data is simply absent from the dict (the caller fails open per
        ticker). IEX volume is a fraction of consolidated volume, so treat the
        volume figure as relative-only, never as true share count."""
        from datetime import datetime, timedelta, timezone

        from alpaca.data.enums import DataFeed
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        if not symbols:
            return {}
        client = StockHistoricalDataClient(self.key_id, self.secret_key)
        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
            feed=DataFeed.IEX,
        )
        bars = client.get_stock_bars(req)
        data = getattr(bars, "data", {}) or {}
        out: dict[str, list[dict[str, float]]] = {}
        for sym, blist in data.items():
            out[sym] = [
                {"c": float(b.close), "v": float(b.volume or 0.0)}
                for b in blist
                if b.close is not None
            ]
        return out

    def stock_minute_bars(
        self, symbol: str, *, lookback_minutes: int = 60, feed: str = "sip"
    ) -> list[dict[str, Any]]:
        """Recent 1-minute bars for ONE symbol, for the 0DTE ORB scalper's
        intraday signals. Returns [{"ts_utc", "et_date", "et_time", "o","h",
        "l","c","v"}, ...] oldest-first, timestamps converted to America/New_York
        (Alpaca sends UTC; the opening-range / session filters need ET — the
        fleet's known SIP-bar gotcha). feed="sip" is verified entitled on this
        login (probe 2026-07-10); "iex" is the degraded fallback. Empty list on
        any error or no data (caller fails open, never trades blind)."""
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo

        from alpaca.data.enums import DataFeed
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        et = ZoneInfo("America/New_York")
        data_feed = DataFeed.IEX if str(feed).lower() == "iex" else DataFeed.SIP
        client = StockHistoricalDataClient(*self._data_credentials())
        start = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            feed=data_feed,
        )
        try:
            bars = client.get_stock_bars(req)
        except Exception:
            return []
        blist = (getattr(bars, "data", {}) or {}).get(symbol, [])
        out: list[dict[str, Any]] = []
        for b in blist:
            if b.close is None:
                continue
            ts = b.timestamp  # tz-aware UTC
            ts_et = ts.astimezone(et)
            out.append(
                {
                    "ts_utc": ts.isoformat(),
                    "et_date": ts_et.strftime("%Y-%m-%d"),
                    "et_time": ts_et.strftime("%H:%M"),
                    "o": float(b.open),
                    "h": float(b.high),
                    "l": float(b.low),
                    "c": float(b.close),
                    "v": float(b.volume or 0.0),
                }
            )
        return out

    def stock_latest_price(self, symbol: str, *, feed: str = "sip") -> float | None:
        """Live last-trade price for the underlying (spot for ATM strike
        selection). None on any failure (caller falls back to the last bar's
        close)."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest

        data_feed = DataFeed.IEX if str(feed).lower() == "iex" else DataFeed.SIP
        client = StockHistoricalDataClient(*self._data_credentials())
        try:
            req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=data_feed)
            tr = client.get_stock_latest_trade(req)
            t = tr.get(symbol)
            return float(t.price) if t is not None and t.price is not None else None
        except Exception:
            return None

    def cancel_order(self, order_id: str) -> None:
        """Cancel a working order (e.g. a scalp entry limit that never filled)."""
        try:
            self._trading_client().cancel_order_by_id(order_id)
        except Exception:
            pass

    def market_is_open(self) -> bool:
        """Broker market clock — the cron scripts' holiday/weekend guard.
        The cron time windows only know the ET wall clock, not the NYSE
        calendar; this is the authoritative check."""
        clock = self._trading_client().get_clock()
        return bool(clock.is_open)


def make_client() -> PaperClient:
    from harness.env import require_env

    key_id = require_env("ALPACA_API_KEY")
    secret_key = require_env("ALPACA_SECRET_KEY")
    client = PaperClient(key_id=key_id, secret_key=secret_key)
    client._ensure_paper()  # fail fast at construction, not on first call
    return client
