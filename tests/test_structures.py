import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.structures import Leg, Structure, load_open, reconcile, record_closed, record_opened


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
