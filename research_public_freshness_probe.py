"""Market-hours probe: is Public's bid/ask real-time or delayed?

Run during the regular session:  python3 research_public_freshness_probe.py
Prints Public vs AlpacaRelay (SIP) quote and trade stamps for SPY, QQQ and
one near-the-money SPY option, then looks up the SIP quote at Public's own
bid timestamp to see whether Public is replaying a 15-minute-old NBBO.
Read-only. Loads .env from the wingspan folder.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

PUB = "https://api.public.com"
tok = requests.post(
    f"{PUB}/userapiauthservice/personal/access-tokens",
    json={"validityInMinutes": 5, "secret": os.environ["PUBLIC_API_SECRET"]},
    timeout=10,
).json()["accessToken"]
PH = {"Authorization": f"Bearer {tok}"}
acct = os.environ.get("PUBLIC_ACCOUNT_ID") or "5OI20801"
RELAY = os.environ["OA_DATA_URL"].rstrip("/")
RH = {"APCA-API-KEY-ID": os.environ["OA_DATA_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["OA_DATA_SECRET_KEY"]}


def public_quote(sym: str, typ: str) -> dict:
    r = requests.post(f"{PUB}/userapigateway/marketdata/{acct}/quotes", headers=PH,
                      json={"instruments": [{"symbol": sym, "type": typ}]}, timeout=10)
    return r.json()["quotes"][0]


def sip(sym: str) -> tuple[dict, dict]:
    q = requests.get(f"{RELAY}/v2/stocks/{sym}/quotes/latest", headers=RH, timeout=10).json()["quote"]
    t = requests.get(f"{RELAY}/v2/stocks/{sym}/trades/latest", headers=RH, timeout=10).json()["trade"]
    return q, t


now = datetime.now(timezone.utc)
print("probe at", now.isoformat(timespec="seconds"))
for sym in ("SPY", "QQQ"):
    p = public_quote(sym, "EQUITY")
    q, t = sip(sym)
    print(f"\n{sym}")
    print(f"  PUBLIC last {p['last']} @ {p['lastTimestamp']} | bid {p['bid']}x{p['bidSize']} ask {p['ask']}x{p['askSize']} @ {p['bidTimestamp']}")
    print(f"  SIP    last {t['p']} @ {t['t'][:19]} | bid {q['bp']}x{q['bs']} ask {q['ap']}x{q['as']} @ {q['t'][:19]}")
    stamp = datetime.fromisoformat(p["bidTimestamp"].replace("Z", "+00:00"))
    lag = (now - stamp).total_seconds()
    print(f"  Public bid stamp is {lag:.0f}s old")
    win = requests.get(f"{RELAY}/v2/stocks/{sym}/quotes", headers=RH, timeout=15,
                       params={"start": (stamp - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                               "end": (stamp + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), "limit": 200}).json()
    hits = [x for x in (win.get("quotes") or []) if abs(x["bp"] - float(p["bid"])) < 1e-6 and abs(x["ap"] - float(p["ask"])) < 1e-6]
    print(f"  SIP quotes within +-1s of that stamp: {len(win.get('quotes') or [])}, exact bid/ask matches: {len(hits)}")

# one near-the-money SPY option, next expiry
exp = requests.post(f"{PUB}/userapigateway/marketdata/{acct}/option-expirations", headers=PH,
                    json={"instrument": {"symbol": "SPY", "type": "EQUITY"}}, timeout=10).json()["expirations"][1]
chain = requests.post(f"{PUB}/userapigateway/marketdata/{acct}/option-chain", headers=PH,
                      json={"instrument": {"symbol": "SPY", "type": "EQUITY"}, "expirationDate": exp}, timeout=20).json()
spot = float(public_quote("SPY", "EQUITY")["last"])
calls = sorted(chain["calls"], key=lambda c: abs(float(c["optionDetails"]["strikePrice"]) - spot) if c.get("optionDetails") else 1e9)
c = calls[0]
print(f"\n{c['instrument']['symbol']} (Public chain)")
print(f"  bid {c['bid']}x{c['bidSize']} ask {c['ask']}x{c['askSize']} @ {c['bidTimestamp']} | last {c['last']} @ {c['lastTimestamp']} | OI {c['openInterest']} vol {c['volume']}")
stamp = datetime.fromisoformat(str(c["bidTimestamp"]).replace("Z", "+00:00"))
print(f"  option bid stamp is {(now - stamp).total_seconds():.0f}s old")
print("\nVerdict rule: stamps under ~5s old and exact SIP matches at the stamp = real-time NBBO."
      " Stamps ~900s old = 15-minute delayed. Old stamps with no SIP match = a different (single-venue) feed.")
sys.exit(0)
