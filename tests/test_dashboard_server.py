"""Security and contract tests for the read-only dashboard server."""

import json
from http.client import HTTPConnection
import inspect

import pytest

import harness.dashboard_server as dashboard


class FakeStore:
    def get(self):
        return {
            "status": "ok",
            "as_of": dashboard._iso_now(),
            "consecutive_failures": 0,
            "error": None,
            "account": {"equity_usd": 5000.0, "available_options_buying_power_usd": 4200.0},
            "positions": [],
        }


@pytest.fixture
def http_server():
    server = dashboard.DashboardHTTPServer(
        ("127.0.0.1", 0), dashboard.DashboardHandler, store=FakeStore()
    )
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(server, method, path, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def test_health_and_data_api_are_available_locally(http_server):
    assert _request(http_server, "GET", "/healthz") == (200, b'{"status":"ok"}')
    status, body = _request(http_server, "GET", "/api/summary")
    assert status == 200
    assert json.loads(body)["paper"] is True


def test_dashboard_rejects_write_methods_and_unknown_paths(http_server):
    assert _request(http_server, "POST", "/api/summary")[0] == 405
    assert _request(http_server, "GET", "/data/.env")[0] == 404
    assert _request(http_server, "GET", "/api/summary/../../.env")[0] == 404


def test_dashboard_static_module_has_no_order_or_execution_imports():
    source = inspect.getsource(dashboard)
    assert "harness.execution" not in source
    assert "submit_" not in source
    assert "cancel_order" not in source


def test_snapshot_store_refreshes_in_background_and_fails_closed(monkeypatch):
    calls = []

    class Broker:
        def read_snapshot(self):
            calls.append(True)
            return ({"equity_usd": 5000.0, "available_options_buying_power_usd": 4000.0}, [])

    store = dashboard.SnapshotStore(lambda: Broker())
    store.refresh()
    snapshot = store.get()
    assert calls == [True]
    assert snapshot["status"] == "ok"
    assert snapshot["account"]["equity_usd"] == 5000.0

    class BrokenBroker:
        def read_snapshot(self):
            raise RuntimeError("broker down")

    failed = dashboard.SnapshotStore(lambda: BrokenBroker())
    failed.refresh()
    snapshot = failed.get()
    assert snapshot["status"] == "unavailable"
    assert snapshot["account"] is None
    assert snapshot["consecutive_failures"] == 1


def test_history_metrics_excludes_unknown_pnl_and_builds_daily_curve():
    curve, daily = dashboard._history_metrics(
        [
            {"ts": "2026-08-26T14:00:00+00:00", "pnl_usd": 10},
            {"ts": "2026-08-26T15:00:00+00:00", "pnl_usd": None},
            {"ts": "2026-08-27T14:00:00+00:00", "pnl_usd": -4},
        ]
    )
    assert daily == [
        {"date": "2026-08-26", "pnl_usd": 10.0},
        {"date": "2026-08-27", "pnl_usd": -4.0},
    ]
    # The curve carries a RUNNING total under its own key; the anchor sits on
    # the day before the first trade so no date appears twice.
    assert curve[0] == {"date": "2026-08-25", "cumulative_pnl_usd": 0.0}
    assert curve[-1] == {"date": "2026-08-27", "cumulative_pnl_usd": 6.0}


# --- equity scalper visibility (2026-09-01) -------------------------------
# The scalper writes its own journal, never structures.jsonl. Before this the
# dashboard read only the seller's registry and reported a flat, empty day
# while the scalper was the engine actually trading.

SCALP_EVENTS = [
    {"kind": "eq_open", "symbol": "SPY", "rule": "morning_fade", "side": "long",
     "qty": 26, "entry_price": 765.84, "ts": "2026-08-31T14:18:04+00:00"},
    {"kind": "eq_close", "symbol": "SPY", "reason": "time_exit", "entry": 765.84,
     "exit": 765.40, "qty": 26, "pnl_usd": -11.44, "ts": "2026-08-31T16:23:04+00:00"},
    {"kind": "eq_open", "symbol": "QQQ", "rule": "gap_follow", "side": "short",
     "qty": 28, "entry_price": 708.89, "ts": "2026-09-01T17:01:06+00:00"},
]


def _write_scalp_journal(tmp_path, monkeypatch, events):
    path = tmp_path / "equity_scalp_decisions.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    monkeypatch.setattr(dashboard, "EQUITY_SCALP_DECISIONS_PATH", path)
    return path


def test_equity_scalp_journal_pairs_opens_with_closes(tmp_path, monkeypatch):
    _write_scalp_journal(tmp_path, monkeypatch, SCALP_EVENTS)
    open_rows, closed = dashboard._equity_scalp_records()

    assert [row["underlying"] for row in open_rows] == ["QQQ"]
    assert open_rows[0]["rule"] == "gap_follow"
    assert open_rows[0]["side"] == "short"
    assert open_rows[0]["entry_price"] == 708.89
    assert len(closed) == 1
    assert closed[0]["underlying"] == "SPY"
    assert closed[0]["rule"] == "morning_fade"
    assert closed[0]["side"] == "long"
    assert closed[0]["pnl_usd"] == -11.44
    assert closed[0]["strategy_type"] == "equity_scalp"


def test_unpaired_close_does_not_invent_an_open_position(tmp_path, monkeypatch):
    """A close with no matching open must still be reported as a closed trade
    and must not leave a phantom open row behind."""
    _write_scalp_journal(tmp_path, monkeypatch, [
        {"kind": "eq_close", "symbol": "IWM", "reason": "time_exit_orphan",
         "exit": 240.0, "qty": 10, "pnl_usd": 3.5, "ts": "2026-09-01T16:00:00+00:00"},
    ])
    open_rows, closed = dashboard._equity_scalp_records()
    assert open_rows == []
    assert len(closed) == 1 and closed[0]["pnl_usd"] == 3.5


def test_closed_scalps_reach_todays_pnl_and_the_equity_curve(tmp_path, monkeypatch):
    """The seller's registry being empty must not zero out the scalper's P/L."""
    _write_scalp_journal(tmp_path, monkeypatch, SCALP_EVENTS + [
        {"kind": "eq_close", "symbol": "QQQ", "reason": "time_exit", "entry": 708.89,
         "exit": 707.00, "qty": 28, "pnl_usd": 52.92,
         "ts": dashboard._now().isoformat()},
    ])
    monkeypatch.setattr(dashboard, "STRUCTURES_PATH", tmp_path / "missing.jsonl")
    payload = dashboard.build_payload(FakeStore(), "/api/summary")

    assert payload["today_pnl_usd"] == pytest.approx(52.92)
    curve = payload["equity_curve"]
    assert [point["cumulative_pnl_usd"] for point in curve] == pytest.approx([0.0, -11.44, 41.48])
    # The zero anchor must NOT share a date with the first trade.
    assert curve[0]["date"] == "2026-08-30" and curve[1]["date"] == "2026-08-31"
    assert len({point["date"] for point in curve}) == len(curve)
    assert payload["open_scalps"] == 0

    trades = dashboard.build_payload(FakeStore(), "/api/trades")["trades"]
    assert [row["pnl_usd"] for row in trades] == [52.92, -11.44]  # newest first
    assert trades[0]["strategy"] == "Equity Scalp"


def test_today_pnl_uses_the_et_trading_date_not_the_utc_date(tmp_path, monkeypatch):
    """01:00 UTC is 21:00 ET the PREVIOUS day: a UTC-date comparison would
    credit that close to the wrong session."""
    yesterday_et = (dashboard._now().astimezone(dashboard.ET).date())
    closed = [{"ts": f"{yesterday_et.isoformat()}T23:30:00-04:00", "pnl_usd": 25.0}]
    assert dashboard._today_pnl(closed) == pytest.approx(25.0)

    _, daily = dashboard._history_metrics(closed)
    assert daily == [{"date": yesterday_et.isoformat(), "pnl_usd": 25.0}]


def test_short_position_unrealized_pnl_is_positive_when_price_falls(tmp_path, monkeypatch):
    """Alpaca's facade returns no unrealized P/L. Market value minus cost basis
    must read correctly for a SHORT, whose cost basis is negative proceeds."""
    _write_scalp_journal(tmp_path, monkeypatch, SCALP_EVENTS)
    open_rows, _ = dashboard._equity_scalp_records()
    snapshot = {"positions": [
        {"symbol": "QQQ", "qty": -28.0, "cost_basis": -19848.92, "market_value": -19787.88},
        {"symbol": "AAPL", "qty": 10.0, "cost_basis": 2000.0, "market_value": 2150.0},
    ]}
    rows = dashboard._position_rows(snapshot, [], open_rows)

    assert rows[0]["unrealized_pnl_usd"] == pytest.approx(61.04)
    assert rows[0]["strategy"] == "Equity Scalp · Gap Follow"
    assert rows[0]["side"] == "short"
    assert rows[0]["entry_price"] == 708.89
    # An unrelated broker position stays labelled as one, with real P/L.
    assert rows[1]["strategy"] == "Broker position"
    assert rows[1]["unrealized_pnl_usd"] == pytest.approx(150.0)


def test_missing_day_state_reports_not_running_rather_than_a_zero_day(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "EQUITY_SCALP_STATE_DIR", tmp_path / "no_state")
    summary = dashboard._equity_scalp_summary([])
    assert summary["has_state"] is False
    assert summary["trades_today"] is None      # not 0 — silence is not a zero day
    assert summary["realized_today_usd"] is None

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    today = dashboard._et_today()
    (state_dir / f"{today}.json").write_text(json.dumps(
        {"date": today, "trades_today": 2, "realized_pnl_usd": -8.09,
         "halted": False, "rules_taken_day": ["morning_fade", "gap_follow"]}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "EQUITY_SCALP_STATE_DIR", state_dir)
    summary = dashboard._equity_scalp_summary([])
    assert summary["has_state"] is True
    assert summary["trades_today"] == 2
    assert summary["realized_today_usd"] == pytest.approx(-8.09)
    assert summary["rules_taken_day"] == ["morning_fade", "gap_follow"]


# --- QA review follow-ups (2026-09-01) ------------------------------------

def test_stale_broker_reports_unknown_positions_not_an_empty_book(monkeypatch, tmp_path):
    """A broker read that never landed must not render as '0 positions'."""
    monkeypatch.setattr(dashboard, "EQUITY_SCALP_DECISIONS_PATH", tmp_path / "none.jsonl")

    class DeadStore:
        def get(self):
            return {"status": "unavailable", "as_of": None, "consecutive_failures": 3,
                    "error": "broker_timeout", "account": None, "positions": []}

    assert dashboard.build_payload(DeadStore(), "/api/summary")["open_positions"] is None
    positions = dashboard.build_payload(DeadStore(), "/api/positions")
    assert positions["positions_known"] is False


def test_unpaired_open_from_an_earlier_day_is_not_a_live_position(tmp_path, monkeypatch):
    """The scalper flattens by 15:50 ET, so a stale open means an un-journaled
    close, not a position still on the book. It must not persist forever."""
    _write_scalp_journal(tmp_path, monkeypatch, [
        {"kind": "eq_open", "symbol": "SPY", "rule": "morning_fade", "side": "long",
         "qty": 10, "entry_price": 700.0, "ts": "2026-08-20T14:18:04+00:00"},
    ])
    open_rows, closed = dashboard._equity_scalp_records()
    assert open_rows == [] and closed == []


def test_two_opens_on_one_symbol_pair_fifo_and_keep_their_own_identity(tmp_path, monkeypatch):
    """A second open must not overwrite the first: that stamps BOTH closed
    trades with the wrong rule, side and entry price."""
    _write_scalp_journal(tmp_path, monkeypatch, [
        {"kind": "eq_open", "symbol": "SPY", "rule": "morning_fade", "side": "long",
         "qty": 10, "entry_price": 700.0, "ts": "2026-09-01T14:00:00+00:00"},
        {"kind": "eq_open", "symbol": "SPY", "rule": "gap_follow", "side": "short",
         "qty": 10, "entry_price": 710.0, "ts": "2026-09-01T17:00:00+00:00"},
        {"kind": "eq_close", "symbol": "SPY", "entry": 700.0, "exit": 695.0, "qty": 10,
         "pnl_usd": -50.0, "reason": "time_exit", "ts": "2026-09-01T15:00:00+00:00"},
        {"kind": "eq_close", "symbol": "SPY", "entry": 710.0, "exit": 708.0, "qty": 10,
         "pnl_usd": 20.0, "reason": "time_exit", "ts": "2026-09-01T18:00:00+00:00"},
    ])
    _, closed = dashboard._equity_scalp_records()
    first, second = closed
    assert (first["pnl_usd"], first["rule"], first["side"], first["entry_price"]) == (-50.0, "morning_fade", "long", 700.0)
    assert (second["pnl_usd"], second["rule"], second["side"], second["entry_price"]) == (20.0, "gap_follow", "short", 710.0)


def test_a_day_of_unknown_pnl_closes_is_unknown_not_a_flat_zero(tmp_path, monkeypatch):
    """The orphan-close path journals pnl_usd: null. Reporting that day as
    +$0.00 asserts a flat session that nobody actually measured."""
    now = dashboard._now().isoformat()
    assert dashboard._today_pnl([{"ts": now, "pnl_usd": None}]) is None
    # A genuinely empty day is still zero, not unknown.
    assert dashboard._today_pnl([]) == 0.0
    # One known close alongside an unknown one still reports the known total.
    assert dashboard._today_pnl([{"ts": now, "pnl_usd": None}, {"ts": now, "pnl_usd": 5.0}]) == 5.0


def test_malformed_day_state_degrades_instead_of_breaking_the_page(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"; state_dir.mkdir()
    (state_dir / f"{dashboard._et_today()}.json").write_text(
        json.dumps({"rules_taken_day": "morning_fade", "trades_today": {"bad": 1}}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "EQUITY_SCALP_STATE_DIR", state_dir)
    summary = dashboard._equity_scalp_summary([])
    assert summary["rules_taken_day"] == []  # a bare string is not a rule list


def test_trades_sort_on_the_parsed_instant_not_the_raw_string(tmp_path, monkeypatch):
    """'…Z' sorts after '…+00:00' lexicographically despite being the same
    instant, which would reorder the table."""
    _write_scalp_journal(tmp_path, monkeypatch, [
        {"kind": "eq_close", "symbol": "SPY", "qty": 1, "pnl_usd": 1.0, "ts": "2026-08-31T16:00:00+00:00"},
        {"kind": "eq_close", "symbol": "QQQ", "qty": 1, "pnl_usd": 2.0, "ts": "2026-08-30T16:00:00Z"},
    ])
    monkeypatch.setattr(dashboard, "STRUCTURES_PATH", tmp_path / "missing.jsonl")
    trades = dashboard.build_payload(FakeStore(), "/api/trades")["trades"]
    assert [row["underlying"] for row in trades] == ["SPY", "QQQ"]  # newest first


def test_last_cycle_is_iso_8601_parseable(tmp_path, monkeypatch):
    path = tmp_path / "decisions.jsonl"
    path.write_text(json.dumps({"kind": "cycle_start", "ts": "2026-09-01T14:15:02.246680+00:00"}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "DECISIONS_PATH", path)
    value = dashboard._last_cycle_iso()
    assert "T" in value and " " not in value
    assert dashboard._parse_ts(value) is not None
