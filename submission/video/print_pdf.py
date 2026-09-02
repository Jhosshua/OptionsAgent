#!/usr/bin/env python3
"""Print OnePager.dc.html to submission/out/Wingspan-OnePager.pdf through the debug Chrome (CDP)."""
import asyncio, base64, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render, websockets

async def main():
    tab = render.http("/json/new?about:blank", "PUT")
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=64*1024*1024) as ws:
        cdp = render.Cdp(ws)
        await cdp.call("Page.enable"); await cdp.call("Runtime.enable")
        await cdp.call("Page.navigate", url=(render.SCENES / "OnePager.dc.html").resolve().as_uri())
        await asyncio.sleep(0.8)
        await cdp.eval("document.fonts.ready.then(() => true)", await_promise=True)
        await cdp.eval("document.getAnimations({subtree:true}).forEach(a => { a.finish && a.finish(); }); true")
        pdf = await cdp.call("Page.printToPDF", printBackground=True, preferCSSPageSize=True,
                             paperWidth=8.5, paperHeight=11, marginTop=0, marginBottom=0, marginLeft=0, marginRight=0)
        out = render.OUT / "Wingspan-OnePager.pdf"
        out.write_bytes(base64.b64decode(pdf["data"]))
        print("wrote", out, out.stat().st_size // 1024, "KB")
    try: render.http(f"/json/close/{tab['id']}")
    except Exception: pass

asyncio.run(main())
