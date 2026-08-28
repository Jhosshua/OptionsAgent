"""Capture OptionsAgent dashboard tabs via CDP (Chrome blocks IP-host requests,
so we go through localhost)."""
import asyncio
import base64
import json
import os
import urllib.request
import websockets

OUT = os.path.dirname(os.path.abspath(__file__))
TAB_IDS = ["overview", "positions", "trades", "research", "risk", "system"]


def http_json(path):
    req = urllib.request.Request("http://localhost:9222" + path, headers={"Host": "localhost"})
    return json.load(urllib.request.urlopen(req))


async def main():
    targets = http_json("/json/list")
    page = next(t for t in targets if t.get("type") == "page" and "8765" in (t.get("url") or ""))
    ws_url = "ws://localhost:9222/devtools/page/" + page["id"]
    print("page:", page["url"], "->", ws_url)
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        mid = 0

        async def cmd(method, params=None):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Runtime.enable")
        await cmd("Page.navigate", {"url": "http://127.0.0.1:8765/"})
        await asyncio.sleep(4)

        # figure out the actual nav buttons
        btns = await cmd("Runtime.evaluate", {
            "expression": "JSON.stringify([...document.querySelectorAll('button,[data-view],nav a,.nav-item')].map(b=>({t:(b.textContent||'').trim(),v:b.getAttribute('data-view'),c:b.className})))",
            "returnByValue": True,
        })
        print("buttons:", btns["result"]["value"][:2000])

        for tab in TAB_IDS:
            click = (
                f"(() => {{ const b = document.querySelector('[data-view=\"{tab}\"]');"
                f" if (b) b.click(); }})()"
            )
            await cmd("Runtime.evaluate", {"expression": click})
            await asyncio.sleep(1.5)
            shot = await cmd("Page.captureScreenshot", {"format": "png"})
            path = os.path.join(OUT, f"dash_{tab}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print("saved", path)


asyncio.run(main())
