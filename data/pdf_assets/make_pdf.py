"""Print explainer.html to PDF via the running debug Chrome (CDP)."""
import asyncio
import base64
import json
import urllib.request
import websockets

OUT = "/Users/mo/OptionsAgent/OptionsAgent-Explainer.pdf"
URL = "file:///Users/mo/OptionsAgent/data/pdf_assets/explainer.html"


def http_json(path, method="GET"):
    req = urllib.request.Request("http://localhost:9222" + path,
                                 headers={"Host": "localhost"}, method=method)
    return json.load(urllib.request.urlopen(req))


async def main():
    page = http_json("/json/new?" + URL, method="PUT")
    ws_url = "ws://localhost:9222/devtools/page/" + page["id"]
    async with websockets.connect(ws_url, max_size=256 * 1024 * 1024) as ws:
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
        await asyncio.sleep(5)
        result = await cmd("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
        })
        with open(OUT, "wb") as f:
            f.write(base64.b64decode(result["data"]))
        print("wrote", OUT, len(result["data"]) // 1024, "KB b64")
        # also a PNG of page 1 for layout check
        await cmd("Emulation.setDeviceMetricsOverride",
                  {"width": 1056, "height": 816, "deviceScaleFactor": 1, "mobile": False})
        shot = await cmd("Page.captureScreenshot", {"format": "png"})
        with open("/Users/mo/OptionsAgent/data/pdf_assets/page1_check.png", "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print("page1 check saved")
        await cmd("Target.closeTarget", {"targetId": page["id"]}) if False else None


asyncio.run(main())
