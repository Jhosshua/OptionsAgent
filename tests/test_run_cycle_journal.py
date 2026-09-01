"""run_cycle must journal the AI call itself as a `proposer_result` row.

Without this row a dead model and a quiet market are the same empty day
(2026-08-31 and 09-01 were both lost to a logged-out CLI and looked like
nothing-to-trade). Everything that touches a broker or the network is stubbed;
the assertion is on what reaches the journal seam."""

import run_cycle
from harness.proposer import ProposeReport


def _stub_everything(monkeypatch, report):
    rows = []

    class Client:
        def account_state(self):
            return {"equity_usd": 1.0}

        def list_positions(self):
            return []

    monkeypatch.setattr(run_cycle, "make_client", lambda: Client())
    monkeypatch.setattr(run_cycle, "build_account_state", lambda **kwargs: object())
    monkeypatch.setattr(run_cycle, "universe", lambda: ["CCL"])
    monkeypatch.setattr(run_cycle.chain_capture, "capture_universe", lambda client, syms: {})
    monkeypatch.setattr(run_cycle.market_context, "build_context", lambda client, syms: {"CCL": {}})
    monkeypatch.setattr(run_cycle.market_context, "has_data", lambda ctx: False)
    monkeypatch.setattr(run_cycle, "propose_report", lambda bundle: report)
    monkeypatch.setattr(run_cycle.decision_log, "record_cycle_start", lambda phase: "cycle-test")
    monkeypatch.setattr(run_cycle.decision_log, "record", lambda row: rows.append(row))
    monkeypatch.setattr(run_cycle.notify, "error", lambda message: None)
    return rows


def test_a_failed_ai_call_is_journaled_as_a_proposer_result_row(monkeypatch):
    rows = _stub_everything(
        monkeypatch,
        ProposeReport(provider="deepseek", model="deepseek-v4-pro", ok=False, attempts=3,
                      latency_s=9.0, error="RuntimeError: DeepSeek HTTP 500: down"),
    )

    run_cycle.run()

    results = [row for row in rows if row.get("kind") == "proposer_result"]
    assert len(results) == 1
    assert results[0]["cycle_id"] == "cycle-test"
    assert results[0]["ok"] is False
    assert results[0]["proposals"] == 0
    assert "HTTP 500" in results[0]["error"]
    assert results[0]["ts"]


def test_a_quiet_market_is_journaled_as_ok_with_zero_proposals(monkeypatch):
    rows = _stub_everything(
        monkeypatch,
        ProposeReport(provider="deepseek", model="deepseek-v4-pro", ok=True, attempts=1, latency_s=40.0),
    )

    run_cycle.run()

    results = [row for row in rows if row.get("kind") == "proposer_result"]
    assert len(results) == 1
    assert results[0]["ok"] is True and results[0]["proposals"] == 0 and results[0]["error"] is None
