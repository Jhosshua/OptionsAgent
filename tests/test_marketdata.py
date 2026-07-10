"""Tests for the shared market-data feed: the snapshot builder + the relay's
auth / path-whitelist / traversal handling (pure, no sockets)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import marketdata_relay
from harness.marketdata_publish import snapshot_row
from harness.signals_intraday import latest_rvol

DATE = "2026-07-13"


def _bar(et_time, o, h, l, c, v):
    return {"ts_utc": f"{DATE}T{et_time}:00+00:00", "et_date": DATE, "et_time": et_time,
            "o": o, "h": h, "l": l, "c": c, "v": v}


def _breakout_bars():
    return [
        _bar("09:30", 100, 101, 100, 100.5, 1000),
        _bar("09:31", 100.5, 101, 100, 100.5, 1000),
        _bar("09:32", 100.5, 101, 100, 100.5, 1000),
        _bar("09:34", 100.5, 102.5, 100, 102.0, 3000),
    ]


# --------------------------------------------------------------- snapshot builder
def test_snapshot_row_has_bar_and_signals():
    row = snapshot_row(_breakout_bars(), DATE, "SPY", rvol_min=1.5)
    assert row is not None
    assert row["symbol"] == "SPY" and row["source"] == "optionsagent"
    assert row["bar"]["c"] == 102.0
    assert row["opening_range"] == {"high": 101, "low": 100}
    assert row["breakout"] == "up"
    assert row["rvol_latest"] == 3.0
    assert row["vwap"] is not None


def test_snapshot_row_none_without_session_bars():
    pre = [_bar("09:15", 100, 100, 99, 99, 500)]  # premarket only
    assert snapshot_row(pre, DATE, "SPY") is None


def test_latest_rvol():
    assert latest_rvol(_breakout_bars(), DATE) == 3.0


# --------------------------------------------------------------- relay resolve_request
TOKEN = "secret-token-123"


def _req(method, path, auth, data_dir):
    return marketdata_relay.resolve_request(method, path, auth, token=TOKEN, data_dir=data_dir)


def test_relay_rejects_non_get(tmp_path):
    status, _, _ = _req("POST", "/marketdata/2026-07-13.jsonl", f"Bearer {TOKEN}", str(tmp_path))
    assert status == 405


def test_relay_requires_valid_token(tmp_path):
    assert _req("GET", "/marketdata/2026-07-13.jsonl", None, str(tmp_path))[0] == 401
    assert _req("GET", "/marketdata/2026-07-13.jsonl", "Bearer wrong", str(tmp_path))[0] == 401
    assert _req("GET", "/marketdata/2026-07-13.jsonl", "Basic xyz", str(tmp_path))[0] == 401


def test_relay_empty_configured_token_denies_all(tmp_path):
    status, _, _ = marketdata_relay.resolve_request(
        "GET", "/marketdata/2026-07-13.jsonl", "Bearer ", token="", data_dir=str(tmp_path))
    assert status == 401


def test_relay_bad_path_404(tmp_path):
    assert _req("GET", "/etc/passwd", f"Bearer {TOKEN}", str(tmp_path))[0] == 404
    assert _req("GET", "/marketdata/../secrets.jsonl", f"Bearer {TOKEN}", str(tmp_path))[0] == 404
    assert _req("GET", "/marketdata/2026-7-3.jsonl", f"Bearer {TOKEN}", str(tmp_path))[0] == 404  # bad date fmt


def test_relay_missing_file_404(tmp_path):
    assert _req("GET", "/marketdata/2026-07-13.jsonl", f"Bearer {TOKEN}", str(tmp_path))[0] == 404


def test_relay_serves_existing_file(tmp_path):
    body = '{"symbol":"SPY","bar":{"c":102.0}}\n'
    (tmp_path / "2026-07-13.jsonl").write_text(body)
    status, ctype, out = _req("GET", "/marketdata/2026-07-13.jsonl", f"Bearer {TOKEN}", str(tmp_path))
    assert status == 200 and ctype == "application/x-ndjson"
    assert out.decode() == body
