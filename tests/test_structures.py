import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.structures import (
    Leg,
    Structure,
    classify_vanished,
    load_open,
    reconcile,
    record_closed,
    record_opened,
)


def make_structure(structure_id="abc123", strategy_type="credit_spread"):
    return Structure(
        structure_id=structure_id,
        underlying="AAPL",
        strategy_type=strategy_type,
        contracts=2,
        entry_net=1.10,
        legs=[
            Leg("AAPL250815P00095000", "short", "put", 95.0, "2025-08-15"),
            Leg("AAPL250815P00092000", "long", "put", 92.0, "2025-08-15"),
        ],
        opened_ts="2025-07-03T14:00:00+00:00",
        order_ids=["ord-1"],
    )


def test_open_close_roundtrip(tmp_path):
    path = str(tmp_path / "structures.jsonl")
    record_opened(make_structure("s1"), path=path)
    record_opened(make_structure("s2"), path=path)
    assert {s.structure_id for s in load_open(path)} == {"s1", "s2"}

    record_closed("s1", reason="profit target", pnl_usd=110.0, path=path)
    remaining = load_open(path)
    assert [s.structure_id for s in remaining] == ["s2"]
    # legs survive the roundtrip with types intact
    assert remaining[0].legs[0].strike == 95.0
    assert remaining[0].legs[0].side == "short"


def test_load_open_empty_when_no_file(tmp_path):
    assert load_open(str(tmp_path / "missing.jsonl")) == []


def test_reconcile_splits_vanished_structures():
    s1, s2 = make_structure("s1"), make_structure("s2")
    live = {"AAPL250815P00095000", "AAPL250815P00092000"}  # s1+s2 legs identical symbols
    intact, vanished = reconcile([s1, s2], live)
    assert len(intact) == 2 and not vanished

    intact, vanished = reconcile([s1], {"AAPL250815P00092000"})  # short leg gone (assigned)
    assert not intact and [s.structure_id for s in vanished] == ["s1"]


def test_order_ids_survive_roundtrip_and_default_empty(tmp_path):
    path = str(tmp_path / "structures.jsonl")
    record_opened(make_structure("s1"), path=path)
    assert load_open(path)[0].order_ids == ["ord-1"]
    # pre-upgrade events (no order_ids key) load as empty list, not a crash
    with open(path) as fh:
        import json
        event = json.loads(fh.readline())
    del event["order_ids"]
    event["structure_id"] = "legacy"
    with open(path, "a") as fh:
        fh.write(json.dumps(event) + "\n")
    legacy = next(s for s in load_open(path) if s.structure_id == "legacy")
    assert legacy.order_ids == []


def test_classify_vanished_pending_while_order_working():
    # unfilled limit order = the 2026-07-07 false-alarm shape
    assert classify_vanished([{"status": "new", "filled_qty": 0.0}]) == "pending"
    assert classify_vanished([{"status": "accepted", "filled_qty": 0.0}]) == "pending"
    # partial fill still working — don't declare anything yet
    assert classify_vanished([{"status": "partially_filled", "filled_qty": 3.0}]) == "pending"
    # covered straddle: one leg filled, the other still working -> pending
    assert classify_vanished(
        [{"status": "filled", "filled_qty": 8.0}, {"status": "new", "filled_qty": 0.0}]
    ) == "pending"


def test_classify_vanished_never_filled_when_all_orders_dead_with_zero_fills():
    assert classify_vanished([{"status": "expired", "filled_qty": 0.0}]) == "never_filled"
    assert classify_vanished([{"status": "canceled", "filled_qty": 0.0}]) == "never_filled"
    assert classify_vanished(
        [{"status": "canceled", "filled_qty": 0.0}, {"status": "rejected", "filled_qty": 0.0}]
    ) == "never_filled"


def test_classify_vanished_gone_when_filled_or_no_info():
    # order filled, position missing anyway -> real assignment/manual-close alert
    assert classify_vanished([{"status": "filled", "filled_qty": 8.0}]) == "gone"
    # canceled AFTER a partial fill: shares existed, now missing -> alert
    assert classify_vanished([{"status": "canceled", "filled_qty": 2.0}]) == "gone"
    # no order info (pre-upgrade structure or lookup failure) -> stay LOUD
    assert classify_vanished([]) == "gone"
