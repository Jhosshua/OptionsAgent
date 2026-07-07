"""Tests cementing the 2026-07-08 strategy pivot (BotResearch run
20260708-0015): premium buyer -> defined-risk premium seller.

If a future change flips the phase or widens spreads back, one of these
fails and forces a conscious decision (the MEMORY.md "never contradict a
logged decision without flagging it" rule, in test form).
"""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import chain_capture
from harness.contracts import OptionQuote, select_credit_spread
from harness.env import allowed_strategies, config
from harness.proposer import SYSTEM_PROMPT


def test_live_phase_is_credit_spreads_only():
    assert config()["phase"] == "credit_spreads_only"
    assert allowed_strategies() == ["credit_spread"]


def test_spread_width_capped_at_2():
    assert config()["spreads"]["max_width_usd"] == 2.0


def test_proposer_prompt_carries_seller_posture():
    assert "put credit spread" in SYSTEM_PROMPT
    assert "call credit spread" in SYSTEM_PROMPT


def _q(right, strike, dte, delta, bid, ask):
    return OptionQuote(
        symbol=f"XYZ{strike}", underlying="XYZ", right=right,
        strike=strike, dte=dte, delta=delta, bid=bid, ask=ask,
    )


def test_credit_spread_rejects_widths_above_cap():
    # Only long leg available is $2.50 below the short -> no $2-wide spread exists.
    chain = [
        _q("put", 20.0, 35, -0.25, bid=0.60, ask=0.70),
        _q("put", 17.5, 35, -0.15, bid=0.30, ask=0.40),
    ]
    assert select_credit_spread(
        chain, direction="bullish", delta_min=0.15, delta_max=0.30,
        dte_min=30, dte_max=45, max_width=2.0,
    ) is None
    # Same chain, baseline $5 cap -> the spread is buildable.
    assert select_credit_spread(
        chain, direction="bullish", delta_min=0.15, delta_max=0.30,
        dte_min=30, dte_max=45, max_width=5.0,
    ) is not None


def test_credit_spread_rejects_nonpositive_crossed_credit():
    # short bid 0.40, long ask 0.45 -> crossed-price credit is -0.05: reject.
    chain = [
        _q("put", 20.0, 35, -0.25, bid=0.40, ask=0.50),
        _q("put", 18.0, 35, -0.15, bid=0.35, ask=0.45),
    ]
    assert select_credit_spread(
        chain, direction="bullish", delta_min=0.15, delta_max=0.30,
        dte_min=30, dte_max=45, max_width=2.0,
    ) is None


def test_chain_snapshot_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(chain_capture, "SNAPSHOT_ROOT", str(tmp_path))
    rows = [{"symbol": "F260807C00012000", "bid": 0.5, "implied_volatility": 0.31}]
    path = chain_capture.write_snapshot("F", rows, day="2026-07-08")
    with gzip.open(path, "rt") as fh:
        back = [json.loads(line) for line in fh]
    assert back == rows


def test_capture_universe_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(chain_capture, "SNAPSHOT_ROOT", str(tmp_path))

    class FakeClient:
        def option_chain_raw(self, underlying):
            if underlying == "BAD":
                raise RuntimeError("boom")
            return [{"symbol": f"{underlying}X", "bid": 1.0}]

    counts = chain_capture.capture_universe(FakeClient(), ["F", "BAD", "T"])
    # one bad chain never blocks the others
    assert counts == {"F": 1, "BAD": -1, "T": 1}
