"""Always-on, read-only dashboard server for OptionsAgent.

The web process is deliberately narrower than the trading process. It exposes
fixed GET/HEAD routes, reads a cached broker snapshot refreshed in a background
thread, and never imports the order execution modules. The dashboard token is
required for all data APIs; /healthz is a deliberately fixed liveness probe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from harness.env import ROOT, active_phase, config, env
from harness.occ import parse_occ_symbol
from harness.risk_rails import active_rails, credit_spread_overfit_decision

log = logging.getLogger("optionsagent.dashboard")

DATA_DIR = ROOT / "data"
DASHBOARD_DIR = ROOT / "dashboard"
STRUCTURES_PATH = DATA_DIR / "structures.jsonl"
DECISIONS_PATH = DATA_DIR / "decisions.jsonl"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_ROWS = 5000
MAX_AUTH_TOKEN_FAILURES = 5
AUTH_BACKOFF_SECONDS = 5.0
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
    """Read a bounded, known data file; never accepts a caller path."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            return []
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as fh:
            for index, line in enumerate(fh):
                if index >= max_rows:
                    break
                if line.strip():
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


def _strategy_label(value: Any) -> str:
    return str(value or "unknown").replace("_", " ").title()


def _position_rows(snapshot: dict[str, Any], open_structures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    structures_by_symbol: dict[str, dict[str, Any]] = {}
    for structure in open_structures:
        for leg in structure.get("legs") or []:
            if leg.get("symbol"):
                structures_by_symbol[leg["symbol"]] = structure
    rows = []
    for position in snapshot.get("positions") or []:
        symbol = str(position.get("symbol") or "")
        structure = structures_by_symbol.get(symbol)
        try:
            parsed = parse_occ_symbol(symbol)
            display_symbol = parsed.underlying
        except ValueError:
            display_symbol = symbol
        rows.append(
            {
                "symbol": symbol,
                "display_symbol": display_symbol,
                "qty": position.get("qty"),
                "market_value": position.get("market_value"),
                "cost_basis": position.get("cost_basis"),
                "strategy": _strategy_label(structure.get("strategy_type")) if structure else "Broker position",
                "status": "open",
                "structure_id": structure.get("structure_id") if structure else None,
            }
        )
    return rows


def _today_pnl(closed: list[dict[str, Any]]) -> float | None:
    today = _now().date()
    values = []
    for row in closed:
        ts = _parse_ts(row.get("ts"))
        pnl = _json_number(row.get("pnl_usd"))
        if ts and ts.date() == today and pnl is not None:
            values.append(pnl)
    return sum(values) if values else 0.0


def _history_metrics(closed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return cumulative known P/L and daily known P/L, excluding unknowns."""
    known = []
    daily: dict[str, float] = {}
    for row in closed:
        ts = _parse_ts(row.get("ts"))
        pnl = _json_number(row.get("pnl_usd"))
        if ts is None or pnl is None:
            continue
        day = ts.date().isoformat()
        daily[day] = daily.get(day, 0.0) + pnl
        known.append((ts, pnl))
    running = 0.0
    curve = [{"date": known[0][0].date().isoformat(), "pnl_usd": 0.0}] if known else []
    for ts, pnl in sorted(known):
        running += pnl
        curve.append({"date": ts.date().isoformat(), "pnl_usd": running})
    daily_rows = [{"date": day, "pnl_usd": value} for day, value in sorted(daily.items())]
    return curve, daily_rows


def _research_summary() -> dict[str, Any]:
    open_structures, closed = _structure_records()
    credit = [row for row in [*closed, *open_structures] if row.get("strategy_type") == "credit_spread"]
    known = [_json_number(row.get("pnl_usd")) for row in credit]
    known = [value for value in known if value is not None and value != 0]
    profile = []
    for row in credit:
        value = _json_number(row.get("pnl_usd"))
        legs = row.get("legs") or []
        if value is None or value == 0 or len(legs) < 2:
            continue
        try:
            direction = "bullish" if next(leg for leg in legs if leg.get("side") == "short").get("right") == "put" else "bearish"
            width = abs(float(legs[0]["strike"]) - float(legs[1]["strike"]))
            matched, _ = credit_spread_overfit_decision(
                underlying=str(row.get("underlying", "")),
                direction=direction,
                width=width,
                net_credit=float(row.get("entry_net", 0)),
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            matched = False
        if matched:
            profile.append(value)
    days = {str(row.get("opened_ts", ""))[:10] for row in credit if row.get("opened_ts")}
    unknown = sum(1 for row in credit if row.get("pnl_usd") is None)
    return {
        "entry_days": len(days),
        "records": len(credit),
        "realized_pnl": sum(known),
        "profile_pnl": sum(profile),
        "unknown_pnl_closes": unknown,
        "rules": [
            "CCL bullish · width ≥ $1.50 · credit ≥ $0.29",
            "SOFI bullish · width ≥ $1.00 · credit ≥ $0.23",
            "F bearish · width ≤ $0.50 · credit ≥ $0.06",
        ],
    }


def build_payload(store: SnapshotStore, route: str) -> dict[str, Any]:
    snapshot = store.get()
    open_structures, closed = _structure_records()
    equity_curve, daily_pnl = _history_metrics(closed)
    stale = snapshot.get("status") != "ok" or _is_stale(snapshot.get("as_of"))
    account = snapshot.get("account") if not stale or snapshot.get("account") else None
    rails = active_rails()
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
            "open_positions_cap": rails.max_concurrent_positions,
            "winner_rules": 3,
            "last_cycle": max((_parse_ts(row.get("ts")) for row in _read_jsonl(DECISIONS_PATH) if row.get("kind") == "cycle_start"), default=None),
            "deployment": "paper / online" if _trading_enabled_from_dotenv() else "paper / disarmed",
            "equity_curve": equity_curve,
        }
    if route == "/api/positions":
        return {**base, "positions": _position_rows(snapshot, open_structures)}
    if route == "/api/trades":
        rows = []
        for row in reversed(closed):
            pnl = _json_number(row.get("pnl_usd"))
            rows.append(
                {
                    "underlying": row.get("underlying", "—"),
                    "strategy": _strategy_label(row.get("strategy_type")),
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
    if route == "/api/research":
        return {**base, **_research_summary()}
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
            },
        }
    if route == "/api/system":
        return {
            **base,
            "phase": active_phase(),
            "provider": env("OA_OPTIONS_DATA_PROVIDER", "alpaca") or "alpaca",
            "trading_enabled": _trading_enabled_from_dotenv(),
            "paper_only": (env("ALPACA_PAPER", "true") or "true").lower() == "true",
        }
    raise KeyError(route)


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, store: SnapshotStore, token: str):
        super().__init__(address, handler)
        self.store = store
        self.token = token
        self.auth_failures: dict[str, tuple[int, float]] = {}
        self.auth_lock = threading.Lock()

    def authorized(self, ip: str, header: str | None) -> bool:
        now = time.monotonic()
        with self.auth_lock:
            if len(self.auth_failures) > 1024:
                self.auth_failures = {
                    key: value
                    for key, value in sorted(self.auth_failures.items(), key=lambda item: item[1][1], reverse=True)[:512]
                }
            failures, blocked_until = self.auth_failures.get(ip, (0, 0.0))
            if blocked_until > now:
                return False
            presented = header[len("Bearer ") :] if header and header.startswith("Bearer ") else ""
            ok = bool(presented) and hmac.compare_digest(presented, self.token)
            if ok:
                self.auth_failures.pop(ip, None)
                return True
            failures += 1
            if failures >= MAX_AUTH_TOKEN_FAILURES:
                self.auth_failures[ip] = (0, now + AUTH_BACKOFF_SECONDS)
            else:
                self.auth_failures[ip] = (failures, 0.0)
            return False


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
            if not self.server.authorized(self.client_address[0], self.headers.get("Authorization")):
                self._send(HTTPStatus.UNAUTHORIZED, b"unauthorized", "text/plain", no_store=True)
                return
            if path not in {"/api/summary", "/api/positions", "/api/trades", "/api/research", "/api/risk", "/api/system"}:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain", no_store=True)
                return
            body = json.dumps(build_payload(self.server.store, path), default=str).encode("utf-8")
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
    token = env("OA_DASHBOARD_TOKEN") or ""
    if len(token.encode("utf-8")) < 32:
        log.error("OA_DASHBOARD_TOKEN missing or shorter than 32 bytes; dashboard refuses to start")
        return
    try:
        port = int(env("PORT", "8080") or "8080")
    except ValueError:
        log.error("PORT is not an integer; dashboard refuses to start")
        return
    store = SnapshotStore()
    store.start()
    httpd = DashboardHTTPServer(("0.0.0.0", port), DashboardHandler, store=store, token=token)
    log.info("dashboard listening on :%d", port)
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
