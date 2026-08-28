"""Tests for the equity intraday scalper: mined signals (rules A and C), exit
priority, and the tighten-only rails. Pure logic, no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.equity_scalp import (
    evaluate_equity_exit,
    gap_follow_signal,
    morning_fade_signal,
    orphan_equity_positions,
    per_bar_vwap,
)
from harness.risk_rails import EquityScalpRails, active_equity_scalp_rails


def _bars(closes, start="09:30", date="2026-08-28", vol=1000.0):
    """Synthetic session bars with given closes (one per minute from start)."""
    h0, m0 = int(start[:2]), int(start[3:])
    out = []
    for i, c in enumerate(closes):
        t = f"{(h0 + (m0 + i) // 60):02d}:{(m0 + i) % 60:02d}"
        out.append({"et_date": date, "et_time": t, "o": c, "h": c * 1.001,
                    "l": c * 0.999, "c": c, "v": vol})
    return out


def test_morning_fade_short_above_vwap_and_range():
    # first 15 bars trend up hard, then keep climbing: above vwap and range high
    closes = [100.0 + 0.5 * i for i in range(46)]
    sig = morning_fade_signal(_bars(closes))
    assert sig is not None and sig.rule == "morning_fade" and sig.side == "short"
    assert sig.bar_et_time == "10:15"


def test_morning_fade_long_below_vwap_and_range():
    closes = [100.0 - 0.5 * i for i in range(46)]
    sig = morning_fade_signal(_bars(closes))
    assert sig is not None and sig.side == "long"


def test_morning_fade_no_trade_in_middle():
    # oscillating around vwap: never beyond both gates -> no signal
    closes = [100.0 + (0.2 if i % 2 else -0.2) for i in range(46)]
    assert morning_fade_signal(_bars(closes)) is None


def test_morning_fade_needs_full_window():
    closes = [100.0 + 0.5 * i for i in range(30)]
    assert morning_fade_signal(_bars(closes)) is None


def test_gap_follow_requires_big_gap():
    bars = _bars([200.0 + 0.1 * i for i in range(211)])
    assert gap_follow_signal(bars, prev_close=200.0, open_px=200.02) is None  # 0.01%
    sig = gap_follow_signal(bars, prev_close=200.0, open_px=202.5)  # +1.25%
    assert sig is not None and sig.rule == "gap_follow" and sig.side == "long"
    sig = gap_follow_signal(bars, prev_close=200.0, open_px=197.0)  # -1.5%
    assert sig is not None and sig.side == "short"


def test_exit_priority_eod_first():
    rails = EquityScalpRails()
    d = evaluate_equity_exit(side="long", entry_price=100.0, last_price=50.0,  # stop also hit
                             entry_bar_index=0, last_bar_index=10, now_et_hhmm="15:50", rails=rails)
    assert d.should_close and d.reason == "eod_flatten"


def test_exit_stop_adverse_direction():
    rails = EquityScalpRails()
    # long down 1% > 0.7% stop
    d = evaluate_equity_exit(side="long", entry_price=100.0, last_price=99.0,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert d.should_close and d.reason == "stop_loss"
    # short UP 1% is adverse for a short -> stop
    d = evaluate_equity_exit(side="short", entry_price=100.0, last_price=101.0,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert d.should_close and d.reason == "stop_loss"
    # short DOWN 1% is a WIN for a short -> no stop
    d = evaluate_equity_exit(side="short", entry_price=100.0, last_price=99.0,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert not d.should_close


def test_exit_time_exit():
    rails = EquityScalpRails()
    d = evaluate_equity_exit(side="long", entry_price=100.0, last_price=100.5,
                             entry_bar_index=0, last_bar_index=120, now_et_hhmm="12:20", rails=rails)
    assert d.should_close and d.reason == "time_exit"


def test_exit_intrabar_stop_extreme():
    rails = EquityScalpRails()
    # long: bar LOW breaches 0.7% but close recovers -> still a stop (codex P1)
    d = evaluate_equity_exit(side="long", entry_price=100.0, last_price=100.5,
                             bar_low=99.0, bar_high=100.6,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert d.should_close and d.reason == "stop_loss"
    # short: bar HIGH breaches -> stop for the short
    d = evaluate_equity_exit(side="short", entry_price=100.0, last_price=100.2,
                             bar_low=99.8, bar_high=101.0,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert d.should_close and d.reason == "stop_loss"
    # long: adverse low NOT through the stop -> hold
    d = evaluate_equity_exit(side="long", entry_price=100.0, last_price=100.5,
                             bar_low=99.9, bar_high=100.6,
                             entry_bar_index=0, last_bar_index=5, now_et_hhmm="11:00", rails=rails)
    assert not d.should_close


def test_vwap_is_causal():
    bars = _bars([100, 101, 102, 103])
    v = per_bar_vwap(bars)
    assert len(v) == 4
    assert v[0] == (100 * 1.001 + 100 * 0.999 + 100) / 3  # first bar only


def test_rails_env_tighten_only(monkeypatch):
    monkeypatch.setenv("OA_EQUITY_NOTIONAL_USD", "5000")
    monkeypatch.setenv("OA_EQUITY_MAX_TRADES", "1")
    monkeypatch.setenv("OA_EQUITY_DAILY_LOSS_USD", "100")
    monkeypatch.setenv("OA_EQUITY_STOP_PCT", "0.004")
    r = active_equity_scalp_rails()
    assert r.notional_per_trade_usd == 5000
    assert r.max_trades_per_day == 1
    assert r.daily_loss_stop_usd == 100
    assert r.stop_loss_pct == 0.004


def test_rails_env_cannot_loosen(monkeypatch):
    monkeypatch.setenv("OA_EQUITY_NOTIONAL_USD", "500000")   # raise: ignored
    monkeypatch.setenv("OA_EQUITY_MAX_TRADES", "9")
    r = active_equity_scalp_rails()
    base = EquityScalpRails()
    assert r.notional_per_trade_usd == base.notional_per_trade_usd
    assert r.max_trades_per_day == base.max_trades_per_day


def test_orphan_detection():
    state = {"symbols": {"SPY": {"qty": 27, "side": "short"}}}
    broker = [
        {"symbol": "SPY", "asset_class": "us_equity", "qty": -27},
        {"symbol": "QQQ", "asset_class": "us_equity", "qty": 30},   # untracked -> orphan
        {"symbol": "F", "asset_class": "us_equity", "qty": 100},    # not ours -> ignored
        {"symbol": "SPY261128C00700000", "asset_class": "us_option", "qty": 1},
    ]
    orphans = orphan_equity_positions(broker, state)
    assert [o["symbol"] for o in orphans] == ["QQQ"]
    assert orphans[0]["side"] == "long" and orphans[0]["qty"] == 30


def test_orphan_short_qty_sign():
    orphans = orphan_equity_positions(
        [{"symbol": "SPY", "asset_class": "us_equity", "qty": -15}], {"symbols": {}})
    assert orphans and orphans[0]["side"] == "short" and orphans[0]["qty"] == -15
