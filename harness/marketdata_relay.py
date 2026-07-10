"""Token-gated read-only HTTP relay that serves the shared market-data feed
(data/marketdata/<date>.jsonl) to other bots — the OptionsAgent analogue of DTA's
orderflow relay. GET-only, Bearer-token auth, filename whitelisted (no path
traversal). Launched from entrypoint.sh ONLY when OA_RELAY_TOKEN is set.

Consumer (any other bot):
    curl -H "Authorization: Bearer $OA_RELAY_TOKEN" \
        https://<optionsagent-domain>/marketdata/2026-07-13.jsonl
Each line is a JSON snapshot: {ts, et_time, symbol, bar{ohlcv}, vwap, opening_range,
rvol_latest, breakout, source, feed}.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("optionsagent.marketdata_relay")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MARKETDATA_ROOT = os.path.join(_DATA_DIR, "marketdata")

# Only a bare date file may be requested — no path traversal, no other files.
_PATH_RE = re.compile(r"^/marketdata/(\d{4}-\d{2}-\d{2})\.jsonl$")


def _authorized(auth_header: str | None, token: str) -> bool:
    if not token:
        return False
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    presented = auth_header[len("Bearer ") :]
    return hmac.compare_digest(presented, token)


def resolve_request(
    method: str, path: str, auth_header: str | None, *, token: str, data_dir: str = MARKETDATA_ROOT
) -> tuple[int, str, bytes]:
    """PURE request handling (unit-testable, no sockets). Returns
    (status_code, content_type, body). Order: method -> auth -> path -> file."""
    if method != "GET":
        return 405, "text/plain", b"method not allowed"
    if not _authorized(auth_header, token):
        return 401, "text/plain", b"unauthorized"
    m = _PATH_RE.match(path)
    if not m:
        return 404, "text/plain", b"not found"
    fpath = os.path.join(data_dir, f"{m.group(1)}.jsonl")
    # Defense in depth: the resolved path must stay inside data_dir.
    if os.path.abspath(fpath).startswith(os.path.abspath(data_dir) + os.sep) is False:
        return 404, "text/plain", b"not found"
    if not os.path.exists(fpath):
        return 404, "text/plain", b"not found"
    with open(fpath, "rb") as fh:
        return 200, "application/x-ndjson", fh.read()


class _Handler(BaseHTTPRequestHandler):
    server_version = "OptionsAgentRelay/1.0"

    def _token(self) -> str:
        return os.environ.get("OA_RELAY_TOKEN", "") or ""

    def do_GET(self):  # noqa: N802 (http.server API)
        status, ctype, body = resolve_request(
            "GET", self.path, self.headers.get("Authorization"), token=self._token()
        )
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the access log quiet + never log the token
        return


def main() -> None:
    token = os.environ.get("OA_RELAY_TOKEN", "") or ""
    if not token:
        log.warning("OA_RELAY_TOKEN not set — relay refuses to start.")
        return
    port = int(os.environ.get("OA_RELAY_PORT", "8399"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    log.info("market-data relay listening on :%d", port)
    httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
