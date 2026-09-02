"""Alpaca CLI transport for the broker adapter (hackathon requirement, 2026-09-01).

The Alpaca AI Trading Agents Hackathon requires the agent to reach Alpaca's
Trading API through the official MCP server or the official CLI. This module
wraps the CLI (github.com/alpacahq/cli, a single static Go binary) so that
`harness/alpaca_glue.PaperClient` can route every ACCOUNT / POSITION / ORDER /
CLOCK call through `alpaca ...` instead of alpaca-py when
OA_BROKER_TRANSPORT=cli. Market data (option chains via the Public.com
sidecar, stock bars via the AlpacaRelay proxy) is untouched.

Design rules:
- Paper by construction: the CLI defaults to paper-api.alpaca.markets and we
  never pass ALPACA_LIVE_TRADE. The caller's ALPACA_PAPER=true gate still runs.
- Explicit environment: cron does not inherit the container env, so the two
  keys are passed on the subprocess env from the PaperClient, never read from
  the ambient process. ALPACA_PROFILE is stripped so a stray saved profile can
  never redirect an order.
- Fail CLOSED, no silent SDK fallback: a missing binary, a non-zero exit, or
  non-JSON output raises CliError. A silent fallback would make the "CLI in the
  order path" claim false and would hide a broken container.
- Every call is journaled to data/cli_calls.jsonl (argv without secrets, exit
  code, latency, ok/error, order id when present) so the dashboard and the
  write-up can prove the path was used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.env import ROOT, env

CLI_CALLS_LOG = ROOT / "data" / "cli_calls.jsonl"
DEFAULT_TIMEOUT_S = 30
TRANSPORT_ENV = "OA_BROKER_TRANSPORT"
BINARY_ENV = "OA_ALPACA_CLI"


class CliError(RuntimeError):
    """The CLI could not be run or returned an error. Never swallowed here."""


def transport() -> str:
    """'cli' or 'sdk'. Unknown values fall back to 'sdk' (the historical path)."""
    raw = (env(TRANSPORT_ENV, "sdk") or "sdk").strip().lower()
    return "cli" if raw == "cli" else "sdk"


def cli_enabled() -> bool:
    return transport() == "cli"


def cli_binary() -> str | None:
    """Absolute path of the alpaca binary, or None if it is not installed."""
    configured = env(BINARY_ENV, "alpaca") or "alpaca"
    if os.path.sep in configured:
        return configured if os.access(configured, os.X_OK) else None
    return shutil.which(configured)


def _journal(row: dict[str, Any]) -> None:
    try:
        CLI_CALLS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(CLI_CALLS_LOG, "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError:
        pass  # journaling must never take the trading path down


def _summary(payload: Any) -> dict[str, Any]:
    """Small, secret-free digest of a CLI result for the journal."""
    if isinstance(payload, dict):
        keep = {k: payload.get(k) for k in ("id", "client_order_id", "status", "symbol", "order_class", "is_open") if k in payload}
        return keep or {"keys": sorted(payload.keys())[:8]}
    if isinstance(payload, list):
        return {"rows": len(payload)}
    return {"type": type(payload).__name__}


def run_cli(
    args: list[str],
    *,
    key_id: str,
    secret_key: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    expect_json: bool = True,
) -> Any:
    """Run `alpaca <args> -q`, return the parsed JSON (or None for empty
    bodies such as a 204 cancel). Raises CliError on any failure."""
    binary = cli_binary()
    started = time.monotonic()
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "argv": ["alpaca", *args],
    }
    if binary is None:
        row.update(ok=False, exit_code=None, ms=0, error="alpaca CLI binary not found")
        _journal(row)
        raise CliError("alpaca CLI binary not found on PATH (set OA_ALPACA_CLI or install it)")

    child_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "ALPACA_API_KEY": key_id,
        "ALPACA_SECRET_KEY": secret_key,
    }
    # The CLI's own HTTP timeout must be SHORTER than our subprocess timeout,
    # otherwise Python gives up first and an accepted order looks like a failure.
    cli_http_timeout = max(5, int(timeout_s) - 10)
    argv = [binary, *args, "-q", "--timeout", str(cli_http_timeout)]
    try:
        proc = subprocess.run(
            argv, env=child_env, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired:
        row.update(ok=False, exit_code=None, ms=int((time.monotonic() - started) * 1000),
                   error=f"timeout after {timeout_s}s")
        _journal(row)
        raise CliError(f"alpaca {' '.join(args)} timed out after {timeout_s}s")
    except OSError as e:
        row.update(ok=False, exit_code=None, ms=int((time.monotonic() - started) * 1000), error=str(e))
        _journal(row)
        raise CliError(f"alpaca {' '.join(args)} could not start: {e}") from e

    ms = int((time.monotonic() - started) * 1000)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = err or out or "no output"
        row.update(ok=False, exit_code=proc.returncode, ms=ms, error=detail[:500])
        _journal(row)
        raise CliError(f"alpaca {' '.join(args)} exited {proc.returncode}: {detail[:500]}")

    payload: Any = None
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as e:
            row.update(ok=False, exit_code=0, ms=ms, error=f"non-JSON stdout: {out[:200]}")
            _journal(row)
            raise CliError(f"alpaca {' '.join(args)} returned non-JSON output: {out[:200]}") from e
    elif expect_json:
        row.update(ok=False, exit_code=0, ms=ms, error="empty stdout")
        _journal(row)
        raise CliError(f"alpaca {' '.join(args)} returned an empty body")

    # The CLI reports usage/API errors as {"code":..,"error":..} with a
    # non-zero exit, but guard the body too: an error-shaped success is not
    # a result.
    if isinstance(payload, dict) and payload.get("error") and "id" not in payload:
        row.update(ok=False, exit_code=0, ms=ms, error=str(payload.get("error"))[:500])
        _journal(row)
        raise CliError(f"alpaca {' '.join(args)}: {payload.get('error')}")

    row.update(ok=True, exit_code=0, ms=ms, result=_summary(payload))
    _journal(row)
    return payload


def recent_calls(limit: int = 20) -> list[dict[str, Any]]:
    """Last N journal rows, newest last (dashboard / verification helper)."""
    try:
        with open(CLI_CALLS_LOG) as f:
            lines = f.readlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for ln in lines[-limit:]:
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows
