"""Read-only Public.com market-data adapter.

Public's Individual API is used only for market data here. Alpaca remains the
sole account, position, and order broker. The adapter intentionally has no
order methods and fails closed on malformed quote fields.

Public API flow:
  personal secret -> short-lived access token -> account ID -> option chain
  -> per-contract quotes/Greeks.

The chain endpoint supplies contract metadata, bid/ask, and (when available)
Greeks. The quote endpoint supplies the freshest bid/ask and may omit
``optionDetails``/Greeks, so chain Greeks are retained as the fallback. Raw
snapshots keep the chain endpoint's quote fields and do not fan out into a
second quote request for every contract.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo

import requests

from harness.contracts import OptionQuote
from harness.env import env
from harness.occ import parse_occ_symbol

BASE_URL = "https://api.public.com"
EASTERN = ZoneInfo("America/New_York")


class PublicMarketDataError(RuntimeError):
    """A safe, non-secret-bearing error from the Public market-data API."""


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date_today() -> date:
    return datetime.now(EASTERN).date()


def _greeks(raw: Any) -> dict[str, float]:
    """Extract the numeric Greeks Public includes in optionDetails."""
    if not isinstance(raw, dict):
        return {}
    details = raw.get("optionDetails") or {}
    values = details.get("greeks") if isinstance(details, dict) else None
    if not isinstance(values, dict):
        return {}
    names = {
        "delta": "delta",
        "gamma": "gamma",
        "theta": "theta",
        "vega": "vega",
        "rho": "rho",
        "impliedVolatility": "implied_volatility",
    }
    parsed: dict[str, float] = {}
    for source, target in names.items():
        value = _float(values.get(source))
        if value is not None:
            parsed[target] = value
    return parsed


class PublicMarketDataClient:
    """Small authenticated REST client for Public option market data."""

    def __init__(
        self,
        secret: str,
        *,
        account_id: str | None = None,
        dte_min: int = 30,
        dte_max: int = 45,
        quote_batch_size: int = 50,
        timeout_seconds: float = 10.0,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
    ) -> None:
        if not secret:
            raise ValueError("Public API secret is required")
        if dte_min < 0 or dte_max < dte_min:
            raise ValueError("Public options DTE range is invalid")
        if quote_batch_size < 1:
            raise ValueError("Public quote batch size must be positive")
        self.secret = secret
        self.account_id = account_id
        self.dte_min = dte_min
        self.dte_max = dte_max
        self.quote_batch_size = quote_batch_size
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._chain_cache: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def from_env(cls) -> "PublicMarketDataClient":
        secret = env("PUBLIC_API_SECRET") or env("PUBLIC_API_SECRET_KEY")
        if not secret:
            raise RuntimeError(
                "OA_OPTIONS_DATA_PROVIDER=public requires PUBLIC_API_SECRET "
                "(or PUBLIC_API_SECRET_KEY)"
            )
        return cls(
            secret,
            account_id=env("PUBLIC_ACCOUNT_ID"),
            dte_min=int(env("PUBLIC_OPTIONS_DTE_MIN", "30")),
            dte_max=int(env("PUBLIC_OPTIONS_DTE_MAX", "45")),
            quote_batch_size=int(env("PUBLIC_QUOTE_BATCH_SIZE", "50")),
            timeout_seconds=float(env("PUBLIC_API_TIMEOUT_SECONDS", "10")),
        )

    def _token(self, *, refresh: bool = False) -> str:
        if self._access_token and not refresh:
            return self._access_token
        try:
            response = self.session.post(
                f"{self.base_url}/userapiauthservice/personal/access-tokens",
                json={"validityInMinutes": 60, "secret": self.secret},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            token = response.json().get("accessToken")
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise PublicMarketDataError(f"Public token exchange failed: {exc}") from exc
        if not token:
            raise PublicMarketDataError("Public token exchange returned no access token")
        self._access_token = str(token)
        return self._access_token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request_headers = dict(kwargs.pop("headers", {}) or {})
        for attempt in range(2):
            headers = dict(request_headers)
            headers["Authorization"] = f"Bearer {self._token(refresh=attempt == 1)}"
            headers.setdefault("Content-Type", "application/json")
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.status_code == 401 and attempt == 0:
                    self._access_token = None
                    continue
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError, AttributeError) as exc:
                raise PublicMarketDataError(f"Public {method} {path} failed: {exc}") from exc
            if not isinstance(payload, dict):
                raise PublicMarketDataError(f"Public {method} {path} returned non-object JSON")
            return payload
        raise PublicMarketDataError(f"Public {method} {path} unauthorized after token refresh")

    def _account(self) -> str:
        if self.account_id:
            return self.account_id
        payload = self._request("GET", "/userapigateway/trading/account")
        accounts = payload.get("accounts") or []
        account = next((row for row in accounts if row.get("accountType") == "BROKERAGE"), None)
        if account is None and accounts:
            account = accounts[0]
        if not isinstance(account, dict) or not account.get("accountId"):
            raise PublicMarketDataError("Public account lookup returned no usable accountId")
        self.account_id = str(account["accountId"])
        return self.account_id

    def _expiration_dates(self, underlying: str) -> list[date]:
        payload = self._request(
            "POST",
            f"/userapigateway/marketdata/{self._account()}/option-expirations",
            json={"instrument": {"symbol": underlying.upper(), "type": "EQUITY"}},
        )
        today = _date_today()
        low = today + timedelta(days=self.dte_min)
        high = today + timedelta(days=self.dte_max)
        dates = []
        for raw in payload.get("expirations") or []:
            try:
                expiry = date.fromisoformat(str(raw))
            except ValueError:
                continue
            if low <= expiry <= high:
                dates.append(expiry)
        return sorted(set(dates))

    def _chain_rows(self, underlying: str) -> list[dict[str, Any]]:
        symbol = underlying.strip().upper()
        if symbol in self._chain_cache:
            return list(self._chain_cache[symbol])
        rows: list[dict[str, Any]] = []
        for expiry in self._expiration_dates(symbol):
            payload = self._request(
                "POST",
                f"/userapigateway/marketdata/{self._account()}/option-chain",
                json={
                    "instrument": {"symbol": symbol, "type": "EQUITY"},
                    "expirationDate": expiry.isoformat(),
                },
            )
            for side, right in (("calls", "call"), ("puts", "put")):
                for raw in payload.get(side) or []:
                    if not isinstance(raw, dict):
                        continue
                    instrument = raw.get("instrument") or {}
                    option_symbol = instrument.get("symbol")
                    if not option_symbol:
                        continue
                    try:
                        parts = parse_occ_symbol(option_symbol)
                    except ValueError:
                        continue
                    if parts.underlying != symbol or parts.right != right or parts.expiry != expiry:
                        continue
                    bid = _float(raw.get("bid"))
                    ask = _float(raw.get("ask"))
                    row = {
                        "symbol": option_symbol,
                        "underlying": symbol,
                        "right": right,
                        "strike": parts.strike,
                        "expiry": expiry.isoformat(),
                        "dte": (expiry - _date_today()).days,
                        "bid": bid,
                        "ask": ask,
                        "last": _float(raw.get("last")),
                        "bid_size": _float(raw.get("bidSize")),
                        "ask_size": _float(raw.get("askSize")),
                        "quote_ts": raw.get("bidTimestamp") or raw.get("lastTimestamp"),
                    }
                    # Public's quote endpoint currently returns bid/ask for
                    # options but often omits optionDetails. Keep the chain
                    # Greeks so the selector still has the delta it requires.
                    row.update(_greeks(raw))
                    rows.append(row)
        self._chain_cache[symbol] = rows
        return list(rows)

    def _quote_batches(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        quotes: dict[str, dict[str, Any]] = {}
        account = self._account()
        for start in range(0, len(symbols), self.quote_batch_size):
            batch = symbols[start : start + self.quote_batch_size]
            payload = self._request(
                "POST",
                f"/userapigateway/marketdata/{account}/quotes",
                json={"instruments": [{"symbol": symbol, "type": "OPTION"} for symbol in batch]},
            )
            for raw in payload.get("quotes") or []:
                if not isinstance(raw, dict):
                    continue
                instrument = raw.get("instrument") or {}
                symbol = instrument.get("symbol")
                if symbol:
                    quotes[str(symbol)] = raw
        return quotes

    def _enriched_rows(self, underlying: str) -> list[dict[str, Any]]:
        rows = self._chain_rows(underlying)
        quotes = self._quote_batches([row["symbol"] for row in rows])
        enriched: list[dict[str, Any]] = []
        for row in rows:
            quote = quotes.get(row["symbol"], {})
            quote_greeks = _greeks(quote)
            merged = dict(row)

            def prefer(primary: Any, fallback: Any) -> Any:
                value = _float(primary)
                return fallback if value is None else value

            merged.update(
                bid=prefer(quote.get("bid"), row.get("bid")),
                ask=prefer(quote.get("ask"), row.get("ask")),
                last=prefer(quote.get("last"), row.get("last")),
                bid_size=prefer(quote.get("bidSize"), row.get("bid_size")),
                ask_size=prefer(quote.get("askSize"), row.get("ask_size")),
                quote_ts=quote.get("bidTimestamp") or quote.get("lastTimestamp") or row.get("quote_ts"),
                delta=quote_greeks.get("delta", row.get("delta")),
                gamma=quote_greeks.get("gamma", row.get("gamma")),
                theta=quote_greeks.get("theta", row.get("theta")),
                vega=quote_greeks.get("vega", row.get("vega")),
                rho=quote_greeks.get("rho", row.get("rho")),
                implied_volatility=quote_greeks.get(
                    "implied_volatility", row.get("implied_volatility")
                ),
            )
            enriched.append(merged)
        return enriched

    def option_chain(self, underlying: str) -> list[OptionQuote]:
        """Return selector-ready quotes with Public bid/ask and Greeks."""
        quotes: list[OptionQuote] = []
        for row in self._enriched_rows(underlying):
            bid = row.get("bid")
            ask = row.get("ask")
            delta = row.get("delta")
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (bid, ask, delta)):
                continue
            if bid <= 0 or ask <= 0:
                continue
            quotes.append(
                OptionQuote(
                    symbol=row["symbol"],
                    underlying=row["underlying"],
                    right=row["right"],
                    strike=float(row["strike"]),
                    dte=int(row["dte"]),
                    delta=float(delta),
                    bid=float(bid),
                    ask=float(ask),
                )
            )
        return quotes

    def option_chain_raw(self, underlying: str) -> list[dict[str, Any]]:
        """Return chain rows for archival capture without a quote fan-out."""
        return self._chain_rows(underlying)

    def option_quotes(self, option_symbols: list[str]) -> dict[str, dict[str, float]]:
        """Return latest Public bid/ask values for exit marking."""
        if not option_symbols:
            return {}
        rows = self._quote_batches(option_symbols)
        result: dict[str, dict[str, float]] = {}
        for symbol, row in rows.items():
            bid = _float(row.get("bid"))
            ask = _float(row.get("ask"))
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                continue
            result[symbol] = {"bid": bid, "ask": ask}
        return result

    def option_chain_0dte(
        self, underlying: str, *, right: str, spot: float, strike_pct: float = 0.03
    ) -> list[dict[str, Any]]:
        """Return today's Public option quotes for the isolated scalp module."""
        if right not in {"call", "put"}:
            raise ValueError("right must be 'call' or 'put'")
        symbol = underlying.strip().upper()
        today = _date_today()
        payload = self._request(
            "POST",
            f"/userapigateway/marketdata/{self._account()}/option-chain",
            json={
                "instrument": {"symbol": symbol, "type": "EQUITY"},
                "expirationDate": today.isoformat(),
            },
        )
        side = "calls" if right == "call" else "puts"
        rows = []
        for raw in payload.get(side) or []:
            instrument = raw.get("instrument") or {}
            option_symbol = instrument.get("symbol")
            if not option_symbol:
                continue
            try:
                parts = parse_occ_symbol(option_symbol)
            except ValueError:
                continue
            bid = _float(raw.get("bid"))
            ask = _float(raw.get("ask"))
            if parts.underlying != symbol or parts.right != right or parts.expiry != today:
                continue
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                continue
            if abs(parts.strike - spot) > spot * strike_pct:
                continue
            mid = (bid + ask) / 2.0
            rows.append(
                {
                    "symbol": option_symbol,
                    "strike": parts.strike,
                    "right": right,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "spread_pct": (ask - bid) / mid if mid > 0 else 1.0,
                }
            )
        return rows
