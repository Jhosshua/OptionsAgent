"""Offline tests for the proposer boundary: DeepSeek API by default, the
Claude Code CLI only when OA_LLM_PROVIDER=claude_cli (Mac)."""

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


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _completion(content, finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    """No sleeping between retries, no Discord, deterministic env."""
    sent = []
    monkeypatch.setattr(proposer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(proposer.notify, "error", lambda message: sent.append(message))
    monkeypatch.setenv("OA_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("OA_LLM_ATTEMPTS", "3")
    monkeypatch.delenv("OA_DEEPSEEK_MODEL", raising=False)
    return sent


def _post_returning(monkeypatch, responses):
    """Queue of responses; the last one repeats. Records every call."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    monkeypatch.setattr(proposer.requests, "post", fake_post)
    return calls


# --- DeepSeek --------------------------------------------------------------


def test_deepseek_posts_the_bundle_and_parses_proposals(monkeypatch, alerts):
    calls = _post_returning(monkeypatch, [FakeResponse(200, _completion(json.dumps(GOOD)))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True
    assert report.attempts == 1
    assert report.error is None
    assert [p.underlying for p in report.proposals] == ["CCL"]
    assert report.proposals[0].direction == "bullish"
    assert alerts == []

    url, kwargs = calls[0]
    assert url == proposer.DEEPSEEK_URL
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = kwargs["json"]
    assert body["model"] == "deepseek-v4-pro"  # config/config.json llm.model
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == proposer.DEEPSEEK_MAX_TOKENS
    system, user = body["messages"]
    assert system["role"] == "system"
    assert "json" in system["content"].lower()  # DeepSeek's json_object precondition
    assert "never mention a specific strike" in system["content"]
    assert user["role"] == "user"
    assert json.loads(user["content"])["phase"] == "credit_spreads_only"


def test_env_model_overrides_config(monkeypatch):
    monkeypatch.setenv("OA_DEEPSEEK_MODEL", "deepseek-v4-flash")
    calls = _post_returning(monkeypatch, [FakeResponse(200, _completion('{"proposals": []}'))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.proposals == []
    assert calls[0][1]["json"]["model"] == "deepseek-v4-flash"
    assert report.model == "deepseek-v4-flash"


def test_missing_key_fails_closed_without_calling_the_api(monkeypatch, alerts):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setattr(proposer.requests, "post", lambda *a, **k: pytest.fail("must not call the API"))

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False
    assert report.proposals == []
    assert report.attempts == 1  # config errors are not retried
    assert "DEEPSEEK_API_KEY" in report.error
    assert len(alerts) == 1 and "NO TRADES" in alerts[0] and "DEEPSEEK_API_KEY" in alerts[0]


def test_bad_key_is_not_retried(monkeypatch, alerts):
    calls = _post_returning(monkeypatch, [FakeResponse(401, None, '{"error":"invalid key"}')])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert len(calls) == 1 and report.attempts == 1
    assert "HTTP 401" in report.error
    assert len(alerts) == 1


def test_server_error_is_retried_then_fails_closed(monkeypatch, alerts):
    calls = _post_returning(monkeypatch, [FakeResponse(500, None, "upstream down")])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert len(calls) == 3 and report.attempts == 3
    assert "HTTP 500" in report.error
    assert len(alerts) == 1  # one page, not one per attempt


def test_transient_error_then_success_does_not_alert(monkeypatch, alerts):
    calls = _post_returning(
        monkeypatch,
        [FakeResponse(503, None, "busy"), FakeResponse(200, _completion(json.dumps(GOOD)))],
    )

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.attempts == 2 and len(calls) == 2
    assert [p.underlying for p in report.proposals] == ["CCL"]
    assert alerts == []


def test_truncated_reply_is_rejected_not_half_used(monkeypatch, alerts):
    _post_returning(monkeypatch, [FakeResponse(200, _completion(json.dumps(GOOD), finish="length"))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert "truncated" in report.error


def test_invalid_json_is_rejected(monkeypatch, alerts):
    _post_returning(monkeypatch, [FakeResponse(200, _completion("I think CCL looks good"))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert "invalid" in report.error.lower()


def test_json_without_a_proposals_list_is_rejected(monkeypatch, alerts):
    _post_returning(monkeypatch, [FakeResponse(200, _completion('{"ideas": []}'))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []


def test_malformed_items_are_dropped_not_guessed(monkeypatch):
    payload = {
        "proposals": [
            GOOD["proposals"][0],
            {**GOOD["proposals"][0], "underlying": "AAL", "conviction": 1.5},
            {**GOOD["proposals"][0], "underlying": "T", "strategy_type": "iron_condor"},
            {"underlying": "F"},
        ]
    }
    _post_returning(monkeypatch, [FakeResponse(200, _completion(json.dumps(payload)))])

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True
    assert [p.underlying for p in report.proposals] == ["CCL"]


def test_propose_wrapper_returns_only_the_proposals(monkeypatch):
    _post_returning(monkeypatch, [FakeResponse(200, _completion(json.dumps(GOOD)))])

    assert [p.underlying for p in proposer.propose(BUNDLE)] == ["CCL"]


def test_journal_row_carries_the_call_outcome_not_the_proposals():
    report = proposer.ProposeReport(
        provider="deepseek", model="deepseek-v4-pro", ok=False, attempts=3, latency_s=12.5,
        error="RuntimeError: DeepSeek HTTP 500: upstream down",
    )

    row = report.as_journal_row("cycle-1", "2026-09-02T14:15:40+00:00")

    assert row == {
        "kind": "proposer_result",
        "cycle_id": "cycle-1",
        "ts": "2026-09-02T14:15:40+00:00",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "ok": False,
        "proposals": 0,
        "attempts": 3,
        "latency_s": 12.5,
        "error": "RuntimeError: DeepSeek HTTP 500: upstream down",
    }


def test_unknown_provider_fails_closed(monkeypatch, alerts):
    monkeypatch.setenv("OA_LLM_PROVIDER", "gpt")
    monkeypatch.setattr(proposer.requests, "post", lambda *a, **k: pytest.fail("must not call the API"))

    report = proposer.propose_report(BUNDLE)

    assert report.ok is False and report.proposals == []
    assert report.attempts == 1
    assert "unknown OA_LLM_PROVIDER" in report.error
    assert len(alerts) == 1


# --- Claude Code CLI (Mac only) ---------------------------------------------


def test_claude_cli_path_uses_structured_output_and_not_api_key(monkeypatch):
    calls = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({"structured_output": GOOD})

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return Completed()

    monkeypatch.setenv("OA_LLM_PROVIDER", "claude_cli")
    monkeypatch.setenv("OA_CLAUDE_CLI", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    monkeypatch.setattr(
        proposer.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude-test" else None,
    )
    monkeypatch.setattr(proposer.subprocess, "run", fake_run)
    monkeypatch.setattr(proposer.requests, "post", lambda *a, **k: pytest.fail("CLI path must not hit HTTP"))

    report = proposer.propose_report(BUNDLE)

    assert report.ok is True and report.provider == "claude_cli"
    assert report.proposals[0].underlying == "CCL"
    assert calls["command"][0] == "/usr/local/bin/claude"
    assert "--json-schema" in calls["command"]
    assert "--no-session-persistence" in calls["command"]
    assert "ANTHROPIC_API_KEY" not in calls["kwargs"]["env"]


def test_claude_cli_missing_fails_closed(monkeypatch, alerts, tmp_path):
    monkeypatch.setenv("OA_LLM_PROVIDER", "claude_cli")
    monkeypatch.setenv("OA_CLAUDE_CLI", "missing-claude")
    monkeypatch.setattr(proposer.shutil, "which", lambda name: None)
    # The last fallback is ~/.npm-global/bin/claude, which EXISTS on the Mac:
    # without this the test silently runs the real CLI.
    monkeypatch.setattr(proposer.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(proposer.subprocess, "run", lambda *a, **k: pytest.fail("must not run a real CLI"))

    assert proposer.propose(BUNDLE) == []
    assert len(alerts) == 1 and "Claude CLI" in alerts[0]
