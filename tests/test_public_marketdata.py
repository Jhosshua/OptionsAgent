"""Offline contract tests for the optional Public.com market-data sidecar."""

from datetime import date

import pytest

from harness.public_marketdata import PublicMarketDataClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, token=None, responses=None):
        self.token = token or {"accessToken": "test-token"}
        self.responses = list(responses or [])
        self.post_calls = []
        self.request_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse(self.token)

    def request(self, method, url, **kwargs):
        self.request_calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return FakeResponse(self.responses.pop(0))


CCL_PUT = "CCL260930P00024000"
CCL_BAD_ADJUSTED = "CCL1260930P00024000"


def _client(session):
    return PublicMarketDataClient(
        "test-secret",
        account_id="acct-1",
        dte_min=30,
        dte_max=45,
        session=session,
    )


def test_option_chain_normalizes_public_chain_and_quote_greeks(monkeypatch):
    monkeypatch.setattr("harness.public_marketdata._date_today", lambda: date(2026, 8, 27))
    session = FakeSession(
        responses=[
            {"expirations": ["2026-09-30", "2026-10-30", "not-a-date"]},
            {
                "puts": [
                    {
                        "instrument": {"symbol": CCL_PUT},
                        "bid": "0.40",
                        "ask": "0.45",
                        "last": "0.42",
                        "bidSize": 2,
                        "askSize": 3,
                    },
                    {"instrument": {"symbol": CCL_BAD_ADJUSTED}, "bid": "9", "ask": "9.1"},
                    {"instrument": {"symbol": "not-an-option"}, "bid": "1", "ask": "1.1"},
                ],
                "calls": [],
            },
            {
                "quotes": [
                    {
                        "instrument": {"symbol": CCL_PUT},
                        "bid": "0.41",
                        "ask": "0.46",
                        "optionDetails": {"greeks": {"delta": "-0.25", "gamma": "0.02"}},
                    }
                ]
            },
        ]
    )

    quotes = _client(session).option_chain("CCL")

    assert len(quotes) == 1
    assert quotes[0].symbol == CCL_PUT
    assert quotes[0].strike == 24.0
    assert quotes[0].dte == 34
    assert quotes[0].delta == -0.25
    assert quotes[0].bid == 0.41
    assert quotes[0].ask == 0.46
    assert len(session.post_calls) == 1
    assert session.post_calls[0][1]["json"]["secret"] == "test-secret"


def test_option_chain_falls_back_to_chain_greeks_when_quote_omits_details(monkeypatch):
    monkeypatch.setattr("harness.public_marketdata._date_today", lambda: date(2026, 8, 27))
    session = FakeSession(
        responses=[
            {"expirations": ["2026-09-30"]},
            {
                "puts": [
                    {
                        "instrument": {"symbol": CCL_PUT},
                        "bid": "0.40",
                        "ask": "0.45",
                        "optionDetails": {
                            "greeks": {
                                "delta": "-0.25",
                                "gamma": "0.02",
                                "theta": "-0.01",
                                "vega": "0.10",
                                "rho": "-0.03",
                                "impliedVolatility": "0.35",
                            }
                        },
                    }
                ],
                "calls": [],
            },
            {"quotes": [{"instrument": {"symbol": CCL_PUT}, "bid": "0.41", "ask": "0.46"}]},
            {"quotes": [{"instrument": {"symbol": CCL_PUT}, "bid": "0.41", "ask": "0.46"}]},
        ]
    )

    client = _client(session)
    enriched = client._enriched_rows("CCL")

    assert len(enriched) == 1
    assert enriched[0]["delta"] == -0.25
    assert enriched[0]["bid"] == 0.41
    assert enriched[0]["gamma"] == 0.02
    assert enriched[0]["implied_volatility"] == 0.35

    # The selector-facing adapter accepts the chain delta even though the
    # quote response omitted optionDetails entirely.
    assert len(client.option_chain("CCL")) == 1


def test_raw_chain_does_not_make_quote_fanout_request(monkeypatch):
    monkeypatch.setattr("harness.public_marketdata._date_today", lambda: date(2026, 8, 27))
    session = FakeSession(
        responses=[
            {"expirations": ["2026-09-30"]},
            {"puts": [{"instrument": {"symbol": CCL_PUT}, "bid": "0.4", "ask": "0.5"}]},
        ]
    )

    rows = _client(session).option_chain_raw("CCL")

    assert rows[0]["symbol"] == CCL_PUT
    assert "delta" not in rows[0]
    assert len(session.request_calls) == 2  # expirations + chain; no /quotes call


def test_option_quotes_skips_non_positive_market_values():
    good = "CCL260930P00024000"
    bad = "CCL260930P00023000"
    session = FakeSession(
        responses=[
            {
                "quotes": [
                    {"instrument": {"symbol": good}, "bid": "0.4", "ask": "0.5"},
                    {"instrument": {"symbol": bad}, "bid": "0", "ask": "0.5"},
                ]
            }
        ]
    )

    assert _client(session).option_quotes([good, bad]) == {good: {"bid": 0.4, "ask": 0.5}}


def test_0dte_requires_valid_side_and_filters_expiration_and_spot(monkeypatch):
    today = date(2026, 8, 27)
    monkeypatch.setattr("harness.public_marketdata._date_today", lambda: today)
    valid = "SPY260827C00640000"
    wrong_expiry = "SPY260828C00640000"
    session = FakeSession(
        responses=[
            {
                "calls": [
                    {"instrument": {"symbol": valid}, "bid": "1", "ask": "1.1"},
                    {"instrument": {"symbol": wrong_expiry}, "bid": "1", "ask": "1.1"},
                ],
                "puts": [],
            }
        ]
    )

    rows = _client(session).option_chain_0dte("SPY", right="call", spot=640.0)

    assert [row["symbol"] for row in rows] == [valid]
    with pytest.raises(ValueError, match="right"):
        _client(FakeSession()).option_chain_0dte("SPY", right="CALL", spot=640.0)


def test_paper_client_routes_only_market_data_to_public(monkeypatch):
    from harness.alpaca_glue import PaperClient

    class FakePublic:
        def option_quotes(self, symbols):
            return {symbols[0]: {"bid": 1.0, "ask": 1.1}}

    monkeypatch.setenv("OA_OPTIONS_DATA_PROVIDER", "public")
    monkeypatch.setattr(
        "harness.public_marketdata.PublicMarketDataClient.from_env",
        lambda: FakePublic(),
    )

    client = PaperClient(key_id="paper-key", secret_key="paper-secret")

    assert client.option_quotes(["CCL260930P00024000"]) == {
        "CCL260930P00024000": {"bid": 1.0, "ask": 1.1}
    }
