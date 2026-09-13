"""The alert transport, and the one failure it exists to make loud.

The proposer FAILS CLOSED: a dead agy CLI means no proposals, which means no
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
    assert calls["kwargs"]["json"] == notify.card_payload("hello")
    assert calls["kwargs"]["params"]["with_components"] == "true"
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
    monkeypatch.setenv("OA_LLM_ATTEMPTS", "1")
    monkeypatch.setattr(proposer.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        proposer,
        "_propose_with_agy",
        lambda bundle, **kwargs: (_ for _ in ()).throw(FileNotFoundError("no agy")),
    )
    sent: list[str] = []
    monkeypatch.setattr(notify, "post", lambda msg: sent.append(msg) or True)

    assert proposer.propose({"phase": "x", "allowed_strategies": [], "watchlist": []}) == []
    assert len(sent) == 1, "a dead CLI must produce exactly one page"
    assert "NO TRADES" in sent[0]
    assert "fail-closed" in sent[0].lower()


def test_the_page_cannot_break_the_cycle_if_notify_itself_explodes(monkeypatch):
    monkeypatch.setenv("OA_LLM_ATTEMPTS", "1")
    monkeypatch.setattr(proposer.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        proposer,
        "_propose_with_agy",
        lambda bundle, **kwargs: (_ for _ in ()).throw(FileNotFoundError("no agy")),
    )
    monkeypatch.setattr(
        notify, "post", lambda msg: (_ for _ in ()).throw(RuntimeError("discord down"))
    )
    # Must still degrade to no-trade rather than propagate.
    assert proposer.propose({"phase": "x", "allowed_strategies": [], "watchlist": []}) == []


def test_v2_card_has_one_container_and_a_dashboard_button(monkeypatch):
    monkeypatch.setenv("OA_DASHBOARD_URL", "https://example.com/dashboard")
    payload = notify.card_payload("T closed @everyone")
    assert payload["flags"] == 32768
    assert "content" not in payload and "embeds" not in payload
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(payload["components"]) == 1
    card = payload["components"][0]
    assert card["type"] == 17
    button = card["components"][-1]["components"][0]
    assert button == {"type": 2, "style": 5, "label": "Open dashboard", "url": "https://example.com/dashboard"}


def test_invalid_dashboard_link_falls_back(monkeypatch):
    monkeypatch.setenv("OA_DASHBOARD_URL", "javascript:alert(1)")
    assert notify.dashboard_url() == notify.DEFAULT_DASHBOARD_URL


def test_capacity_message_explains_legs_and_spreads(monkeypatch):
    sent=[]
    monkeypatch.setattr(notify, "post", lambda msg: sent.append(msg))
    notify.trade_vetoed(underlying="MARA", strategy_type="credit_spread", reason="already at max_concurrent_positions (6)")
    assert "6 option-leg slots" in sent[0] and "3 spreads" in sent[0]
