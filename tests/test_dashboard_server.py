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
    assert curve[-1] == {"date": "2026-08-27", "pnl_usd": 6.0}
