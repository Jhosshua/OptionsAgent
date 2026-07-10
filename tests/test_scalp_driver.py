"""Integration tests for the scalp DRIVER, execution, isolation, and edge paths —
the money-touching wiring the pure-helper tests don't cover (QAExpert testing
reviewer TST-001..006). A FakeClient stands in for the broker (no network).
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import run_scalp
from harness import scalp_execution, scalp_registry, scalp_state
from harness.risk_rails import ScalpRails
from harness.scalp_exits import ScalpExitRules

DATE = "2026-07-13"


class FakeClient:
    def __init__(self, *, quotes=None, positions=None, chain_rows=None, spot=None,
                 fill_status="filled", fill_price=None):
        self.quotes = quotes or {}
        self.positions = positions if positions is not None else []
        self.chain_rows = chain_rows or []
        self.spot = spot
        self.orders = []      # every submit_single_leg_order call
        self.canceled = []
        self._fill_status = fill_status
        self._fill_price = fill_price
        self._n = 0

    def option_quotes(self, syms):
        return {s: self.quotes.get(s, {"bid": 0.0, "ask": 0.0}) for s in syms}

    def list_positions(self):
        return [{"symbol": s, "asset_class": "us_option", "qty": 1.0,
                 "cost_basis": 0.0, "market_value": 0.0} for s in self.positions]

    def stock_latest_price(self, sym, feed="sip"):
        return self.spot

    def option_chain_0dte(self, u, *, right, spot, strike_pct=0.03):
        return self.chain_rows

    def submit_single_leg_order(self, *, option_symbol, side, qty, limit_price,
                                decision_id, prefix="oa-"):
        self._n += 1
        oid = f"id{self._n}"
        self.orders.append({"id": oid, "symbol": option_symbol, "side": side, "qty": qty,
                            "limit_price": limit_price, "prefix": prefix, "decision_id": decision_id})
        return {"id": oid, "status": "accepted"}

    def get_order(self, oid):
        qty = self.orders[-1]["qty"] if self.orders else 0
        return {"id": oid, "status": self._fill_status, "filled_qty": qty,
                "filled_avg_price": self._fill_price}

    def cancel_order(self, oid):
        self.canceled.append(oid)


@pytest.fixture(autouse=True)
def _fast_and_isolated(tmp_path, monkeypatch):
    # No real sleeps in fill confirmation.
    monkeypatch.setattr(scalp_execution, "_POLL_TRIES", 1)
    monkeypatch.setattr(scalp_execution, "_POLL_SLEEP_S", 0.0)
    # Redirect the registry + scalp decision log to the tmp dir.
    monkeypatch.setattr(scalp_registry, "SCALP_POSITIONS_PATH", str(tmp_path / "scalp_positions.jsonl"))
    monkeypatch.setattr(run_scalp, "SCALP_DECISIONS_PATH", str(tmp_path / "scalp_decisions.jsonl"))
    monkeypatch.setattr(scalp_state, "STATE_ROOT", str(tmp_path / "scalp_state"))


def _bar(et_time, o, h, l, c, v, et_date=DATE):
    return {"ts_utc": f"{et_date}T{et_time}:00+00:00", "et_date": et_date, "et_time": et_time,
            "o": o, "h": h, "l": l, "c": c, "v": v}


def _breakout_bars():
    return [
        _bar("09:30", 100, 101, 100, 100.5, 1000),
        _bar("09:31", 100.5, 101, 100, 100.5, 1000),
        _bar("09:32", 100.5, 101, 100, 100.5, 1000),
        _bar("09:34", 100.5, 102.5, 100, 102.0, 3000),  # breakout up, rvol 3
    ]


def _fresh_blk():
    return {"state": "WAITING_FOR_RANGE", "range_high": None, "range_low": None,
            "last_evaluated_bar_ts": None, "position": None}


CFG = {"range_minutes": 3, "rvol_min": 1.5, "max_spread_pct": 0.15,
       "per_trade_usd": 250, "data_feed": "sip"}
RAILS = ScalpRails()
XR = ScalpExitRules()


# --------------------------------------------------------------- TST-003: execution
def test_submit_scalp_entry_sizes_and_fills():
    from harness.contracts import ScalpContract
    c = ScalpContract(symbol="SPYC", right="call", strike=102, bid=1.9, ask=2.0, mid=1.95, spread_pct=0.05)
    fc = FakeClient(quotes={"SPYC": {"bid": 1.9, "ask": 2.0}}, fill_price=2.0)
    fill = scalp_execution.submit_scalp_entry(fc, contract=c, budget_usd=250, decision_id="d1")
    assert fill is not None and fill.qty == 1 and fill.fill_price == 2.0
    assert fc.orders[-1]["side"] == "buy" and fc.orders[-1]["prefix"] == "oas-"


def test_submit_scalp_entry_below_one_contract_returns_none():
    from harness.contracts import ScalpContract
    c = ScalpContract(symbol="SPYC", right="call", strike=102, bid=4.9, ask=5.0, mid=4.95, spread_pct=0.02)
    fc = FakeClient(quotes={"SPYC": {"bid": 4.9, "ask": 5.0}}, fill_price=5.0)
    # budget 250 / (5.0*100) = 0.5 -> 0 contracts
    assert scalp_execution.submit_scalp_entry(fc, contract=c, budget_usd=250, decision_id="d1") is None


def test_submit_scalp_close_zero_bid_prices_at_tick_floor():
    fc = FakeClient(quotes={"SPYC": {"bid": 0.0, "ask": 0.0}}, fill_price=0.01)
    res = scalp_execution.submit_scalp_close(fc, option_symbol="SPYC", qty=1, decision_id="d1", aggressive=True)
    assert fc.orders[-1]["side"] == "sell" and fc.orders[-1]["limit_price"] == 0.01
    assert res.filled is True


def test_submit_scalp_close_unconfirmed_reports_not_filled():
    fc = FakeClient(quotes={"SPYC": {"bid": 1.0, "ask": 1.1}}, fill_status="new", fill_price=None)
    res = scalp_execution.submit_scalp_close(fc, option_symbol="SPYC", qty=1, decision_id="d1", aggressive=False)
    assert res.filled is False  # never confirmed -> runner keeps IN_TRADE


# --------------------------------------------------------------- TST-001: _manage_open
def _open_pos_blk(entry=1.0, qty=2, sym="SPYC"):
    blk = _fresh_blk()
    blk["state"] = "IN_TRADE"
    blk["position"] = {"scalp_id": "s1", "option_symbol": sym, "right": "call", "direction": "up",
                       "qty": qty, "entry_fill_price": entry,
                       "entry_ts": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                       "entry_order_id": "e1"}
    return blk


def _state_with(blk, sym="SPYC"):
    return {"date": DATE, "trades_today": 1, "realized_pnl_usd": 0.0, "halted": False,
            "halt_reason": None, "underlyings": {"SPY": blk}}


def _mo(fc, blk, state, now_hhmm="11:00"):
    run_scalp._manage_open(fc, "SPY", blk, now_utc=datetime.now(timezone.utc), now_hhmm=now_hhmm,
                           rails=RAILS, exit_rules=XR, state=state, dry=False)


def test_manage_open_profit_target_pnl_and_state():
    blk = _open_pos_blk(entry=1.0, qty=2)
    state = _state_with(blk)
    fc = FakeClient(quotes={"SPYC": {"bid": 1.60, "ask": 1.65}}, positions=["SPYC"], fill_price=1.60)
    _mo(fc, blk, state)
    assert state["realized_pnl_usd"] == pytest.approx(120.0)  # (1.60-1.0)*100*2
    assert blk["position"] is None and blk["state"] == "WATCHING_FOR_BREAK"
    assert state["halted"] is False


def test_manage_open_stop_loss_triggers_daily_halt():
    blk = _open_pos_blk(entry=1.0, qty=2)
    state = _state_with(blk)
    fc = FakeClient(quotes={"SPYC": {"bid": 0.10, "ask": 0.15}}, positions=["SPYC"], fill_price=0.10)
    _mo(fc, blk, state)
    assert state["realized_pnl_usd"] == pytest.approx(-180.0)  # beyond -150 stop
    assert state["halted"] is True and blk["state"] == "DONE"


def test_manage_open_vanished_position_cleared_without_order():
    blk = _open_pos_blk()
    state = _state_with(blk)
    fc = FakeClient(quotes={"SPYC": {"bid": 1.0, "ask": 1.1}}, positions=[])  # not live on broker
    _mo(fc, blk, state)
    assert blk["position"] is None and blk["state"] == "WATCHING_FOR_BREAK"
    assert fc.orders == []  # never tried to sell a non-existent position


def test_manage_open_zero_bid_transient_is_not_a_stop_out():
    blk = _open_pos_blk(entry=1.0)
    state = _state_with(blk)
    fc = FakeClient(quotes={"SPYC": {"bid": 0.0, "ask": 0.0}}, positions=["SPYC"])
    _mo(fc, blk, state, now_hhmm="11:00")  # not EOD
    assert blk["position"] is not None and fc.orders == []  # held, no phantom dump


def test_manage_open_eod_flatten_forces_exit_even_on_zero_bid():
    blk = _open_pos_blk(entry=1.0)
    state = _state_with(blk)
    fc = FakeClient(quotes={"SPYC": {"bid": 0.0, "ask": 0.0}}, positions=["SPYC"], fill_price=0.0)
    _mo(fc, blk, state, now_hhmm="15:55")  # mandatory flatten window
    assert blk["position"] is None and fc.orders[-1]["side"] == "sell"


# --------------------------------------------------------------- TST-002: _try_entry
def _te(fc, blk, state, dry, now_hhmm="10:00"):
    run_scalp._try_entry(fc, "SPY", blk, _breakout_bars(), et_date=DATE, now_hhmm=now_hhmm,
                         now_utc=datetime.now(timezone.utc), cfg_scalp=CFG, rails=RAILS, state=state, dry=dry)


def _entry_client():
    return FakeClient(
        quotes={"SPYC": {"bid": 1.9, "ask": 2.0}},
        chain_rows=[{"symbol": "SPYC", "strike": 102, "right": "call", "bid": 1.9, "ask": 2.0,
                     "mid": 1.95, "spread_pct": 0.05}],
        spot=102.0, fill_price=2.0,
    )


def test_try_entry_dry_run_places_no_order():
    blk = _fresh_blk()
    state = {"date": DATE, "trades_today": 0, "realized_pnl_usd": 0.0, "halted": False,
             "underlyings": {"SPY": blk}}
    fc = _entry_client()
    _te(fc, blk, state, dry=True)
    assert fc.orders == []          # NO live order in a dry run
    assert blk["position"] is None  # not opened
    assert blk["range_high"] == 101 and blk["range_low"] == 100  # range still computed


def test_try_entry_live_opens_position_and_counts_trade():
    blk = _fresh_blk()
    state = {"date": DATE, "trades_today": 0, "realized_pnl_usd": 0.0, "halted": False,
             "underlyings": {"SPY": blk}}
    fc = _entry_client()
    _te(fc, blk, state, dry=False)
    assert blk["state"] == "IN_TRADE" and blk["position"]["option_symbol"] == "SPYC"
    assert state["trades_today"] == 1
    assert fc.orders[-1]["prefix"] == "oas-" and fc.orders[-1]["side"] == "buy"


def test_try_entry_idempotent_per_bar():
    blk = _fresh_blk()
    blk["range_high"] = 101
    blk["range_low"] = 100
    blk["state"] = "WATCHING_FOR_BREAK"
    blk["last_evaluated_bar_ts"] = f"{DATE}T09:34:00+00:00"  # already acted on this candle
    state = {"date": DATE, "trades_today": 0, "realized_pnl_usd": 0.0, "halted": False,
             "underlyings": {"SPY": blk}}
    fc = _entry_client()
    _te(fc, blk, state, dry=False)
    assert fc.orders == [] and blk["position"] is None  # no double entry on the same bar


def test_try_entry_halted_blocks_entry():
    blk = _fresh_blk()
    state = {"date": DATE, "trades_today": 0, "realized_pnl_usd": -200.0, "halted": True,
             "underlyings": {"SPY": blk}}
    fc = _entry_client()
    _te(fc, blk, state, dry=False)
    assert fc.orders == [] and blk["position"] is None


# --------------------------------------------------------------- TST-004: isolation guard
def test_exclude_scalp_symbols_drops_open_scalp(tmp_path, monkeypatch):
    path = str(tmp_path / "sp.jsonl")
    monkeypatch.setattr(scalp_registry, "SCALP_POSITIONS_PATH", path)
    scalp_registry.record_opened(scalp_registry.ScalpPosition(
        scalp_id="s1", underlying="SPY", option_symbol="SPYC0DTE", right="call",
        direction="up", qty=1, entry_price=1.0), path=path)
    live = {"SPYC0DTE", "F250815C00012000"}  # scalp + a seller leg
    out = scalp_registry.exclude_scalp_symbols(live, path=path)
    assert out == {"F250815C00012000"}  # scalp symbol removed, seller leg kept


# --------------------------------------------------------------- TST-006: corrupt state
def test_load_state_corrupt_file_returns_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(scalp_state, "STATE_ROOT", str(tmp_path))
    p = scalp_state.state_path("2026-07-13")
    Path(p).write_text("{not valid json")
    st = scalp_state.load_state("2026-07-13", ["SPY"])
    assert st["underlyings"]["SPY"]["state"] == "WAITING_FOR_RANGE"
    assert st["trades_today"] == 0


# --------------------------------------------------------------- TST-005: 0DTE chain filter
def test_option_chain_0dte_filters_adjusted_and_zero_quote(monkeypatch):
    from harness.alpaca_glue import PaperClient

    today = date.today().strftime("%y%m%d")
    valid = f"SPY{today}C00752000"
    adjusted = f"SPY7{today}C00752000"   # root SPY7 -> not tradable
    zero_bid = f"SPY{today}C00750000"

    class _Q:
        def __init__(self, bid, ask):
            self.bid_price, self.ask_price = bid, ask

    class _Snap:
        def __init__(self, bid, ask):
            self.latest_quote = _Q(bid, ask)

    class _HistClient:
        def get_option_chain(self, req):
            return {valid: _Snap(2.0, 2.1), adjusted: _Snap(2.0, 2.1), zero_bid: _Snap(0.0, 0.0)}

    # PaperClient is a frozen dataclass -> patch the method on the class, not the instance.
    monkeypatch.setattr(PaperClient, "_option_historical_client", lambda self: _HistClient())
    pc = PaperClient(key_id="k", secret_key="s")
    rows = pc.option_chain_0dte("SPY", right="call", spot=752.0)
    syms = {r["symbol"] for r in rows}
    assert syms == {valid}  # adjusted + zero-quote excluded
