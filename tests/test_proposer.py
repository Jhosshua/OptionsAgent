"""Offline tests for the local Claude Code CLI proposer boundary."""

import json

from harness import proposer


def test_propose_uses_cli_structured_output_and_not_api_key(monkeypatch):
    calls = {}

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "structured_output": {
                    "proposals": [
                        {
                            "underlying": "CCL",
                            "strategy_type": "credit_spread",
                            "direction": "bullish",
                            "conviction": 0.8,
                            "thesis": "test",
                        }
                    ]
                }
            }
        )

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return Completed()

    monkeypatch.setenv("OA_CLAUDE_CLI", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    monkeypatch.setattr(
        proposer.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude-test" else None,
    )
    monkeypatch.setattr(proposer.subprocess, "run", fake_run)

    result = proposer.propose({"phase": "credit_spreads_only", "watchlist": []})

    assert result[0].underlying == "CCL"
    assert result[0].direction == "bullish"
    assert calls["command"][0] == "/usr/local/bin/claude"
    assert "--json-schema" in calls["command"]
    assert "--no-session-persistence" in calls["command"]
    assert "ANTHROPIC_API_KEY" not in calls["kwargs"]["env"]


def test_propose_fails_closed_when_cli_is_missing(monkeypatch):
    monkeypatch.setenv("OA_CLAUDE_CLI", "missing-claude")
    monkeypatch.setattr(proposer.shutil, "which", lambda name: None)

    assert proposer.propose({"phase": "credit_spreads_only", "watchlist": []}) == []
