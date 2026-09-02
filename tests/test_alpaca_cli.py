"""Behavior tests for the Alpaca CLI transport (harness/alpaca_cli.py) and the
PaperClient methods that ride on it when OA_BROKER_TRANSPORT=cli.

A fake `alpaca` executable is written to a temp dir and pointed at via
OA_ALPACA_CLI. It records the argv it was called with and replies with the
canned JSON the test asks for, so every assertion is about what the adapter
SENDS and how it NORMALIZES what comes back — not about call counts.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from harness import alpaca_cli
from harness.alpaca_glue import PaperClient


def _fake_cli(tmp_path: Path, *, stdout: str = "{}", exit_code: int = 0, stderr: str = "") -> Path:
    """Write an executable that dumps argv+env to a file and prints `stdout`."""
    record = tmp_path / "argv.json"
    script = tmp_path / "alpaca"
    body = f"""#!/usr/bin/env python3
import json, os, sys
with open({str(record)!r}, "w") as f:
    json.dump({{"argv": sys.argv[1:], "env_keys": sorted(k for k in os.environ if k.startswith("ALPACA"))}}, f)
sys.stdout.write({stdout!r})
sys.stderr.write({stderr!r})
sys.exit({exit_code})
"""
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _recorded(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "argv.json").read_text())


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OA_BROKER_TRANSPORT", "cli")
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setattr(alpaca_cli, "CLI_CALLS_LOG", tmp_path / "cli_calls.jsonl")
    return tmp_path


def _client() -> PaperClient:
    return PaperClient(key_id="PKTEST", secret_key="SECRETTEST")


# -- transport selection -----------------------------------------------------

def test_transport_defaults_to_sdk_and_ignores_junk(monkeypatch):
    monkeypatch.delenv("OA_BROKER_TRANSPORT", raising=False)
    assert alpaca_cli.transport() == "sdk"
    monkeypatch.setenv("OA_BROKER_TRANSPORT", "banana")
    assert alpaca_cli.transport() == "sdk"
    monkeypatch.setenv("OA_BROKER_TRANSPORT", " CLI ")
    assert alpaca_cli.transport() == "cli"


# -- run_cli mechanics ---------------------------------------------------------

def test_run_cli_passes_only_this_clients_keys_and_appends_quiet(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout='{"is_open": true}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    monkeypatch.setenv("ALPACA_PROFILE", "live-oops")  # must NOT leak to the child
    out = alpaca_cli.run_cli(["clock"], key_id="K1", secret_key="S1")
    assert out == {"is_open": True}
    rec = _recorded(cli_env)
    assert rec["argv"] == ["clock", "-q", "--timeout", "20"]
    assert rec["env_keys"] == ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"]


def test_run_cli_fails_closed_when_binary_missing(cli_env, monkeypatch):
    monkeypatch.setenv("OA_ALPACA_CLI", str(cli_env / "does-not-exist"))
    with pytest.raises(alpaca_cli.CliError, match="not found"):
        alpaca_cli.run_cli(["clock"], key_id="K", secret_key="S")
    rows = alpaca_cli.recent_calls()
    assert rows and rows[-1]["ok"] is False


def test_run_cli_raises_on_nonzero_exit_with_stderr_detail(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout="", exit_code=1,
                       stderr='{"code":0,"error":"--order-id required","status":0}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    with pytest.raises(alpaca_cli.CliError, match="--order-id required"):
        alpaca_cli.run_cli(["order", "get"], key_id="K", secret_key="S")


def test_run_cli_raises_on_error_shaped_success_body(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout='{"code":40010001,"error":"insufficient buying power"}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    with pytest.raises(alpaca_cli.CliError, match="insufficient buying power"):
        alpaca_cli.run_cli(["order", "submit"], key_id="K", secret_key="S")


def test_run_cli_raises_on_non_json_stdout(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout="Welcome to alpaca!\n")
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    with pytest.raises(alpaca_cli.CliError, match="non-JSON"):
        alpaca_cli.run_cli(["account", "get"], key_id="K", secret_key="S")


def test_run_cli_journals_every_call_without_secrets(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout='{"id":"abc","status":"accepted"}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    alpaca_cli.run_cli(["order", "submit", "--symbol", "SPY"], key_id="K-SECRET", secret_key="S-SECRET")
    text = alpaca_cli.CLI_CALLS_LOG.read_text()
    assert "K-SECRET" not in text and "S-SECRET" not in text
    row = alpaca_cli.recent_calls()[-1]
    assert row["ok"] is True and row["result"] == {"id": "abc", "status": "accepted"}
    assert row["argv"][:3] == ["alpaca", "order", "submit"]


# -- PaperClient on the CLI path ----------------------------------------------

def test_account_state_reads_options_buying_power_from_cli(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps(
        {"equity": "100034.43", "options_buying_power": "100034.43", "buying_power": "400137.72"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    state = _client().account_state()
    assert state == {"equity_usd": 100034.43, "available_options_buying_power_usd": 100034.43}
    assert _recorded(cli_env)["argv"] == ["account", "get", "-q", "--timeout", "20"]


def test_account_state_falls_back_to_buying_power_when_options_bp_missing(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"equity": "1000", "buying_power": "2000"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    assert _client().account_state()["available_options_buying_power_usd"] == 2000.0


def test_list_positions_normalizes_asset_class_lowercase(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps([
        {"symbol": "QQQ", "qty": "-28", "asset_class": "US_EQUITY", "cost_basis": "-19848.92", "market_value": "-19794.6"},
        {"symbol": "F260925P00009500", "qty": "-3", "asset_class": "us_option", "cost_basis": "-90", "market_value": "-75"},
    ]))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    rows = _client().list_positions()
    assert rows[0]["asset_class"] == "us_equity" and rows[0]["qty"] == -28.0
    assert rows[1]["asset_class"] == "us_option" and rows[1]["market_value"] == -75.0


def test_list_positions_empty_book_is_an_empty_list_not_an_error(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout="[]")
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    assert _client().list_positions() == []


def test_submit_mleg_order_sends_credit_as_negative_equals_form_limit(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"id": "ord-1", "status": "accepted", "client_order_id": "ignored"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    result = _client().submit_mleg_order(
        legs=[{"symbol": "F260925P00009500", "side": "sell", "ratio_qty": 1},
              {"symbol": "F260925P00009000", "side": "buy", "ratio_qty": 1}],
        qty=3, limit_price=-0.30, decision_id="dec123",
    )
    argv = _recorded(cli_env)["argv"]
    assert argv[:2] == ["order", "submit"]
    assert "--order-class" in argv and argv[argv.index("--order-class") + 1] == "mleg"
    assert "--limit-price=-0.30" in argv            # equals form, not two tokens
    assert argv[argv.index("--qty") + 1] == "3"
    assert argv[argv.index("--time-in-force") + 1] == "day"
    legs = json.loads(argv[argv.index("--legs") + 1])
    assert legs == [{"symbol": "F260925P00009500", "side": "sell", "ratio_qty": "1"},
                    {"symbol": "F260925P00009000", "side": "buy", "ratio_qty": "1"}]
    coid = argv[argv.index("--client-order-id") + 1]
    assert coid.startswith("oa-dec123-")
    assert result == {"id": "ord-1", "client_order_id": "ignored", "status": "accepted"}


def test_submit_single_leg_order_maps_limit_and_side(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"id": "ord-2", "status": "new"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    out = _client().submit_single_leg_order(
        option_symbol="SPY260904C00650000", side="sell", qty=2, limit_price=1.234, decision_id="d9", prefix="oa-sc-")
    argv = _recorded(cli_env)["argv"]
    assert argv[argv.index("--symbol") + 1] == "SPY260904C00650000"
    assert argv[argv.index("--side") + 1] == "sell"
    assert argv[argv.index("--type") + 1] == "limit"
    assert "--limit-price=1.23" in argv
    assert argv[argv.index("--client-order-id") + 1].startswith("oa-sc-d9-")
    assert out["id"] == "ord-2" and out["status"] == "new"


def test_submit_equity_order_is_a_market_day_order(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"id": "ord-3", "status": "accepted"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    _client().submit_equity_order(symbol="QQQ", side="buy", qty=28, decision_id="eq1")
    argv = _recorded(cli_env)["argv"]
    assert argv[argv.index("--type") + 1] == "market"
    assert argv[argv.index("--qty") + 1] == "28"
    assert argv[argv.index("--time-in-force") + 1] == "day"
    assert "--limit-price" not in " ".join(argv)


def test_submit_order_without_id_in_reply_raises(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"status": "accepted"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    with pytest.raises(alpaca_cli.CliError, match="no order id"):
        _client().submit_equity_order(symbol="QQQ", side="buy", qty=1, decision_id="x")


def test_get_order_normalizes_fill_fields(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps(
        {"id": "ord-1", "status": "filled", "filled_qty": "3", "filled_avg_price": "-0.31"}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    out = _client().get_order("ord-1")
    assert out == {"id": "ord-1", "status": "filled", "filled_qty": 3.0, "filled_avg_price": -0.31}
    assert _recorded(cli_env)["argv"] == ["order", "get", "--order-id", "ord-1", "-q", "--timeout", "20"]


def test_get_order_null_fill_price_stays_none(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout=json.dumps({"id": "o", "status": "new", "filled_qty": None, "filled_avg_price": None}))
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    out = _client().get_order("o")
    assert out["filled_qty"] == 0.0 and out["filled_avg_price"] is None


def test_cancel_order_uses_cli_and_tolerates_empty_204_body(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout="")
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    _client().cancel_order("ord-9")  # must not raise
    assert _recorded(cli_env)["argv"] == ["order", "cancel", "--order-id", "ord-9", "-q", "--timeout", "20"]


def test_market_is_open_reads_clock(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout='{"is_open": false, "next_open": "2026-09-02T09:30:00-04:00"}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    assert _client().market_is_open() is False
    assert _recorded(cli_env)["argv"] == ["clock", "-q", "--timeout", "20"]


def test_cli_path_refuses_when_paper_flag_is_off(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout='{"is_open": true}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    monkeypatch.setenv("ALPACA_PAPER", "false")
    with pytest.raises(RuntimeError, match="ALPACA_PAPER"):
        _client().market_is_open()
    assert not (cli_env / "argv.json").exists()  # the binary never ran


def test_sdk_path_untouched_when_transport_is_sdk(monkeypatch, tmp_path):
    """With the default transport the adapter must not even look for the binary."""
    monkeypatch.setenv("OA_BROKER_TRANSPORT", "sdk")
    monkeypatch.setenv("OA_ALPACA_CLI", str(tmp_path / "missing"))
    monkeypatch.setenv("ALPACA_PAPER", "true")
    client = _client()
    called = {}

    class FakeTrading:
        def get_clock(self):
            called["sdk"] = True
            return type("C", (), {"is_open": True})()

    monkeypatch.setattr(PaperClient, "_trading_client", lambda self: FakeTrading())
    assert client.market_is_open() is True and called == {"sdk": True}


def test_submit_reconciles_by_client_order_id_when_submit_call_fails(cli_env, monkeypatch):
    """Alpaca accepted the order but the CLI reply was lost: the adapter must
    find it by OUR client_order_id rather than report a failure that leaves a
    live, untracked position."""
    record = cli_env / "calls.jsonl"
    script = cli_env / "alpaca"
    script.write_text(f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
with open({str(record)!r}, "a") as f:
    f.write(json.dumps(args) + chr(10))
if args[:2] == ["order", "submit"]:
    sys.stderr.write('{{"code":0,"error":"context deadline exceeded"}}')
    sys.exit(2)
if args[:2] == ["order", "get-by-client-id"]:
    coid = args[args.index("--client-order-id") + 1]
    print(json.dumps({{"id": "found-1", "client_order_id": coid, "status": "accepted"}}))
    sys.exit(0)
sys.exit(1)
""")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    out = _client().submit_equity_order(symbol="QQQ", side="sell", qty=28, decision_id="rec1", prefix="oae-")
    assert out["id"] == "found-1" and out["client_order_id"].startswith("oae-rec1-")
    calls = [json.loads(l) for l in record.read_text().splitlines()]
    assert calls[0][:2] == ["order", "submit"] and calls[1][:2] == ["order", "get-by-client-id"]


def test_submit_reraises_original_error_when_lookup_finds_nothing(cli_env, monkeypatch):
    script = _fake_cli(cli_env, stdout="", exit_code=2, stderr='{"error":"insufficient buying power"}')
    monkeypatch.setenv("OA_ALPACA_CLI", str(script))
    with pytest.raises(alpaca_cli.CliError, match="insufficient buying power"):
        _client().submit_equity_order(symbol="QQQ", side="buy", qty=1, decision_id="x")
