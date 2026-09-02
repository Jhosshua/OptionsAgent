"""Always-on, read-only dashboard server for OptionsAgent.

The web process is deliberately narrower than the trading process. It exposes
fixed GET/HEAD routes, reads a cached broker snapshot refreshed in a background
thread, and never imports the order execution modules. The local server binds
to loopback by default; /healthz is a deliberately fixed liveness probe.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from harness import alpaca_cli, notify, proposer
from harness.env import ROOT, active_phase, config, env
from harness.occ import parse_occ_symbol
from harness.risk_rails import (
    _CREDIT_SPREAD_OVERFIT_RULES,
    active_credit_spread_gate,
    active_equity_scalp_rails,
    active_rails,
)

try:  # stdlib on 3.9+; the dashboard must never fail to start over a tz lookup
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - only if tzdata is missing
    ET = timezone.utc

log = logging.getLogger("optionsagent.dashboard")

DATA_DIR = ROOT / "data"
DASHBOARD_DIR = ROOT / "dashboard"
STRUCTURES_PATH = DATA_DIR / "structures.jsonl"
DECISIONS_PATH = DATA_DIR / "decisions.jsonl"
EQUITY_SCALP_DECISIONS_PATH = DATA_DIR / "equity_scalp_decisions.jsonl"
EQUITY_SCALP_STATE_DIR = DATA_DIR / "equity_scalp_state"
# Memory is bounded by MAX_ARCHIVE_ROWS (a tail deque), so the byte cap is only
# a sanity bound against a runaway file, not a working limit: at ~530 B/row the
# old 2 MB cap would have returned [] for the whole journal after ~265 days and
# rendered a year-old bot as "has not run a cycle yet".
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ROWS = 5000
STALE_AFTER_SECONDS = 120
REFRESH_INTERVAL_SECONDS = 30
BROKER_TIMEOUT_SECONDS = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _json_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_jsonl(path: Path, *, max_rows: int = MAX_ARCHIVE_ROWS) -> list[dict[str, Any]]:
    """Read the LAST max_rows rows of a bounded, known data file; never accepts
    a caller path. Tail, not head: every caller wants the latest cycle or the
    latest trades, so a head cap would freeze the page on day one's data."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            return []
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as fh:
            tail = deque(fh, maxlen=max_rows)
        for line in tail:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows
    except (OSError, UnicodeError):
        return []


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _is_stale(as_of: str | None) -> bool:
    parsed = _parse_ts(as_of)
    return parsed is None or (_now() - parsed).total_seconds() > STALE_AFTER_SECONDS


def _trading_enabled_from_dotenv() -> bool:
    """Cron has no inherited env, so this mirrors the cron scripts' .env read."""
    value = env("OA_TRADING_ENABLED")
    if value is not None:
        return value.strip().lower() == "true"
    env_path = ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OA_TRADING_ENABLED="):
                return line.split("=", 1)[1].strip().strip("\"'").lower() == "true"
    except OSError:
        pass
    return False


class ReadOnlyBroker:
    """Dashboard-only broker facade; no order-capable object leaves this class."""

    def read_snapshot(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        from harness.alpaca_glue import make_client

        client = make_client()
        return client.account_state(), client.list_positions()


class SnapshotStore:
    """Thread-safe cached account snapshot; request handlers never hit Alpaca."""

    def __init__(self, broker_factory: Callable[[], ReadOnlyBroker] = ReadOnlyBroker) -> None:
        self._lock = threading.Lock()
        self._broker_factory = broker_factory
        self._snapshot: dict[str, Any] = {
            "status": "unavailable",
            "as_of": None,
            "consecutive_failures": 0,
            "error": "broker snapshot has not completed",
            "account": None,
            "positions": [],
        }
        self._refresh_state_lock = threading.Lock()
        self._refresh_inflight = False

    def get(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._snapshot))

    def refresh(self) -> None:
        with self._refresh_state_lock:
            if self._refresh_inflight:
                return
            self._refresh_inflight = True
        result: dict[str, Any] | None = None
        error: str | None = None

        def worker() -> None:
            nonlocal result, error
            try:
                account, positions = self._broker_factory().read_snapshot()
                result = {"account": account, "positions": positions}
            except Exception as exc:  # dashboard must not affect cron
                error = type(exc).__name__
            finally:
                with self._refresh_state_lock:
                    self._refresh_inflight = False

        thread = threading.Thread(target=worker, name="dashboard-broker-read", daemon=True)
        thread.start()
        thread.join(BROKER_TIMEOUT_SECONDS)
        if thread.is_alive():
            error = "broker_timeout"
        with self._lock:
            previous_failures = int(self._snapshot.get("consecutive_failures") or 0)
            if result is not None:
                self._snapshot = {
                    "status": "ok",
                    "as_of": _iso_now(),
                    "consecutive_failures": 0,
                    "error": None,
                    **result,
                }
            else:
                self._snapshot["status"] = "stale" if self._snapshot.get("account") else "unavailable"
                self._snapshot["consecutive_failures"] = previous_failures + 1
                self._snapshot["error"] = error or "broker_read_failed"

    def start(self, interval_seconds: int = REFRESH_INTERVAL_SECONDS) -> threading.Thread:
        def loop() -> None:
            while True:
                self.refresh()
                time.sleep(interval_seconds)

        thread = threading.Thread(target=loop, name="dashboard-snapshot-refresh", daemon=True)
        thread.start()
        return thread


def _structure_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reduce structure events by (structure_id, opened_ts), not ID alone."""
    events = _read_jsonl(STRUCTURES_PATH)
    opened: dict[tuple[str, str], dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    for event in events:
        event_name = event.get("event")
        if event_name == "opened" and event.get("structure_id"):
            opened_ts = str(event.get("opened_ts") or event.get("ts") or "")
            opened[(str(event["structure_id"]), opened_ts)] = dict(event, opened_ts=opened_ts)
        elif event_name == "closed" and event.get("structure_id"):
            structure_id = str(event["structure_id"])
            close_ts = _parse_ts(event.get("ts")) or _now()
            candidates = [
                (key, value)
                for key, value in opened.items()
                if key[0] == structure_id and (_parse_ts(value.get("opened_ts")) or _now()) <= close_ts
            ]
            if candidates:
                key, opening = max(candidates, key=lambda pair: pair[1].get("opened_ts", ""))
                closed.append({**opening, **event, "opened_ts": opening.get("opened_ts", "")})
                opened.pop(key, None)
            else:
                closed.append(dict(event))
    return list(opened.values()), closed


def _et_today() -> str:
    return _now().astimezone(ET).date().isoformat()


def _equity_scalp_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair the equity scalper's own append-only journal into open/closed rows.

    The scalper never writes structures.jsonl, so without this the dashboard
    reports zero trades while the engine that is actually trading is working.
    Events are paired per symbol in file order: an eq_open holds the slot until
    the next eq_close for that symbol.
    """
    events = _read_jsonl(EQUITY_SCALP_DECISIONS_PATH)
    # FIFO per symbol: a second eq_open before the first close must not silently
    # overwrite it, or BOTH trades render with the wrong identity.
    pending: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    for event in events:
        symbol = str(event.get("symbol") or "")
        if not symbol:
            continue
        kind = event.get("kind")
        if kind == "eq_open":
            pending.setdefault(symbol, []).append(event)
        elif kind == "eq_close":
            queue = pending.get(symbol) or []
            opening = queue.pop(0) if queue else {}
            closed.append(
                {
                    "underlying": symbol,
                    "strategy_type": "equity_scalp",
                    "rule": opening.get("rule") or event.get("rule"),
                    "side": opening.get("side"),
                    "qty": event.get("qty", opening.get("qty")),
                    "entry_price": event.get("entry", opening.get("entry_price")),
                    "exit_price": event.get("exit"),
                    "pnl_usd": event.get("pnl_usd"),
                    "reason": event.get("reason"),
                    "opened_ts": opening.get("ts"),
                    "ts": event.get("ts"),
                }
            )
    # The scalper mandates a 15:50 ET flatten, so an unpaired open from an
    # earlier day means its close was never journaled, NOT a live position.
    # Carrying it forward would report a phantom scalp open indefinitely.
    today = _et_today()
    open_rows = []
    for symbol, queue in pending.items():
        for row in queue:
            opened = _parse_ts(row.get("ts"))
            if opened is None or opened.astimezone(ET).date().isoformat() != today:
                continue
            open_rows.append(
                {
                    "underlying": symbol,
                    "strategy_type": "equity_scalp",
                    "rule": row.get("rule"),
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "entry_price": row.get("entry_price"),
                    "opened_ts": row.get("ts"),
                }
            )
    return open_rows, closed


def _equity_scalp_day_state(et_date: str | None = None) -> dict[str, Any]:
    """Today's scalper day state; a missing file means the engine has not run."""
    day = et_date or _et_today()
    path = EQUITY_SCALP_STATE_DIR / f"{day}.json"
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _equity_scalp_enabled() -> bool:
    """Mirrors the cron wrapper's .env read; cron inherits no environment."""
    value = env("OA_EQUITY_SCALP_ENABLED")
    if value is not None:
        return value.strip().lower() == "true"
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OA_EQUITY_SCALP_ENABLED="):
                return line.split("=", 1)[1].strip().strip("\"'").lower() == "true"
    except OSError:
        pass
    return False


def _string_list(value: Any) -> list[str]:
    """Coerce a journal field to a list of strings. A bare string must yield []
    and not its own characters, which is what iterating one would give."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _last_cycle_iso() -> str | None:
    """ISO-8601, not str(datetime): the handler's default=str would emit a
    space separator that Date parsing is not required to accept."""
    latest = max(
        (_parse_ts(row.get("ts")) for row in _read_jsonl(DECISIONS_PATH) if row.get("kind") == "cycle_start"),
        default=None,
    )
    return latest.isoformat() if latest else None


def _equity_scalp_summary(open_scalps: list[dict[str, Any]]) -> dict[str, Any]:
    """Today's scalper state. `has_state` false means the runner wrote nothing
    for this ET date; that is a real 'not running' signal, not a zero day."""
    rails = active_equity_scalp_rails()
    state = _equity_scalp_day_state()
    return {
        "enabled": _equity_scalp_enabled(),
        "has_state": bool(state),
        "date": state.get("date") or _et_today(),
        "trades_today": state.get("trades_today", 0) if state else None,
        "max_trades_per_day": rails.max_trades_per_day,
        "realized_today_usd": _json_number(state.get("realized_pnl_usd")) if state else None,
        "daily_loss_stop_usd": rails.daily_loss_stop_usd,
        "halted": bool(state.get("halted")) if state else None,
        "halt_reason": state.get("halt_reason") if state else None,
        "rules_taken_day": _string_list(state.get("rules_taken_day")),
        "open_scalps": len(open_scalps),
    }


def _strategy_label(value: Any) -> str:
    return str(value or "unknown").replace("_", " ").title()


def _position_rows(
    snapshot: dict[str, Any],
    open_structures: list[dict[str, Any]],
    open_scalps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    structures_by_symbol: dict[str, dict[str, Any]] = {}
    for structure in open_structures:
        for leg in structure.get("legs") or []:
            if leg.get("symbol"):
                structures_by_symbol[leg["symbol"]] = structure
    scalps_by_symbol = {str(row.get("underlying")): row for row in (open_scalps or [])}
    rows = []
    for position in snapshot.get("positions") or []:
        symbol = str(position.get("symbol") or "")
        structure = structures_by_symbol.get(symbol)
        scalp = scalps_by_symbol.get(symbol)
        try:
            parsed = parse_occ_symbol(symbol)
            display_symbol = parsed.underlying
        except ValueError:
            display_symbol = symbol
        market_value = _json_number(position.get("market_value"))
        cost_basis = _json_number(position.get("cost_basis"))
        # Alpaca does not return unrealized P/L on this facade; market value
        # minus cost basis is correct for a long AND for a short (whose cost
        # basis is negative sale proceeds).
        unrealized = None if market_value is None or cost_basis is None else market_value - cost_basis
        if structure:
            strategy = _strategy_label(structure.get("strategy_type"))
        elif scalp:
            strategy = f"Equity Scalp · {_strategy_label(scalp.get('rule'))}"
        else:
            strategy = "Broker position"
        rows.append(
            {
                "symbol": symbol,
                "display_symbol": display_symbol,
                "qty": position.get("qty"),
                "market_value": position.get("market_value"),
                "cost_basis": position.get("cost_basis"),
                "unrealized_pnl_usd": unrealized,
                "strategy": strategy,
                "side": scalp.get("side") if scalp else None,
                "entry_price": scalp.get("entry_price") if scalp else None,
                "opened_ts": scalp.get("opened_ts") if scalp else None,
                "status": "open",
                "structure_id": structure.get("structure_id") if structure else None,
            }
        )
    return rows


def _today_pnl(closed: list[dict[str, Any]]) -> float | None:
    """Realized P/L for the current ET trading day. The UTC date rolls at
    20:00 ET, mid-session for a late close, so the comparison must be ET."""
    today = _et_today()
    values = []
    unknown = 0
    for row in closed:
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts.astimezone(ET).date().isoformat() != today:
            continue
        pnl = _json_number(row.get("pnl_usd"))
        if pnl is None:
            unknown += 1
        else:
            values.append(pnl)
    if values:
        return sum(values)
    # Closes today whose P/L is unknown must not render as a flat $0.00 day.
    return None if unknown else 0.0


def _history_metrics(closed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return cumulative known P/L and daily known P/L, excluding unknowns."""
    known = []
    daily: dict[str, float] = {}
    for row in closed:
        ts = _parse_ts(row.get("ts"))
        pnl = _json_number(row.get("pnl_usd"))
        if ts is None or pnl is None:
            continue
        day = ts.astimezone(ET).date().isoformat()
        daily[day] = daily.get(day, 0.0) + pnl
        known.append((ts, pnl))
    known.sort()
    running = 0.0
    # The zero anchor belongs to the day BEFORE the first trade; stamping it
    # with the first trade's own date puts two different values on one date.
    # The curve carries a RUNNING total, so its key is named for that: a plain
    # `pnl_usd` on both arrays cannot be told apart from the per-day figure.
    curve = []
    if known:
        first_day = known[0][0].astimezone(ET).date()
        curve.append({"date": (first_day - timedelta(days=1)).isoformat(), "cumulative_pnl_usd": 0.0})
    for ts, pnl in known:
        running += pnl
        curve.append({"date": ts.astimezone(ET).date().isoformat(), "cumulative_pnl_usd": running})
    daily_rows = [{"date": day, "pnl_usd": value} for day, value in sorted(daily.items())]
    return curve, daily_rows


def _allowed_profiles() -> list[str]:
    """The only (symbol, direction, width, credit) shapes the seller may open,
    rendered from the SAME tuple the rail enforces so the page can never drift
    from the code (a hand-copied list did exactly that before)."""
    rows = []
    for symbol, side, min_credit, min_width, max_width in _CREDIT_SPREAD_OVERFIT_RULES:
        parts = [f"{symbol} {side}"]
        if min_width is not None:
            parts.append(f"width ≥ ${min_width:.2f}")
        if max_width is not None:
            parts.append(f"width ≤ ${max_width:.2f}")
        parts.append(f"credit ≥ ${min_credit:.2f}")
        rows.append(" · ".join(parts))
    return rows


def _rejection_label(record: dict[str, Any]) -> str:
    """Collapse a decision's `outcome` into a sentence a person can act on."""
    outcome = str(record.get("outcome") or "")
    if outcome == "executed":
        return "Opened"
    if outcome == "no_spread_matched_criteria":
        return "No contract passed the delta / DTE / width filters"
    if outcome.startswith("overfit_profile"):
        return "Not one of the allowed profiles"
    if outcome == "vetoed":
        rail = record.get("rail_decision") if isinstance(record.get("rail_decision"), dict) else {}
        return f"Rail veto: {rail.get('reason') or 'unspecified'}"
    if outcome.startswith("skipped_cap"):
        return "Position cap below one contract"
    return outcome.replace("_", " ") or "unknown"


def _seller_cycle_report() -> dict[str, Any]:
    """What the seller did on its most recent cycle: whether the AI call
    itself worked (the `proposer_result` row), how many proposals came back,
    how many opened, and why the rest did not. A cycle with no journaled call
    reports the AI as unknown, never as a clean zero."""
    rows = _read_jsonl(DECISIONS_PATH)
    starts = [row for row in rows if row.get("kind") == "cycle_start" and _parse_ts(row.get("ts"))]
    empty = {"cycle_id": None, "started": None, "ai": None, "proposals": None, "opened": None, "rejections": []}
    if not starts:
        return empty
    last = max(starts, key=lambda row: _parse_ts(row["ts"]))
    cycle_id = last.get("cycle_id")
    if not cycle_id:
        # Without an id we cannot tell which rows belong to this cycle; matching
        # on None would absorb every other id-less row into it.
        return {**empty, "cycle_id": None, "started": _parse_ts(last["ts"]).isoformat()}
    result = next(
        (row for row in rows if row.get("kind") == "proposer_result" and row.get("cycle_id") == cycle_id),
        None,
    )
    decisions = [row for row in rows if row.get("kind") == "decision" and row.get("cycle_id") == cycle_id]
    counts: dict[str, int] = {}
    opened = 0
    for decision in decisions:
        label = _rejection_label(decision)
        if label == "Opened":
            opened += 1
        else:
            counts[label] = counts.get(label, 0) + 1
    ai = None
    if result is not None:
        ai = {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "ok": bool(result.get("ok")),
            "attempts": _json_number(result.get("attempts")),
            "latency_s": _json_number(result.get("latency_s")),
            "error": result.get("error"),
            "ts": result.get("ts"),
        }
    if result is not None:
        # Coerce, never int(): one hand-edited or corrupt row must not take
        # every endpoint down behind a still-green /healthz.
        count = _json_number(result.get("proposals"))
        proposals: int | None = int(count) if count is not None else 0
    elif decisions:
        proposals = len(decisions)
    else:
        proposals = None
    return {
        "cycle_id": cycle_id,
        "started": _parse_ts(last["ts"]).isoformat(),
        "ai": ai,
        "proposals": proposals,
        "opened": opened if proposals is not None else None,
        "rejections": [
            {"reason": reason, "count": count}
            for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def build_payload(store: SnapshotStore, route: str) -> dict[str, Any]:
    snapshot = store.get()
    open_structures, spread_closed = _structure_records()
    open_scalps, scalp_closed = _equity_scalp_records()
    # Both engines trade the same account, so every P/L view spans both.
    closed = spread_closed + scalp_closed
    equity_curve, daily_pnl = _history_metrics(closed)
    stale = snapshot.get("status") != "ok" or _is_stale(snapshot.get("as_of"))
    account = snapshot.get("account") if not stale or snapshot.get("account") else None
    rails = active_rails()
    eq_rails = active_equity_scalp_rails()
    seller = _seller_cycle_report()
    base = {
        "status": snapshot.get("status"),
        "as_of": snapshot.get("as_of"),
        "consecutive_failures": snapshot.get("consecutive_failures", 0),
        "stale": stale,
        "error": snapshot.get("error"),
    }
    if route == "/api/summary":
        return {
            **base,
            "paper": (env("ALPACA_PAPER", "true") or "true").lower() == "true",
            "trading_enabled": _trading_enabled_from_dotenv(),
            "phase": active_phase(),
            "provider": env("OA_OPTIONS_DATA_PROVIDER", "alpaca") or "alpaca",
            "equity_usd": account.get("equity_usd") if account else None,
            "buying_power_usd": account.get("available_options_buying_power_usd") if account else None,
            "today_pnl_usd": _today_pnl(closed),
            "open_spreads": sum(1 for row in open_structures if row.get("strategy_type") == "credit_spread"),
            "open_scalps": len(open_scalps),
            # An unread broker is not an empty book: report unknown, not 0.
            "open_positions": len(snapshot.get("positions") or []) if account else None,
            # NOT rails.max_concurrent_positions: that rail is enforced against
            # a count of OPTION LEGS (harness/positions.py), so pairing it with
            # an all-positions total would show a breach that never happened.
            "spread_positions_cap": rails.max_concurrent_positions,
            "equity_scalp": _equity_scalp_summary(open_scalps),
            "seller_cycle": seller,
            "last_cycle": _last_cycle_iso(),
            "deployment": "paper / online" if _trading_enabled_from_dotenv() else "paper / disarmed",
            "equity_curve": equity_curve,
        }
    if route == "/api/positions":
        return {
            **base,
            "positions_known": account is not None,
            "positions": _position_rows(snapshot, open_structures, open_scalps) if account else [],
        }
    if route == "/api/trades":
        rows = []
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        for row in sorted(closed, key=lambda item: _parse_ts(item.get("ts")) or epoch, reverse=True):
            pnl = _json_number(row.get("pnl_usd"))
            rows.append(
                {
                    "underlying": row.get("underlying", "—"),
                    "strategy": _strategy_label(row.get("strategy_type")),
                    "rule": _strategy_label(row["rule"]) if row.get("rule") else None,
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "entry_price": row.get("entry_price"),
                    "exit_price": row.get("exit_price"),
                    "width": abs(float(row["legs"][0]["strike"]) - float(row["legs"][1]["strike"])) if len(row.get("legs") or []) >= 2 else None,
                    "credit": row.get("entry_net"),
                    "pnl_usd": pnl,
                    "closed_ts": row.get("ts"),
                    "reason": row.get("reason"),
                }
            )
        return {
            **base,
            "trades": rows[:100],
            "daily_pnl": daily_pnl[-30:],
            "unknown_pnl_closes": sum(1 for row in closed if row.get("pnl_usd") is None),
        }
    if route == "/api/risk":
        return {
            **base,
            "phase": active_phase(),
            "rails": {
                "conviction_floor": rails.conviction_floor,
                "max_concurrent_positions": rails.max_concurrent_positions,
                "mandatory_close_dte": rails.dte_mandatory_close,
                "paper_only": True,
                "trading_enabled": _trading_enabled_from_dotenv(),
                "allowed_profiles": _allowed_profiles(),
                # Which gate judges a picker-approved spread, and the absolute
                # per-position dollar cap (None = only the %-of-BP scaling).
                # Both come from the SAME functions the entry cycle uses.
                "credit_spread_gate": active_credit_spread_gate(),
                "max_position_abs_usd": rails.max_position_abs_usd,
                "spread_rules": {
                    "short_delta": [config()["spreads"]["short_delta_min"], config()["spreads"]["short_delta_max"]],
                    "dte": [config()["spreads"]["dte_min"], config()["spreads"]["dte_max"]],
                    "max_width_usd": config()["spreads"]["max_width_usd"],
                },
                "broker_transport": alpaca_cli.transport(),
            },
            "proposer": {"provider": proposer.provider(), "model": proposer.model_name()},
            "equity_scalp_rails": {
                "enabled": _equity_scalp_enabled(),
                "notional_per_trade_usd": eq_rails.notional_per_trade_usd,
                "max_trades_per_day": eq_rails.max_trades_per_day,
                "max_concurrent": eq_rails.max_concurrent,
                "stop_loss_pct": eq_rails.stop_loss_pct,
                "daily_loss_stop_usd": eq_rails.daily_loss_stop_usd,
                "time_exit_minutes": eq_rails.time_exit_minutes,
                "eod_flatten_et": eq_rails.eod_flatten_et,
                "entry_windows": [list(window) for window in eq_rails.entry_windows],
            },
        }
    if route == "/api/system":
        return {
            **base,
            "phase": active_phase(),
            "provider": env("OA_OPTIONS_DATA_PROVIDER", "alpaca") or "alpaca",
            "stock_data_source": "AlpacaRelay proxy" if env("OA_DATA_URL") else "Alpaca direct",
            "trading_enabled": _trading_enabled_from_dotenv(),
            "paper_only": (env("ALPACA_PAPER", "true") or "true").lower() == "true",
            "equity_scalp": _equity_scalp_summary(open_scalps),
            "last_cycle": _last_cycle_iso(),
            "proposer": {
                "provider": proposer.provider(),
                "model": proposer.model_name(),
                "last": seller.get("ai"),
                "cycle": seller,
            },
            "alert_transport": notify.transport_status(),
        }
    raise KeyError(route)


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, store: SnapshotStore):
        super().__init__(address, handler)
        self.store = store


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer
    server_version = "OptionsAgentDashboard/1.0"

    def _send(self, status: int, body: bytes, content_type: str, *, no_store: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._route()

    def do_HEAD(self):  # noqa: N802
        self._route()

    def _route(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send(HTTPStatus.OK, b'{"status":"ok"}', "application/json")
            return
        if path in {"/", "/index.html", "/app.css", "/app.js"}:
            files = {"/": "index.html", "/index.html": "index.html", "/app.css": "app.css", "/app.js": "app.js"}
            target = DASHBOARD_DIR / files[path]
            if not target.is_file() or target.is_symlink():
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8" if target.suffix == ".css" else "application/javascript; charset=utf-8"
            self._send(HTTPStatus.OK, target.read_bytes(), content_type)
            return
        if path.startswith("/api/"):
            if path not in {"/api/summary", "/api/positions", "/api/trades", "/api/risk", "/api/system"}:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain", no_store=True)
                return
            try:
                body = json.dumps(build_payload(self.server.store, path), default=str).encode("utf-8")
            except Exception as exc:  # one bad journal row must fail ONE section, loudly, not drop the socket
                log.exception("payload build failed for %s", path)
                body = json.dumps({"error": f"{type(exc).__name__}: {exc}"[:300]}).encode("utf-8")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, body, "application/json", no_store=True)
                return
            self._send(HTTPStatus.OK, body, "application/json", no_store=True)
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"method not allowed", "text/plain")

    def do_PUT(self):  # noqa: N802
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"method not allowed", "text/plain")

    def do_DELETE(self):  # noqa: N802
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"method not allowed", "text/plain")

    def log_message(self, fmt, *args):
        return


def main() -> None:
    try:
        port = int(env("PORT", "8080") or "8080")
    except ValueError:
        log.error("PORT is not an integer; dashboard refuses to start")
        return
    store = SnapshotStore()
    store.start()
    host = env("OA_DASHBOARD_HOST", "127.0.0.1") or "127.0.0.1"
    httpd = DashboardHTTPServer((host, port), DashboardHandler, store=store)
    log.info("dashboard listening on %s:%d", host, port)
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
