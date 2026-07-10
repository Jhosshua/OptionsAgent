# OptionsAgent shared market-data relay

OptionsAgent fetches SIP 1-minute bars for SPY/QQQ and computes intraday signals.
This relay makes that data available to the **other bots** over a token-gated,
read-only HTTPS GET — the same pattern DTA uses for its orderflow relay, so a
consumer written for one works for the other.

## What it serves

`data/marketdata/<YYYY-MM-DD>.jsonl` on the OptionsAgent Railway volume — one JSON
line per underlying per minute:

```json
{"ts":"2026-07-13T13:34:05Z","et_date":"2026-07-13","et_time":"09:34","symbol":"SPY",
 "bar":{"o":100.5,"h":102.5,"l":100.0,"c":102.0,"v":3000.0},
 "vwap":101.2,"opening_range":{"high":101,"low":100},"rvol_latest":3.0,
 "breakout":"up","source":"optionsagent","feed":"sip"}
```

- `bar` — the latest **closed** 1-minute SIP bar (raw Alpaca OHLCV).
- `vwap` — session VWAP; `opening_range` — the frozen 09:30–09:33 ET high/low;
  `rvol_latest` — latest bar volume / session average; `breakout` — `"up"`/`"down"`/`null`.

## Turning it on (OptionsAgent side)

Two independent switches (both off by default), set as Railway env vars:

- `OA_MARKETDATA_ENABLED=true` — runs the per-minute publisher (writes the jsonl).
- `OA_RELAY_TOKEN=<random-secret>` — starts the relay HTTP server (serves the jsonl).
  Optional `OA_RELAY_PORT` (default `8399`); expose that port with a Railway domain.

Both keys are already in `entrypoint.sh`'s secret allowlist (the 3-touch-point rule).

## Consuming it (any other bot)

```
GET https://<optionsagent-domain>/marketdata/2026-07-13.jsonl
Authorization: Bearer <OA_RELAY_TOKEN>
```

Reference pull-and-cache snippet (stdlib only, fail-open — keep the last good copy
on any error, never block the consumer):

```python
import json, os, time, urllib.request

def pull_marketdata(domain, token, out_dir="data/marketdata_shared"):
    day = time.strftime("%Y-%m-%d")  # use ET in production
    url = f"https://{domain}/marketdata/{day}.jsonl"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        body = urllib.request.urlopen(req, timeout=10).read()
        rows = [json.loads(l) for l in body.splitlines() if l.strip()]  # validate
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, f"{day}.jsonl.tmp")
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, os.path.join(out_dir, f"{day}.jsonl"))
        return rows
    except Exception:
        return None  # keep the previous copy; never crash the caller
```

## Security

GET-only, `Bearer` token compared in constant time, filename whitelisted to a bare
date (`^/marketdata/\d{4}-\d{2}-\d{2}\.jsonl$`) so there is no path traversal, and
the resolved path is asserted to stay inside the data dir. The server never starts
without `OA_RELAY_TOKEN`. It is read-only and touches no trading path.
