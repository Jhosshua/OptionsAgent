"""Offline tests for the proposer boundary: the Antigravity CLI (agy) running
Gemini 3.8 Flash is the only provider since 2026-09-13. subprocess.run is
always faked; no test starts a real agy."""

import json

import pytest

from harness import proposer

GOOD = {
    "proposals": [
        {
            "underlying": "ccl",
            "strategy_type": "credit_spread",
            "direction": "bullish",
            "conviction": 0.8,
            "thesis": "test",
        }
    ]
}
BUNDLE = {"phase": "credit_spreads_only", "allowed_strategies": ["credit_spread"], "watchlist": []}


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _agy_json(structured, status="SUCCESS"):
    return json.dumps({"status": status, "response": "done", "structured_output": structured})


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    """No sleeping between retries, no Discord, a fake agy on PATH."""
    sent = []
    monkeypatch.setattr(proposer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(proposer.notify, "error", lambda message: sent.append(message))
    monkeypatch.setenv("OA_LLM_ATTEMPTS", "3")
    monkeypatch.delenv("OA_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OA_AGY_MODEL", raising=False)
    monkeypatch.delenv("OA_AGY_CLI", raising=False)
    monkeypatch.setattr(proposer.shutil, "which", lambda name: "/usr/local/bin/agy" if name == "agy" else None)
    monkeypatch.setattr(proposer.subprocess, "run", lambda *a, **k: pytest.fail("a test ran a real agy"))
    return sent


def _run_returning(monkeypatch, results):
    """Queue of Completed results; the last one repeats. Records every call."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return results[min(len(calls) - 1, len(results) - 1)]

    monkeypatch.setattr(proposer.subprocess, "run", fake_run)
    return calls


def _flag(command, name):
    return command[command.index(name) + 1]


# --- agy --------------------------------------------------------------------


def test_agy_gets_the_bundle_and_structured_output_is_parsed(monkeypatch, alerts):
    calls = _run_returning(monkeypatch, [Completed(stdout=_agy_json(GOOD))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.provider == "agy"
    assert report.attempts == 1 and report.error is None
    assert [p.underlying for p in report.proposals] == ["CCL"]
    assert alerts == []
    command, kwargs = calls[0]
    assert command[0] == "/usr/local/bin/agy"
    assert _flag(command, "--model") == "gemini-3.8-flash-low"  # config/config.json llm.model
    assert _flag(command, "--effort") == "low"
    assert _flag(command, "--output-format") == "json"
    assert json.loads(_flag(command, "--json-schema")) == proposer._OUTPUT_SCHEMA
    assert "--new-project" in command and "--sandbox" in command
    assert "--dangerously-skip-permissions" not in command
    prompt = _flag(command, "-p")
    assert prompt.startswith(proposer.NO_TOOLS_PREAMBLE)
    assert proposer.SYSTEM_PROMPT in prompt
    assert json.loads(prompt.rsplit("\n", 1)[-1])["phase"] == "credit_spreads_only"
    # never started inside the repo: agy has reverted files where it ran
    assert kwargs["cwd"] and "wingspan-agy-" in kwargs["cwd"]


@pytest.mark.parametrize("model,effort", [("gemini-3.8-flash-low", "low"), ("gemini-3.8-flash-medium", "medium")])
def test_env_model_sets_model_and_matching_effort(monkeypatch, model, effort):
    monkeypatch.setenv("OA_AGY_MODEL", model)
    calls = _run_returning(monkeypatch, [Completed(stdout=_agy_json({"proposals": []}))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.proposals == [] and report.model == model
    assert _flag(calls[0][0], "--model") == model
    assert _flag(calls[0][0], "--effort") == effort


def test_config_model_is_used_when_env_is_unset(monkeypatch):
    monkeypatch.setattr(proposer, "config", lambda: {"llm": {"model": "gemini-3.8-flash-medium"}})
    calls = _run_returning(monkeypatch, [Completed(stdout=_agy_json({"proposals": []}))])

    assert proposer.propose_report(BUNDLE).model == "gemini-3.8-flash-medium"
    assert _flag(calls[0][0], "--effort") == "medium"


def test_unsupported_model_fails_closed_without_running_agy(monkeypatch, alerts):
    monkeypatch.setenv("OA_AGY_MODEL", "deepseek-v4-pro")

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == [] and report.attempts == 1
    assert "unsupported agy model" in report.error
    assert len(alerts) == 1 and "NO TRADES" in alerts[0]


def test_missing_cli_fails_closed_and_pages(monkeypatch, alerts):
    monkeypatch.setattr(proposer.shutil, "which", lambda name: None)

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.attempts == 1  # config errors are not retried
    assert "agy CLI not found" in report.error
    assert len(alerts) == 1 and "GEMINI_HOME_TGZ_B64" in alerts[0]


def test_absolute_cli_path_must_exist(monkeypatch, alerts, tmp_path):
    monkeypatch.setenv("OA_AGY_CLI", str(tmp_path / "nope"))

    assert proposer.propose(BUNDLE) == []
    assert len(alerts) == 1


def test_nonzero_exit_is_retried_then_fails_closed_with_one_page(monkeypatch, alerts):
    calls = _run_returning(monkeypatch, [Completed(returncode=1, stderr="not logged in")])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert len(calls) == 3 and report.attempts == 3
    assert "not logged in" in report.error
    assert len(alerts) == 1  # one page, not one per attempt


def test_exit_zero_with_no_output_is_a_failure_not_a_quiet_day(monkeypatch, alerts):
    _run_returning(monkeypatch, [Completed(stdout="", stderr="jetski: no output produced")])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and "no output" in report.error
    assert len(alerts) == 1


def test_transient_failure_then_success_does_not_alert(monkeypatch, alerts):
    calls = _run_returning(monkeypatch, [Completed(returncode=1, stderr="busy"), Completed(stdout=_agy_json(GOOD))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.attempts == 2 and len(calls) == 2
    assert alerts == []


def test_non_json_stdout_is_rejected(monkeypatch, alerts):
    _run_returning(monkeypatch, [Completed(stdout="I think CCL looks good")])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and "did not return JSON" in report.error


def test_non_success_status_is_rejected(monkeypatch, alerts):
    _run_returning(monkeypatch, [Completed(stdout=_agy_json(GOOD, status="ERROR"))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == [] and "status" in report.error


def test_missing_structured_output_is_rejected(monkeypatch, alerts):
    _run_returning(monkeypatch, [Completed(stdout=json.dumps({"status": "SUCCESS", "response": "{}"}))])

    assert proposer.propose_report(BUNDLE).ok is False


def test_structured_output_without_a_proposals_list_is_rejected(monkeypatch, alerts):
    _run_returning(monkeypatch, [Completed(stdout=_agy_json({"ideas": []}))])

    assert proposer.propose_report(BUNDLE).ok is False


def test_cli_timeout_is_retried_then_fails_closed(monkeypatch, alerts):
    def boom(command, **kwargs):
        raise proposer.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(proposer.subprocess, "run", boom)

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.attempts == 3
    assert len(alerts) == 1


def test_timeout_setting_reaches_agy_and_subprocess(monkeypatch):
    monkeypatch.setenv("OA_LLM_TIMEOUT_SECONDS", "90")
    calls = _run_returning(monkeypatch, [Completed(stdout=_agy_json({"proposals": []}))])

    proposer.propose_report(BUNDLE)

    assert _flag(calls[0][0], "--print-timeout") == "90s"
    assert calls[0][1]["timeout"] == 120.0


def test_retry_backoff_sleeps_5_then_10(monkeypatch, alerts):
    slept = []
    monkeypatch.setattr(proposer.time, "sleep", lambda seconds: slept.append(seconds))
    _run_returning(monkeypatch, [Completed(returncode=1, stderr="down")])

    report = proposer.propose_report(BUNDLE)

    assert report.attempts == 3
    assert slept == [5, 10]  # no sleep after the last attempt


def test_malformed_items_are_dropped_not_guessed(monkeypatch):
    payload = {
        "proposals": [
            GOOD["proposals"][0],
            {**GOOD["proposals"][0], "underlying": "AAL", "conviction": 1.5},
            {**GOOD["proposals"][0], "underlying": "T", "strategy_type": "iron_condor"},
            {"underlying": "F"},
        ]
    }
    _run_returning(monkeypatch, [Completed(stdout=_agy_json(payload))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True
    assert [p.underlying for p in report.proposals] == ["CCL"]


def test_propose_wrapper_returns_only_the_proposals(monkeypatch):
    _run_returning(monkeypatch, [Completed(stdout=_agy_json(GOOD))])

    assert [p.underlying for p in proposer.propose(BUNDLE)] == ["CCL"]


def test_journal_row_carries_the_call_outcome_not_the_proposals():
    report = proposer.ProposeReport(
        provider="agy", model="gemini-3.8-flash-low", ok=False, attempts=3, latency_s=12.5,
        error="RuntimeError: agy exited with status 1: not logged in",
    )

    row = report.as_journal_row("cycle-1", "2026-09-02T14:15:40+00:00")

    assert row == {
        "kind": "proposer_result",
        "cycle_id": "cycle-1",
        "ts": "2026-09-02T14:15:40+00:00",
        "provider": "agy",
        "model": "gemini-3.8-flash-low",
        "ok": False,
        "proposals": 0,
        "attempts": 3,
        "latency_s": 12.5,
        "error": "RuntimeError: agy exited with status 1: not logged in",
    }
