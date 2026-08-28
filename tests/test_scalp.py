"""Unit tests for the 0DTE ORB scalp mode (pure modules; no network).

Covers: intraday signals (opening range, breakout + RVOL gate, session filter),
0DTE ATM selection + liquidity guard, the ScalpRails predicates (incl. env
tighten-only), the exit-decision priority order, and the state/registry stores.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import scalp_registry, scalp_state
from harness.contracts import select_0dte_atm
from harness.risk_rails import (
    ScalpRails,
    active_scalp_rails,
    scalp_daily_loss_ok,
    scalp_entry_window_ok,
    scalp_must_flatten,
    scalp_one_at_a_time_ok,
    scalp_per_trade_budget_ok,
    scalp_trade_count_ok,
)
from harness.scalp_exits import ScalpExitRules, evaluate_scalp_exit
from harness.signals_intraday import (
    breakout_check,
    opening_range,
    regular_session_bars,
    session_vwap,
)

DATE = "2026-07-13"


def _bar(et_time, o, h, l, c, v, et_date=DATE):
    return {
        "ts_utc": f"{et_date}T{et_time}:00+00:00",
        "et_date": et_date,
        "et_time": et_time,
        "o": o, "h": h, "l": l, "c": c, "v": v,
    }


# --------------------------------------------------------------- signals: session filter
def test_regular_session_excludes_extended_hours():
    bars = [
        _bar("09:15", 100, 100, 99, 99, 500),   # premarket -> excluded
        _bar("09:30", 100, 101, 100, 100, 1000),
        _bar("16:05", 100, 100, 99, 99, 500),   # postmarket -> excluded
    ]
    sess = regular_session_bars(bars, DATE)
    assert [b["et_time"] for b in sess] == ["09:30"]


# --------------------------------------------------------------- signals: opening range
def test_opening_range_none_until_enough_bars():
    bars = [_bar("09:30", 100, 101, 100, 100, 1000), _bar("09:31", 100, 102, 100, 101, 1000)]
    assert opening_range(bars, DATE, minutes=3) is None  # only 2 of 3 bars


def test_opening_range_high_low():
    bars = [
        _bar("09:30", 100, 101.5, 99.8, 100.2, 1000),
        _bar("09:31", 100.2, 102.0, 100.0, 101.0, 1000),
        _bar("09:32", 101.0, 101.8, 99.5, 100.5, 1000),
        _bar("09:33", 100.5, 105.0, 100.0, 104.0, 1000),  # outside the range window
    ]
    rng = opening_range(bars, DATE, minutes=3)
    assert rng is not None
    assert rng.high == 102.0 and rng.low == 99.5 and rng.bars == 3


# --------------------------------------------------------------- signals: breakout + rvol
def _range_and_bars(break_close, break_vol):
    bars = [
        _bar("09:30", 100, 101, 100, 100.5, 1000),
        _bar("09:31", 100.5, 101, 100, 100.5, 1000),
        _bar("09:32", 100.5, 101, 100, 100.5, 1000),
        _bar("09:34", 100.5, break_close + 0.5, 100, break_close, break_vol),
    ]
    return bars


def test_breakout_up_with_volume_surge():
    bars = _range_and_bars(break_close=102.0, break_vol=3000)  # rvol 3.0 vs avg 1000
    bo = breakout_check(bars, DATE, range_high=101.0, range_low=100.0, rvol_min=1.5)
    assert bo is not None and bo.direction == "up" and bo.rvol >= 1.5


def test_breakout_down():
    bars = _range_and_bars(break_close=99.0, break_vol=3000)
    bo = breakout_check(bars, DATE, range_high=101.0, range_low=100.0, rvol_min=1.5)
    assert bo is not None and bo.direction == "down"


def test_breakout_rejected_without_volume_surge():
    bars = _range_and_bars(break_close=102.0, break_vol=900)  # below avg -> no surge
    assert breakout_check(bars, DATE, range_high=101.0, range_low=100.0, rvol_min=1.5) is None


def test_no_breakout_inside_range():
    bars = _range_and_bars(break_close=100.5, break_vol=3000)
    assert breakout_check(bars, DATE, range_high=101.0, range_low=100.0, rvol_min=1.5) is None


def test_session_vwap_positive():
    bars = [_bar("09:30", 100, 101, 99, 100, 1000), _bar("09:31", 100, 102, 100, 101, 2000)]
    v = session_vwap(bars, DATE)
    assert v is not None and 99 < v < 102


# --------------------------------------------------------------- 0DTE ATM selection
def _row(strike, bid, ask, right="call"):
    mid = (bid + ask) / 2
    return {"symbol": f"SPY{right[0].upper()}{strike}", "strike": strike, "right": right,
            "bid": bid, "ask": ask, "mid": mid, "spread_pct": (ask - bid) / mid if mid else 1.0}


def test_select_0dte_atm_nearest_strike():
    rows = [_row(748, 3.0, 3.1), _row(752, 2.0, 2.1), _row(755, 1.0, 1.1)]
    c = select_0dte_atm(rows, spot=751.8, right="call", max_spread_pct=0.15)
    assert c is not None and c.strike == 752


def test_select_0dte_atm_spread_guard_skips_wide():
    rows = [_row(752, 1.0, 3.0)]  # spread ~1.0 of mid=2 -> 100%
    assert select_0dte_atm(rows, spot=752, right="call", max_spread_pct=0.15) is None


def test_select_0dte_atm_none_when_empty():
    assert select_0dte_atm([], spot=752, right="put", max_spread_pct=0.15) is None


def test_select_0dte_atm_filters_right():
    rows = [_row(752, 2.0, 2.1, right="put")]
    assert select_0dte_atm(rows, spot=752, right="call", max_spread_pct=0.15) is None


# --------------------------------------------------------------- rails predicates
R = ScalpRails()


def test_budget_predicate():
    assert scalp_per_trade_budget_ok(200, R)[0]
    assert not scalp_per_trade_budget_ok(300, R)[0]  # over 250 cap
    assert not scalp_per_trade_budget_ok(0, R)[0]


def test_trade_count_predicate():
    assert scalp_trade_count_ok(1, R)[0]
    assert not scalp_trade_count_ok(2, R)[0]


def test_daily_loss_predicate():
    # Default rails have the halt DISABLED (0) — never halts, however large the loss.
    assert scalp_daily_loss_ok(-100, R)[0]
    assert scalp_daily_loss_ok(-1000, R)[0]
    # An explicit positive stop still halts at/below the threshold.
    RS = ScalpRails(daily_loss_stop_usd=150)
    assert scalp_daily_loss_ok(-100, RS)[0]
    assert not scalp_daily_loss_ok(-150, RS)[0]
    assert not scalp_daily_loss_ok(-200, RS)[0]


def test_one_at_a_time_predicate():
    assert scalp_one_at_a_time_ok(0, R)[0]
    assert not scalp_one_at_a_time_ok(1, R)[0]


def test_entry_window_and_flatten():
    assert scalp_entry_window_ok("11:29", R)[0]
    assert not scalp_entry_window_ok("11:30", R)[0]
    assert not scalp_must_flatten("15:49", R)
    assert scalp_must_flatten("15:50", R)
    assert scalp_must_flatten("15:59", R)


def test_config_mirrors_hard_scalp_rails():
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "config.json").read_text())
    assert cfg["scalp"]["entry_cutoff_et"] == R.entry_cutoff_et
    assert cfg["scalp"]["max_trades_per_day"] == R.max_trades_per_day


def test_env_overrides_tighten_only(monkeypatch):
    monkeypatch.setenv("OA_SCALP_PER_TRADE_USD", "100")   # tighter -> applied
    monkeypatch.setenv("OA_SCALP_DAILY_LOSS_USD", "500")  # re-enables the (disabled) halt at 500
    monkeypatch.setenv("OA_SCALP_MAX_TRADES", "1")        # tighter -> applied
    r = active_scalp_rails()
    assert r.per_trade_usd_cap == 100
    assert r.daily_loss_stop_usd == 500  # base is 0 (disabled); a positive env re-enables it
    assert r.max_trades_per_day == 1


# --------------------------------------------------------------- exit priority
XR = ScalpExitRules(stop_loss_pct=0.30, profit_target_pct=0.50, theta_cut_minutes=15)


def test_exit_eod_flatten_wins():
    d = evaluate_scalp_exit(entry_price=1.0, current_bid=5.0, minutes_held=1,
                            must_flatten=True, rules=XR)
    assert d.should_close and d.reason == "eod_flatten"


def test_exit_stop_loss():
    d = evaluate_scalp_exit(entry_price=1.0, current_bid=0.69, minutes_held=1,
                            must_flatten=False, rules=XR)
    assert d.should_close and d.reason == "stop_loss"


def test_exit_profit_target():
    d = evaluate_scalp_exit(entry_price=1.0, current_bid=1.51, minutes_held=1,
                            must_flatten=False, rules=XR)
    assert d.should_close and d.reason == "profit_target"


def test_exit_theta_cut():
    d = evaluate_scalp_exit(entry_price=1.0, current_bid=1.0, minutes_held=15,
                            must_flatten=False, rules=XR)
    assert d.should_close and d.reason == "theta_cut"


def test_exit_hold():
    d = evaluate_scalp_exit(entry_price=1.0, current_bid=1.2, minutes_held=5,
                            must_flatten=False, rules=XR)
    assert not d.should_close and d.reason == "hold"


# --------------------------------------------------------------- state store
def test_state_roundtrip_and_count(tmp_path, monkeypatch):
    monkeypatch.setattr(scalp_state, "STATE_ROOT", str(tmp_path / "scalp_state"))
    st = scalp_state.load_state("2026-07-13", ["SPY", "QQQ"])
    assert st["underlyings"]["SPY"]["state"] == "WAITING_FOR_RANGE"
    assert scalp_state.open_scalp_count(st) == 0
    st["underlyings"]["SPY"]["position"] = {"scalp_id": "x", "option_symbol": "SPYC752"}
    scalp_state.save_state(st)
    reloaded = scalp_state.load_state("2026-07-13", ["SPY", "QQQ"])
    assert reloaded["underlyings"]["SPY"]["position"]["scalp_id"] == "x"
    assert scalp_state.open_scalp_count(reloaded) == 1


# --------------------------------------------------------------- registry
def test_registry_open_close(tmp_path, monkeypatch):
    path = str(tmp_path / "scalp_positions.jsonl")
    monkeypatch.setattr(scalp_registry, "SCALP_POSITIONS_PATH", path)
    pos = scalp_registry.ScalpPosition(
        scalp_id="abc", underlying="SPY", option_symbol="SPY260713C00752000",
        right="call", direction="up", qty=2, entry_price=0.84,
    )
    scalp_registry.record_opened(pos, path=path)
    assert len(scalp_registry.load_open(path=path)) == 1
    scalp_registry.record_closed("abc", reason="profit_target", exit_price=1.30, pnl_usd=92.0, path=path)
    assert scalp_registry.load_open(path=path) == []


def test_is_scalp_order():
    assert scalp_registry.is_scalp_order("oas-abc-123")
    assert not scalp_registry.is_scalp_order("oa-abc-123")
    assert not scalp_registry.is_scalp_order(None)
