from research_credit_spread_history import _et, load_trades


def test_et_conversion_is_explicitly_new_york():
    assert _et("2026-07-09T14:15:25+00:00") == ("2026-07-09", "10:15")


def test_load_trades_excludes_non_credit_spreads_and_infers_direction(tmp_path):
    (tmp_path / "structures.jsonl").write_text(
        '{"event":"opened","structure_id":"c1","underlying":"CCL",'
        '"strategy_type":"credit_spread","contracts":3,"entry_net":0.29,'
        '"legs":[{"side":"short","right":"put","strike":24},'
        '{"side":"long","right":"put","strike":22.5}],'
        '"opened_ts":"2026-07-09T14:15:25+00:00"}\n'
        '{"event":"closed","structure_id":"c1","reason":"target",'
        '"pnl_usd":45,"ts":"2026-07-28T15:40:03+00:00"}\n'
        '{"event":"opened","structure_id":"long1","underlying":"MARA",'
        '"strategy_type":"long_put","contracts":1,"entry_net":2.18,'
        '"legs":[{"side":"long","right":"put","strike":13}],'
        '"opened_ts":"2026-07-07T14:29:30+00:00"}\n',
        encoding="utf-8",
    )

    trades = load_trades(tmp_path)

    assert len(trades) == 1
    assert trades[0].date == "2026-07-09"
    assert trades[0].opened_et == "10:15"
    assert trades[0].closed_et == "11:40"
    assert trades[0].direction == "bullish"
    assert trades[0].width == 1.5
    assert trades[0].profile_match


def test_load_trades_marks_open_and_non_profile_records(tmp_path):
    (tmp_path / "structures.jsonl").write_text(
        '{"event":"opened","structure_id":"s1","underlying":"SOFI",'
        '"strategy_type":"credit_spread","contracts":8,"entry_net":0.11,'
        '"legs":[{"side":"short","right":"put","strike":13.5},'
        '{"side":"long","right":"put","strike":13}],'
        '"opened_ts":"2026-07-29T14:15:21+00:00"}\n',
        encoding="utf-8",
    )

    trades = load_trades(tmp_path)

    assert trades[0].pnl_usd is None
    assert trades[0].closed_et is None
    assert not trades[0].profile_match
