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
from dataclasses import dataclass
from typing import Any

from harness.contracts import OptionQuote
from harness.env import env
from harness.occ import parse_occ_symbol

ORDER_PREFIX = "oa-"


def _status_str(status: Any) -> str:
    """alpaca-py order statuses are enums whose str() is 'OrderStatus.FILLED';
    callers must compare against the plain lowercase value ('filled'), so
    normalize at the single point every status passes through."""
    return str(getattr(status, "value", status)).lower()


@dataclass(frozen=True)
class PaperClient:
    """Single import-point for the broker. Paper-only by construction."""

    key_id: str
    secret_key: str

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
                "asset_class": str(p.asset_class),
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
        from datetime import date

        from alpaca.data.requests import OptionChainRequest

        client = self._option_historical_client()
        req = OptionChainRequest(underlying_symbol=underlying)
        chain = client.get_option_chain(req)
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

    # -- order submission ------------------------------------------------

    def submit_single_leg_order(
        self, *, option_symbol: str, side: str, qty: int, limit_price: float, decision_id: str
    ) -> dict[str, Any]:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest

        if side not in ("buy", "sell"):
            raise ValueError(f"side must be buy or sell, got {side!r}")
        client_order_id = f"{ORDER_PREFIX}{decision_id}-{uuid.uuid4().hex[:8]}"
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
        return {"id": str(order.id), "status": _status_str(order.status), "filled_qty": float(order.filled_qty or 0)}

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
