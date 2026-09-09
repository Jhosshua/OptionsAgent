from dataclasses import replace
import json

import pytest

from harness import structures, notify, decision_log, execution, dashboard_server
from harness.spread_exit_orders import SpreadExitOrders


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(structures, 'STRUCTURES_PATH', str(tmp_path / 'structures.jsonl'))
    monkeypatch.setattr(dashboard_server, 'STRUCTURES_PATH', tmp_path / 'structures.jsonl')
    monkeypatch.setattr(execution.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(decision_log, 'record', lambda *_args, **_kwargs: None)
    messages = []
    monkeypatch.setattr(notify, 'post', lambda message: messages.append(message) or True)
    s = structures.Structure('s1', 'T', 'credit_spread', 15, .18,
        [structures.Leg('TC28', 'short', 'call', 28, '2026-10-16'),
         structures.Leg('TC30', 'long', 'call', 30, '2026-10-16')],
        '2026-09-02T14:41:23+00:00', ['entry1'])
    structures.record_opened(s)
    return s, SpreadExitOrders(tmp_path / 'pending.json'), messages


class Client:
    def __init__(self):
        self.info = {'status': 'new', 'filled_qty': 0, 'filled_avg_price': None}
        self.submissions = []
        self.cancelled = []
        self.cancel_status = 'canceled'
        self.fail_submit = False

    def submit_mleg_order(self, **kw):
        self.submissions.append(kw)
        if self.fail_submit:
            raise TimeoutError('lost reply')
        return {'id': 'exit' + str(len(self.submissions))}

    def get_order(self, oid):
        return dict(self.info, id=oid)

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        self.info['status'] = self.cancel_status

    def find_exit_order(self, cid, after):
        return {'id': 'exit1'}


def close(m, c, s, reason='profit target reached (56% of credit captured)'):
    m.close(c, s, net=.08, reason=reason, profit_target_pct=.5)


def test_profit_day_order_stays_working_at_target_without_duplicate_or_repeat_alert(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    assert not c.cancelled
    assert c.submissions[0]['limit_price'] == .09
    assert [x['position_intent'] for x in c.submissions[0]['legs']] == ['buy_to_close', 'sell_to_close']
    assert len(messages) == 1 and 'working' in messages[0]
    restarted = SpreadExitOrders(m.path)
    restarted.recover(c)
    close(restarted, c, s)
    assert len(c.submissions) == 1 and len(messages) == 1
    assert structures.load_open()[0].contracts == 15


def test_later_fill_books_actual_price_before_missing_leg_reconciliation(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.info = {'status': 'filled', 'filled_qty': 15, 'filled_avg_price': .07}
    restarted = SpreadExitOrders(m.path)
    restarted.recover(c)
    assert not structures.load_open() and not restarted.pending
    assert '+$165.00' in messages[-1]
    assert '61% of credit captured' in messages[-1]  # Actual fill, not the earlier 56% quote.
    opened, closed = dashboard_server._structure_records()
    assert not opened and closed[-1]['pnl_usd'] == 165 and closed[-1]['contracts'] == 15


def test_partial_terminal_fill_updates_dashboard_and_remaining_exposure_atomically(setup):
    s, m, messages = setup
    c = Client()
    c.info = {'status': 'canceled', 'filled_qty': 4, 'filled_avg_price': .08}
    close(m, c, s)
    assert structures.load_open()[0].contracts == 11
    opened, closed = dashboard_server._structure_records()
    assert opened[0]['contracts'] == 11
    assert closed[-1]['contracts'] == 4 and closed[-1]['pnl_usd'] == 40
    assert '11 spreads remain' in messages[-1]


def test_partial_still_working_is_not_booked_or_resubmitted(setup):
    s, m, messages = setup
    c = Client()
    c.info = {'status': 'partially_filled', 'filled_qty': 4, 'filled_avg_price': .08}
    close(m, c, s)
    m.recover(c)
    close(m, c, s)
    assert len(c.submissions) == 1 and structures.load_open()[0].contracts == 15
    assert m.pending


def test_crash_after_ledger_write_does_not_double_book_or_notify(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    before = m.path.read_text()
    c.info = {'status': 'filled', 'filled_qty': 15, 'filled_avg_price': .08}
    m.recover(c)
    m.path.write_text(before)  # interrupted between ledger event and pending-state cleanup
    n = len(messages)
    SpreadExitOrders(m.path).recover(c)
    assert len(messages) == n
    assert len(dashboard_server._structure_records()[1]) == 1


def test_cancel_pending_does_not_allow_replacement(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.cancel_status = 'pending_cancel'
    close(m, c, s, 'stop loss: confirmed')
    assert c.cancelled == ['exit1'] and len(c.submissions) == 1 and m.pending


def test_fill_during_cancellation_prevents_replacement(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    def cancel(oid):
        c.info = {'status': 'filled', 'filled_qty': 15, 'filled_avg_price': .08}
    c.cancel_order = cancel
    close(m, c, s, 'stop loss: confirmed')
    assert len(c.submissions) == 1 and not structures.load_open()


def test_risk_replaces_profit_only_after_cancel_confirmed_and_partial_accounted(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.info = {'status': 'partially_filled', 'filled_qty': 4, 'filled_avg_price': .08}
    def submit(**kw):
        c.submissions.append(kw)
        c.info = {'status': 'new', 'filled_qty': 0}
        return {'id': 'exit2'}
    c.submit_mleg_order = submit
    m.close(c, s, net=.40, reason='stop loss: confirmed', profit_target_pct=.5)
    assert c.cancelled == ['exit1']
    assert c.submissions[-1]['qty'] == 11 and c.submissions[-1]['limit_price'] == .40
    assert structures.load_open()[0].contracts == 11


def test_lost_submission_response_recovers_by_saved_client_id(setup):
    s, m, messages = setup
    c = Client()
    c.fail_submit = True
    with pytest.raises(TimeoutError):close(m, c, s)
    saved = json.loads(m.path.read_text())['s1']
    assert saved['client_order_id'] == c.submissions[0]['client_order_id']
    restarted = SpreadExitOrders(m.path)
    restarted.recover(c)
    close(restarted, c, s)
    assert len(c.submissions) == 1


def test_unconfirmed_submission_blocks_duplicate(setup):
    s, m, messages = setup
    c = Client()
    c.fail_submit = True
    with pytest.raises(TimeoutError):close(m, c, s)
    c.find_exit_order = lambda *a: None
    m.recover(c)
    close(m, c, s)
    assert len(c.submissions) == 1 and m.pending
    assert 'Another close is blocked' in messages[-1]


@pytest.mark.parametrize('qty,price', [(15,None),(15,float('nan')),(0,.08),(16,.08)])
def test_inconsistent_fill_never_books_or_loses_tracking(setup, qty, price):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.info = {'status': 'filled', 'filled_qty': qty, 'filled_avg_price': price}
    m.recover(c)
    assert structures.load_open()[0].contracts == 15 and m.pending


def test_expired_unfilled_order_keeps_structure_for_next_session(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.info = {'status': 'expired', 'filled_qty': 0}
    m.recover(c)
    assert not m.pending and structures.load_open()[0].contracts == 15


def test_rounding_cannot_weaken_profit_target(setup):
    s, m, messages = setup
    c = Client()
    close(m, c, replace(s, entry_net=.19))
    assert c.submissions[0]['limit_price'] == .09


def test_runner_recovers_fill_before_classifying_missing_legs(setup, monkeypatch):
    import run_exits
    s, m, messages = setup
    c = Client()
    close(m, c, s)
    c.info = {'status': 'filled', 'filled_qty': 15, 'filled_avg_price': .08}
    monkeypatch.setattr(run_exits, 'make_client', lambda: c)
    monkeypatch.setattr(run_exits, 'SpreadExitOrders', lambda: SpreadExitOrders(m.path))
    monkeypatch.setattr(run_exits.exit_state, 'load', lambda: {})
    run_exits.run()
    assert not structures.load_open()
    assert 'Trade closed' in messages[-1]
    assert not any('assignment' in message for message in messages)
