"""Tests for the proposer market-context builder. Pure/no-network."""

from harness import market_context


def _bars(closes, vols=None):
    vols = vols or [1000.0] * len(closes)
    return [{"c": c, "v": v} for c, v in zip(closes, vols)]


def test_too_few_bars_is_unavailable():
    assert market_context.context_from_bars([]) == {"data": "unavailable"}
    assert market_context.context_from_bars(_bars([10.0])) == {"data": "unavailable"}
    assert not market_context.has_data(market_context.context_from_bars([]))


def test_basic_price_and_1d_change():
    ctx = market_context.context_from_bars(_bars([100.0, 110.0]))
    assert ctx["price"] == 110.0
    assert ctx["change_1d_pct"] == 10.0
    assert market_context.has_data(ctx)
    # not enough history for 5d/20d fields
    assert "change_5d_pct" not in ctx
    assert "change_20d_pct" not in ctx


def test_full_window_all_fields():
    # 21 ascending closes 100..120 → last=120
    closes = [100.0 + i for i in range(21)]
    ctx = market_context.context_from_bars(_bars(closes))
    assert ctx["price"] == 120.0
    assert ctx["change_1d_pct"] == _pct(120.0, 119.0)
    assert ctx["change_5d_pct"] == _pct(120.0, 115.0)
    assert ctx["change_20d_pct"] == _pct(120.0, 100.0)
    # 20-day window is closes[-20:] = 101..120
    assert ctx["high_20d"] == 120.0
    assert ctx["low_20d"] == 101.0
    assert ctx["pct_of_20d_range"] == 100.0  # last == high


def test_range_position_midpoint():
    # flat then a value in the middle of the range
    closes = [100.0, 110.0, 105.0]
    ctx = market_context.context_from_bars(_bars(closes))
    assert ctx["high_20d"] == 110.0
    assert ctx["low_20d"] == 100.0
    assert ctx["pct_of_20d_range"] == 50.0  # 105 is halfway between 100 and 110


def test_volume_ratio():
    closes = [100.0] * 5
    vols = [1000.0, 1000.0, 1000.0, 1000.0, 3000.0]  # avg 1400, last 3000
    ctx = market_context.context_from_bars(_bars(closes, vols))
    assert ctx["volume_vs_20d_avg"] == round(3000.0 / (7000.0 / 5), 2)


def test_zero_close_is_dropped_as_bad_data():
    # a 0.0 close is bad data — it's filtered out, so with only one real close
    # left the ticker is "unavailable" rather than reporting a bogus move
    ctx = market_context.context_from_bars(_bars([0.0, 100.0]))
    assert ctx == {"data": "unavailable"}


def test_build_context_fails_open_on_broker_error():
    class Boom:
        def stock_daily_bars(self, symbols):
            raise RuntimeError("data feed down")

    out = market_context.build_context(Boom(), ["F", "T"])
    assert out == {"F": {"data": "unavailable"}, "T": {"data": "unavailable"}}


def test_build_context_mixed_availability():
    class Fake:
        def stock_daily_bars(self, symbols):
            return {"F": _bars([10.0, 11.0])}  # T absent entirely

    out = market_context.build_context(Fake(), ["F", "T"])
    assert out["F"]["price"] == 11.0
    assert out["T"] == {"data": "unavailable"}


def _pct(now, then):
    return round((now - then) / then * 100, 2)
