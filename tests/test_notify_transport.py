"""The alert transport, and the one failure it exists to make loud.

The proposer FAILS CLOSED: no Claude CLI means no proposals, which means no
trades for the whole day, and that is indistinguishable from a genuinely quiet
market unless something says so out loud. These tests pin that it does.
"""

from __future__ import annotations

import pytest

from harness import notify, proposer


class _Resp:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


def _clear(monkeypatch) -> None:
    for key in ("DISCORD_WEBHOOK_URL", "NOTIFY_DISCORD_TOKEN", "NOTIFY_DISCORD_CHANNEL"):
        monkeypatch.delenv(key, raising=False)


def test_webhook_is_used_when_configured(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook.example/abc")
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _Resp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    assert notify.post("hello") is True
    assert calls["url"] == "https://hook.example/abc"
    assert calls["kwargs"]["json"] == {"content": "hello"}
    assert notify.transport_status() == "Discord (webhook)"


def test_bot_token_is_used_when_there_is_no_webhook(monkeypatch):
    """Without this fallback the bot is MUTE, because no webhook is configured
    on Railway — only the fleet's bot token and channel are."""
    _clear(monkeypatch)
    monkeypatch.setenv("NOTIFY_DISCORD_TOKEN", "tok123")
    monkeypatch.setenv("NOTIFY_DISCORD_CHANNEL", "999")
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _Resp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    assert notify.post("hello") is True
    assert calls["url"] == "https://discord.com/api/v10/channels/999/messages"
    assert calls["kwargs"]["headers"]["Authorization"] == "Bot tok123"
    assert notify.transport_status() == "Discord (bot token)"


def test_no_transport_is_reported_not_silently_swallowed(monkeypatch):
    _clear(monkeypatch)
    assert notify.post("hello") is False
    assert "NO DISCORD TRANSPORT" in notify.transport_status()


def test_a_broken_transport_never_raises_into_a_trading_cycle(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook.example/abc")
    monkeypatch.setattr(
        notify.requests, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert notify.post("hello") is False  # logged, not raised


def test_a_dead_cli_pages_instead_of_failing_silently(monkeypatch):
    """The regression this file exists for: three failed attempts used to return
    an empty proposal list and say nothing, so a dead CLI read as a quiet day."""
    # The CLI is no longer the default provider (DeepSeek API since 09-01);
    # pin it so this stays a test of the CLI-dead page.
    monkeypatch.setenv("OA_LLM_PROVIDER", "claude_cli")
    monkeypatch.setenv("OA_CLAUDE_ATTEMPTS", "1")
    monkeypatch.setattr(proposer.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        proposer,
        "_propose_with_claude_cli",
        lambda bundle, **kwargs: (_ for _ in ()).throw(FileNotFoundError("no claude")),
    )
    sent: list[str] = []
    monkeypatch.setattr(notify, "post", lambda msg: sent.append(msg) or True)

    assert proposer.propose({"phase": "x", "allowed_strategies": [], "watchlist": []}) == []
    assert len(sent) == 1, "a dead CLI must produce exactly one page"
    assert "NO TRADES" in sent[0]
    assert "fail-closed" in sent[0].lower()


def test_the_page_cannot_break_the_cycle_if_notify_itself_explodes(monkeypatch):
    # The CLI is no longer the default provider (DeepSeek API since 09-01);
    # pin it so this stays a test of the CLI-dead page.
    monkeypatch.setenv("OA_LLM_PROVIDER", "claude_cli")
    monkeypatch.setenv("OA_CLAUDE_ATTEMPTS", "1")
    monkeypatch.setattr(proposer.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        proposer,
        "_propose_with_claude_cli",
        lambda bundle, **kwargs: (_ for _ in ()).throw(FileNotFoundError("no claude")),
    )
    monkeypatch.setattr(
        notify, "post", lambda msg: (_ for _ in ()).throw(RuntimeError("discord down"))
    )
    # Must still degrade to no-trade rather than propagate.
    assert proposer.propose({"phase": "x", "allowed_strategies": [], "watchlist": []}) == []
