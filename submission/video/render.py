#!/usr/bin/env python3
"""Render the animated scene artboards into the final MP4.

Pipeline: narration (edge-tts) -> scene durations -> frame capture through the
debug Chrome on :9222 (CDP; the scene's CSS animations are paused and seeked
per frame, so the capture is deterministic) -> per-scene MP4 with the audio
padded to the exact scene length (the v2 bug was `-shortest`, which clipped
the last word) -> crossfaded concat.

Usage: python3 submission/video/render.py [--voice=en-US-AndrewMultilingualNeural] [--rate=+12%] [--fps=24]
Needs: the debug Chrome (`bash ~/chrome-debug.sh`-style, port 9222), ffmpeg, edge-tts.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
FRAMES = HERE / "frames"
OUT = HERE.parent / "out"
FPS = 24
XFADE = 0.45          # crossfade into/out of the UI shots (scenes 5-6)
HARD = 0.08           # near-hard cut elsewhere (on the sentence boundary)


def xfade_for(k: int) -> float:
    """Transition length going INTO scene k+1 (1-based scene numbers k -> k+1)."""
    return XFADE if k in (5, 6, 7) else HARD
TAIL = 1.0            # silence after the last spoken word of each scene (plus the lead-in delay)
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
DEFAULT_RATE = "+12%"

# Narration per scene. Short sentences, spoken not read. Keep total ~105 s.
NARRATION = {
    1: "This is Wingspan. An options agent that mostly says no.",
    2: "Point a language model at a brokerage account and it always finds a trade. "
       "Our own first dry run wanted a hundred and seventy eight contracts on one idea. It never says no, and it can't count contracts.",
    3: "So we split the job. The model answers one question: is there a trade, and how sure are you? Code does everything with a dollar sign on it.",
    4: "Then the idea has to survive five gates. Any one of them can kill it. The last one is new: "
       "if our own exit rule would stop the spread out on day one, it dies right here. Most ideas do.",
    5: "The second engine has no AI at all. Two rules on SPY and QQQ, mined from six months of minute bars. "
       "Twenty thousand a trade, two a day, and flat by ten to four.",
    6: "This is the live app. Both engines, one book. From today's run, every idea the model has, and which gate said no, lands in that card. "
       "A no gets logged like a fill.",
    7: "The risk page isn't a copy of the rules. That three thousand comes from the same function the bot calls, so it can't drift.",
    8: "Every order goes out through Alpaca's own command line tool. One process, one JSON reply, logged with its exit code. If the C L I fails, nothing opens.",
    9: "Before the first order we replayed a day of real option chains. Eight of twenty three spreads the open gate would have taken "
       "were already past their own stop. With the liquidity floor: five admitted, zero past the stop.",
    10: None,  # built from live numbers in main()
}

# Cue words: the first matching spoken word sets the CSS variable on the scene, so reveals land on the voice.
CUES = {
    1: {"c-agent": "options"},
    2: {"c-point": "point", "c-finds": "finds", "c-178": "hundred", "c-idea": "idea", "c-never": "never"},
    3: {"c-model": "model", "c-code": "code", "c-code2": "everything", "c-code3": "dollar", "c-code4": "sign"},
    4: {"c-drop": "five", "c-dies": "dies", "c-most": "most"},
    5: {"c-spy": "spy", "c-rules": "rules", "c-fade": "qqq", "c-gap": "mined", "c-twenty": "twenty", "c-twenty2": "trade", "c-two": "two", "c-flat": "flat"},
    6: {"c-ring": "card"},
    7: {"c-ring": "three"},
    8: {"c-json": "json", "c-exit": "exit", "c-fails": "fails"},
    9: {"c-eight": "eight", "c-floor": "liquidity", "c-five": "five", "c-zero": "zero"},
    10: {"c-dash": "dashboard", "c-check": "check"},
}


def results_narration(n: dict) -> str:
    eq = n.get("equity")
    pnl = None if eq is None else eq - 100_000
    if pnl is None:
        money_line = "The account is flat."
    else:
        dollars = int(round(abs(pnl)))
        money_line = ("Flat." if dollars == 0 else f"{'Up' if pnl > 0 else 'Down'} {dollars} dollars.")
    fills = n.get("fills_options") or 0
    fill_line = "No option fills yet." if fills == 0 else f"{fills} option fill{'s' if fills != 1 else ''}."
    return f"Two trading days on a fresh paper account. {money_line} {fill_line} Every idea, and every no, is on the dashboard. Go check it. Thanks for watching."


def word_cues(words_path: Path) -> list[tuple[float, str]]:
    """(start_seconds, normalized word) from the edge-tts WordBoundary dump."""
    import re
    out = []
    for t, w in json.loads(words_path.read_text()):
        for piece in str(w).split():
            out.append((float(t), re.sub(r"[^a-z0-9']", "", piece.lower())))
    return out


def cue_vars(i: int, words_path: Path, lead_in: float) -> dict[str, str]:
    """CSS variables for scene i: first occurrence of each cue word, shifted by the audio lead-in."""
    words = word_cues(words_path)
    vars_: dict[str, str] = {}
    for var, cue in CUES.get(i, {}).items():
        cue_l = cue.lower()
        for t, w in words:
            if w == cue_l or w.startswith(cue_l):
                vars_[var] = f"{t + lead_in:.2f}s"
                break
    return vars_


def http(path: str, method: str = "GET"):
    req = urllib.request.Request("http://localhost:9222" + path, method=method, headers={"Host": "localhost:9222"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


async def narrate(i: int, text: str, voice: str, rate: str) -> Path:
    """Synthesize one scene with edge-tts and keep the per-word timings
    (WordBoundary events, offsets in 100 ns units) next to the mp3."""
    import edge_tts
    mp3 = FRAMES / f"narr-{i:02d}.mp3"
    words_path = FRAMES / f"narr-{i:02d}.words.json"
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append([chunk["offset"] / 1e7, chunk["text"]])
    words_path.write_text(json.dumps(words))
    if mp3.stat().st_size < 1000:
        raise RuntimeError(f"edge-tts produced no audio for scene {i}")
    return mp3


class Cdp:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr: str, await_promise: bool = False):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        return r.get("result", {}).get("value")


async def capture_scene(cdp: Cdp, i: int, dur: float, fps: int, cues: dict[str, str] | None = None) -> int:
    url = (SCENES / f"Scene{i:02d}.dc.html").resolve().as_uri()
    await cdp.call("Page.navigate", url=url)
    await asyncio.sleep(0.4)
    await cdp.eval("document.fonts.ready.then(() => true)", await_promise=True)
    # make every animation deterministic: pause, then seek per frame
    await cdp.eval(f"document.documentElement.style.setProperty('--dur', '{dur:.3f}s'); true")
    for var, val in (cues or {}).items():
        await cdp.eval(f"document.documentElement.style.setProperty('--{var}', '{val}'); true")
    await asyncio.sleep(0.15)
    await cdp.eval("document.getAnimations({subtree:true}).forEach(a => { a.pause(); a.currentTime = 0; }); true")
    frames_dir = FRAMES / f"s{i:02d}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for f in frames_dir.glob("*.jpg"):
        f.unlink()
    total = int(round(dur * fps))
    for k in range(total):
        t_ms = k * 1000.0 / fps
        await cdp.eval(f"document.getAnimations({{subtree:true}}).forEach(a => {{ a.pause(); a.currentTime = {t_ms:.2f}; }}); true")
        shot = await cdp.call("Page.captureScreenshot", format="jpeg", quality=92, fromSurface=True,
                              clip={"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1})
        (frames_dir / f"{k:05d}.jpg").write_bytes(base64.b64decode(shot["data"]))
    return total


def assemble_scene(i: int, dur: float, fps: int, audio: Path) -> Path:
    seg = FRAMES / f"seg-{i:02d}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps), "-i", str(FRAMES / f"s{i:02d}" / "%05d.jpg"),
        "-i", str(audio),
        "-filter_complex", f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={300 if i == 1 else 120}|{300 if i == 1 else 120},apad=whole_dur={dur:.3f}[a]",
        "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(seg),
    ], check=True)
    return seg


def crossfade_concat(segs: list[Path], durs: list[float], out: Path):
    n = len(segs)
    inputs = []
    for s in segs:
        inputs += ["-i", str(s)]
    parts = []
    # video chain
    prev, offset = "[0:v]", 0.0
    for k in range(1, n):
        xf = xfade_for(k)
        offset += durs[k - 1] - xf
        outv = f"[v{k}]" if k < n - 1 else "[vout]"
        parts.append(f"{prev}[{k}:v]xfade=transition=fade:duration={xf}:offset={offset:.3f}{outv}")
        prev = outv
    # audio chain, then one loudness pass so every scene sits at the same level
    prev = "[0:a]"
    for k in range(1, n):
        xf = xfade_for(k)
        outa = f"[a{k}]" if k < n - 1 else "[amix]"
        parts.append(f"{prev}[{k}:a]acrossfade=d={xf}:c1=tri:c2=tri{outa}")
        prev = outa
    parts.append("[amix]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(parts),
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)], check=True)


async def main():
    voice = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--voice=")), DEFAULT_VOICE)
    rate = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--rate=")), DEFAULT_RATE)
    fps = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--fps=")), FPS))
    FRAMES.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) narration + durations (+ per-word cues)
    sys.path.insert(0, str(HERE.parent))
    from build import live_numbers
    NARRATION[10] = results_narration(live_numbers())
    audio, durs, cues = {}, {}, {}
    for i, text in NARRATION.items():
        audio[i] = await narrate(i, text, voice, rate)
        durs[i] = round(probe_duration(audio[i]) + TAIL, 3)
        lead = 0.30 if i == 1 else 0.12
        cues[i] = cue_vars(i, FRAMES / f"narr-{i:02d}.words.json", lead)
        missing = [k for k in CUES.get(i, {}) if k not in cues[i]]
        if missing:
            print(f"scene {i}: cue words not found, CSS defaults used for {missing}")
    total = sum(durs.values()) - sum(xfade_for(k) for k in range(1, len(durs)))
    print("scene seconds:", {k: durs[k] for k in sorted(durs)}, f"total ≈ {total:.0f}s")

    # 2) frames through Chrome
    tab = http("/json/new?about:blank", "PUT")
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
        cdp = Cdp(ws)
        await cdp.call("Page.enable")
        await cdp.call("Runtime.enable")
        await cdp.call("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
        for i in sorted(NARRATION):
            n = await capture_scene(cdp, i, durs[i], fps, cues[i])
            print(f"scene {i}: {n} frames")
    try:
        http(f"/json/close/{tab['id']}")
    except Exception:
        pass

    # 3) assemble
    segs = [assemble_scene(i, durs[i], fps, audio[i]) for i in sorted(NARRATION)]
    final = OUT / "Wingspan-Video.mp4"
    crossfade_concat(segs, [durs[i] for i in sorted(NARRATION)], final)
    print("video:", final, f"{probe_duration(final):.1f}s")
    # slide PDF from the last frame of each scene (its settled state)
    from PIL import Image
    last = [sorted((FRAMES / f"s{i:02d}").glob("*.jpg"))[-1] for i in sorted(NARRATION)]
    ims = [Image.open(p).convert("RGB") for p in last]
    ims[0].save(OUT / "Wingspan-Slides.pdf", save_all=True, append_images=ims[1:], resolution=150)
    ims[0].save(OUT / "cover.png")
    print("slides + cover refreshed from the scenes")


if __name__ == "__main__":
    asyncio.run(main())
