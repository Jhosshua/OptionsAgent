from research_scalp_history import _filtered, load_trades


def test_load_trades_pairs_registry_events_and_entry_metadata(tmp_path):
    (tmp_path / "scalp_positions.jsonl").write_text(
        '{"event":"opened","scalp_id":"s1","underlying":"SPY",'
        '"option_symbol":"SPY0","right":"call","direction":"up",'
        '"qty":1,"entry_price":1.0,"opened_ts":"2026-07-31T13:47:00+00:00"}\n'
        '{"event":"closed","scalp_id":"s1","reason":"profit_target",'
        '"exit_price":1.5,"pnl_usd":50,"ts":"2026-07-31T14:05:00+00:00"}\n',
        encoding="utf-8",
    )
    (tmp_path / "scalp_decisions.jsonl").write_text(
        '{"kind":"scalp_open","decision_id":"s1","rvol":2.1}\n',
        encoding="utf-8",
    )

    trades = load_trades(tmp_path)

    assert len(trades) == 1
    assert trades[0].date == "2026-07-31"
    assert trades[0].opened_et == "09:47"
    assert trades[0].closed_et == "10:05"
    assert trades[0].rvol == 2.1
    assert trades[0].pnl_usd == 50


def test_filtered_cutoff_is_strict_and_preserves_realized_pnl(tmp_path):
    (tmp_path / "scalp_positions.jsonl").write_text(
        '{"event":"opened","scalp_id":"before","underlying":"SPY",'
        '"option_symbol":"SPY0","right":"call","direction":"up",'
        '"qty":1,"entry_price":1.0,"opened_ts":"2026-07-31T15:29:00+00:00"}\n'
        '{"event":"closed","scalp_id":"before","reason":"x",'
        '"exit_price":1.5,"pnl_usd":50,"ts":"2026-07-31T15:30:00+00:00"}\n'
        '{"event":"opened","scalp_id":"at","underlying":"SPY",'
        '"option_symbol":"SPY1","right":"call","direction":"up",'
        '"qty":1,"entry_price":1.0,"opened_ts":"2026-07-31T15:30:00+00:00"}\n'
        '{"event":"closed","scalp_id":"at","reason":"x",'
        '"exit_price":1.5,"pnl_usd":50,"ts":"2026-07-31T15:31:00+00:00"}\n',
        encoding="utf-8",
    )
    (tmp_path / "scalp_decisions.jsonl").write_text(
        '{"kind":"scalp_open","decision_id":"before","rvol":1.5}\n'
        '{"kind":"scalp_open","decision_id":"at","rvol":1.5}\n',
        encoding="utf-8",
    )

    trades = load_trades(tmp_path)

    assert [trade.scalp_id for trade in _filtered(trades, 11 * 60 + 30, 1.5)] == ["before"]


def test_filtered_does_not_treat_unknown_rvol_as_passing(tmp_path):
    (tmp_path / "scalp_positions.jsonl").write_text(
        '{"event":"opened","scalp_id":"unknown","underlying":"SPY",'
        '"option_symbol":"SPY0","right":"call","direction":"up",'
        '"qty":1,"entry_price":1.0,"opened_ts":"2026-07-31T15:29:00+00:00"}\n'
        '{"event":"closed","scalp_id":"unknown","reason":"x",'
        '"exit_price":1.5,"pnl_usd":50,"ts":"2026-07-31T15:30:00+00:00"}\n',
        encoding="utf-8",
    )
    (tmp_path / "scalp_decisions.jsonl").write_text("", encoding="utf-8")

    trades = load_trades(tmp_path)

    assert _filtered(trades, 11 * 60 + 30, 1.5) == []


def test_filtered_daily_cap_keeps_earliest_realized_entries():
    from research_scalp_history import Trade

    trades = [
        Trade("a", "2026-07-31", "09:40", "09:45", "SPY", "up", 1.5, 1, 1.0, 1.5, 50, "x"),
        Trade("b", "2026-07-31", "10:00", "10:05", "SPY", "up", 1.5, 1, 1.0, 1.5, 50, "x"),
        Trade("c", "2026-07-31", "10:20", "10:25", "SPY", "up", 1.5, 1, 1.0, 1.5, 50, "x"),
    ]

    assert [trade.scalp_id for trade in _filtered(trades, 11 * 60 + 30, 1.5, 2)] == ["a", "b"]


def test_filtered_daily_cap_counts_unknown_pnl_and_sorts_entries():
    from research_scalp_history import Trade

    trades = [
        Trade("real-late", "2026-07-31", "10:20", "10:25", "SPY", "up", 1.5, 1, 1.0, 1.5, 50, "x"),
        Trade("unknown-early", "2026-07-31", "09:40", "09:45", "SPY", "up", 1.5, 1, 1.0, None, None, "vanished"),
        Trade("real-middle", "2026-07-31", "10:00", "10:05", "SPY", "up", 1.5, 1, 1.0, 1.5, 50, "x"),
    ]

    selected = _filtered(trades, 11 * 60 + 30, 1.5, 2)

    assert [trade.scalp_id for trade in selected] == ["unknown-early", "real-middle"]
