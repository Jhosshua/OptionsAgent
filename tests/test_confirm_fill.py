"""harness.execution.confirm_fill: book what filled, cancel what did not."""

from harness.execution import confirm_fill


class FakeClient:
    def __init__(self, script):
        self.script = list(script)   # successive get_order replies
        self.cancelled = []

    def get_order(self, order_id):
        reply = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return {"id": order_id, **reply}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        # after a cancel the broker reports whatever had filled so far
        self.script = [{"status": "canceled", "filled_qty": self.script[0].get("filled_qty", 0),
                        "filled_avg_price": self.script[0].get("filled_avg_price")}]


def test_full_fill_is_returned_without_cancel():
    c = FakeClient([{"status": "new", "filled_qty": 0}, {"status": "filled", "filled_qty": 15, "filled_avg_price": -0.31}])
    out = confirm_fill(c, "o1", requested=15, tries=5, sleep_s=0)
    assert out["filled_qty"] == 15 and out["status"] == "filled" and out["cancelled_remainder"] is False
    assert c.cancelled == []


def test_partial_fill_cancels_remainder_and_books_the_partial():
    c = FakeClient([{"status": "partially_filled", "filled_qty": 4, "filled_avg_price": -0.30}])
    out = confirm_fill(c, "o2", requested=15, tries=3, sleep_s=0)
    assert out["filled_qty"] == 4 and out["cancelled_remainder"] is True and c.cancelled == ["o2"]


def test_no_fill_cancels_and_returns_zero():
    c = FakeClient([{"status": "new", "filled_qty": 0}])
    out = confirm_fill(c, "o3", requested=15, tries=2, sleep_s=0)
    assert out["filled_qty"] == 0 and out["cancelled_remainder"] is True and c.cancelled == ["o3"]


def test_rejected_order_returns_immediately_without_cancel():
    c = FakeClient([{"status": "rejected", "filled_qty": 0}])
    out = confirm_fill(c, "o4", requested=15, tries=5, sleep_s=0)
    assert out["filled_qty"] == 0 and out["status"] == "rejected" and c.cancelled == []


def test_filled_qty_never_exceeds_requested():
    c = FakeClient([{"status": "filled", "filled_qty": 30}])
    assert confirm_fill(c, "o5", requested=15, tries=1, sleep_s=0)["filled_qty"] == 15
