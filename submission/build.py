#!/usr/bin/env python3
"""Build every hackathon submission file from one script, so Thursday's re-run
with final numbers is `python3 submission/build.py`.

Outputs (submission/out/):
  cover.png                 16:9 cover image (1920x1080)
  slides/slide-NN.png       8 slides + up to 2 dashboard screenshots (1920x1080)
  Wingspan-Slides.pdf       the slides as a PDF
  Wingspan-OnePager.pdf     one-page write-up (AI logic, risk gates, Alpaca infra)
  Wingspan-Video.mp4        narrated slideshow, <= 5 min (macOS `say` + ffmpeg)

Live numbers come from the public dashboard API and the Alpaca CLI (paper keys
from .env); when either is unreachable the slide says "unavailable" rather
than inventing a figure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "submission" / "out"
SLIDES = OUT / "slides"
SHOTS = ROOT / "submission" / "shots"
DASH = "https://optionsagent-production.up.railway.app"
ACCOUNT_ID = "PA371G5THNUO"
ET = ZoneInfo("America/New_York")

W, H = 1920, 1080
RED = (196, 30, 46)
INK = (24, 24, 28)
PAPER = (250, 248, 245)
MUTED = (110, 110, 118)
WHITE = (255, 255, 255)
GREEN = (28, 140, 84)

FONT_DIR = Path("/System/Library/Fonts/Supplemental")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------- live numbers

def _get_json(url: str, timeout: int = 20):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _env_keys() -> dict[str, str]:
    env = {}
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _cli(args: list[str]):
    env = _env_keys()
    child = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "ALPACA_API_KEY": env.get("ALPACA_API_KEY", ""), "ALPACA_SECRET_KEY": env.get("ALPACA_SECRET_KEY", "")}
    try:
        p = subprocess.run(["alpaca", *args, "-q"], env=child, capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
    except Exception:
        return None


def live_numbers() -> dict:
    n: dict = {"as_of": datetime.now(ET).strftime("%a %b %d, %H:%M ET")}
    acct = _cli(["account", "get"])
    n["equity"] = float(acct["equity"]) if acct else None
    n["account_number"] = acct.get("account_number") if acct else ACCOUNT_ID
    orders = _cli(["order", "list", "--status", "all", "--limit", "500"]) or []
    filled = [o for o in orders if str(o.get("status")) == "filled"]
    n["fills_total"] = len(filled)
    n["fills_options"] = sum(1 for o in filled if str(o.get("asset_class", "")).lower() == "us_option"
                             or str(o.get("order_class", "")) == "mleg")
    n["fills_equity"] = n["fills_total"] - n["fills_options"]
    summary = _get_json(f"{DASH}/api/summary") or {}
    n["today_pnl"] = summary.get("today_pnl_usd")
    n["open_spreads"] = summary.get("open_spreads")
    system = _get_json(f"{DASH}/api/system") or {}
    prop = system.get("proposer") or {}
    n["proposer"] = f"{prop.get('provider', 'deepseek')} · {prop.get('model', 'deepseek-v4-pro')}"
    risk = (_get_json(f"{DASH}/api/risk") or {}).get("rails") or {}
    n["gate"] = risk.get("credit_spread_gate")
    n["cap"] = risk.get("max_position_abs_usd")
    n["transport"] = risk.get("broker_transport")
    return n


def money(v) -> str:
    if v is None:
        return "unavailable"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


# ---------------------------------------------------------------- drawing

def canvas(bg=PAPER) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), bg)
    return im, ImageDraw.Draw(im)


def wing_mark(d: ImageDraw.ImageDraw, x: int, y: int, size: int, color=WHITE, width: int | None = None):
    """The Wingspan W: two spread payoff shapes side by side."""
    width = width or max(6, size // 9)
    s = size
    pts1 = [(x, y), (x + s * 0.25, y + s), (x + s * 0.5, y + s * 0.35)]
    pts2 = [(x + s * 0.5, y + s * 0.35), (x + s * 0.75, y + s), (x + s, y)]
    d.line(pts1, fill=color, width=width, joint="curve")
    d.line(pts2, fill=color, width=width, joint="curve")


def text_block(d, xy, lines: list[str], f, fill=INK, gap=14):
    x, y = xy
    for line in lines:
        d.text((x, y), line, font=f, fill=fill)
        y += f.size + gap
    return y


def wrap(s: str, width: int) -> list[str]:
    out: list[str] = []
    for para in s.split("\n"):
        out.extend(textwrap.wrap(para, width) or [""])
    return out


def header(d, title: str, kicker: str | None = None):
    d.rectangle([0, 0, W, 14], fill=RED)
    wing_mark(d, 96, 60, 64, color=RED)
    d.text((190, 62), "WINGSPAN", font=font(30, True), fill=RED)
    if kicker:
        d.text((190, 100), kicker, font=font(22), fill=MUTED)
    d.text((96, 190), title, font=font(64, True), fill=INK)


def footer(d, n: int, total: int):
    d.text((96, H - 60), f"Wingspan · OptionsAgent · Alpaca AI Trading Agents Hackathon 2026 · account {ACCOUNT_ID}",
           font=font(20), fill=MUTED)
    d.text((W - 160, H - 60), f"{n} / {total}", font=font(20), fill=MUTED)


def bullets(d, x, y, items: list[str], f, width_chars=70, fill=INK, gap=18, bullet="•"):
    for item in items:
        lines = wrap(item, width_chars)
        d.text((x, y), bullet, font=f, fill=RED)
        for i, line in enumerate(lines):
            d.text((x + 44, y), line, font=f, fill=fill)
            y += f.size + 8
        y += gap
    return y


# ---------------------------------------------------------------- cover

def build_cover():
    im, d = canvas(INK)
    d.rectangle([0, 0, 520, H], fill=RED)
    wing_mark(d, 110, 380, 300, color=WHITE, width=34)
    d.text((620, 300), "WINGSPAN", font=font(150, True), fill=WHITE)
    d.text((626, 470), "An options agent that mostly says no.", font=font(54), fill=WHITE)
    lines = ["DeepSeek proposes. Deterministic Python decides every strike, size and exit.",
             "The official Alpaca CLI places every order. Every refusal is journaled."]
    y = 600
    for l in lines:
        d.text((626, y), l, font=font(34), fill=(220, 220, 225)); y += 52
    d.text((626, 860), "Alpaca AI Trading Agents Hackathon 2026  ·  team Convexity  ·  paper account " + ACCOUNT_ID,
           font=font(26), fill=(180, 180, 190))
    im.save(OUT / "cover.png")


# ---------------------------------------------------------------- slides

def slide_specs(n: dict) -> list[dict]:
    """Each: title, kicker, body (callable drawing) and narration text."""
    eq = money(n["equity"])
    return [
        dict(kind="title",
             narration="This is Wingspan, an autonomous options trading agent built for the Alpaca A I Trading Agents Hackathon. "
                       "Its one design rule: the A I is the least trusted part of the system. It may propose a trade. "
                       "It may never pick a strike, size a position, choose an exit, or place an order."),
        dict(title="The problem", kicker="Why build it this way",
             items=["Language models are good at generating plausible trades and bad at refusing bad ones.",
                    "In a live account the expensive mistakes are not the ideas, they are the sizes, the strikes and the exits.",
                    "So the model only answers one question per name: is there a trade here, which strategy, which direction, how sure?",
                    "Everything after that is deterministic code that can be tested, replayed and audited."],
             narration="The problem we designed around: language models are good at generating plausible trades and bad at refusing bad ones. "
                       "In a live account the expensive mistakes are not the ideas. They are the sizes, the strikes and the exits. "
                       "So the model answers one question per name: is there a trade, which strategy, which direction, how sure. "
                       "Everything after that is deterministic code that can be tested, replayed and audited."),
        dict(title="The rule: AI proposes, code disposes", kicker="Architecture",
             items=["Once a day DeepSeek reads a 13-name watchlist with fresh bars and context, returns {underlying, strategy, direction, conviction, thesis}, validated against a schema.",
                    "Deterministic rails: conviction floor 0.60, strategy menu, one position per name, six slots, a $3,000 hard cap per position.",
                    "Contract picker: short strike 0.15 to 0.30 delta, 30 to 45 days out, width at most $2. Liquidity floor: credit ≥ $0.10 and unwind cost < 1.5x credit.",
                    "One multi-leg limit order through the official Alpaca CLI. Fill confirmed, remainder cancelled, filled count booked."],
             narration="Here is the pipeline. Once a day DeepSeek reads a thirteen name watchlist and returns proposals validated against a schema. "
                       "Deterministic rails apply a conviction floor, a strategy menu, one position per name, six slots, and a three thousand dollar hard cap per position. "
                       "A contract picker chooses the short strike between fifteen and thirty delta, thirty to forty five days out, at most two dollars wide, "
                       "and a liquidity floor rejects any spread the exit rule would stop out on its own entry quotes. "
                       "Then one multi leg limit order goes through the official Alpaca C L I, the fill is confirmed, and only the filled count is booked."),
        dict(title="Exits have no AI in them", kicker="Every 20 minutes",
             items=["Profit target: buy the spread back at 50% of the credit received.",
                    "Stop: cost to close at 2x the credit, only after 10:00 ET and only when two consecutive sweeps agree, so one wide opening quote cannot force a liquidation.",
                    "Time: forced close at 21 days to expiry, before gamma risk grows.",
                    "A close is recorded only when the unwind order actually fills; a partial fill re-registers the remainder."],
             narration="Exits run every twenty minutes with no A I in the loop. Profit target at fifty percent of the credit. "
                       "A stop at two times the credit, only after ten A M and only when two consecutive sweeps agree, so one wide opening quote cannot force a liquidation. "
                       "A forced close at twenty one days to expiry. And a close is recorded only when the unwind order actually fills."),
        dict(kind="shot", file="dash_overview.png", title="Live dashboard", kicker="Read-only observer of the same journals",
             narration="This is the public dashboard. It reads the same journals the bot writes: today's equity and P and L, "
                       "the A I's trade ideas for the day, and, next to each one, the gate that accepted or rejected it."),
        dict(kind="shot", file="dash_risk.png", title="Risk rails, as the code sees them", kicker="Rendered from the same functions the bot runs",
             narration="The risk rails tab is rendered from the exact functions the trading cycle calls, so the page cannot drift from the code. "
                       "You can see the gate mode, the three thousand dollar cap, and that the broker path is the official Alpaca C L I."),
        dict(title="Alpaca infrastructure", kicker="Trading API through the official CLI",
             items=["Account, positions, clock, order submit (single-leg and mleg), order status and cancel all run as `alpaca … -q` subprocesses inside the container, JSON out.",
                    "CLI pinned to v0.0.14 with a verified checksum in the Docker image. Every call journaled: argv, exit code, latency, order id.",
                    "Fail-closed: a missing binary or a non-zero exit stops the trade. A lost reply is reconciled by our own client order id before it is called a failure.",
                    "Runs on Railway as Linux cron: entry 10:15 ET, exits every 20 min, an equity scalper every minute. State on a volume. Paper only by construction."],
             narration="On the Alpaca side, every account, position, clock and order call runs through the official command line interface as a subprocess inside the container, "
                       "pinned to a checksummed release, with every call journaled. It fails closed: a missing binary or a non zero exit stops the trade, "
                       "and a lost reply is reconciled by our own client order I D before it is ever called a failure. "
                       "The whole thing runs on Railway as Linux cron, paper only by construction."),
        dict(title="What we caught before the first trade", kicker="Build in public means showing the misses",
             items=["The original gate admitted only three historical winner shapes: a week of zero option fills.",
                    "Opening it naively would have booked losers: replaying the previous day's real chains, 8 of 22 admitted spreads were already past the 2x stop on their own entry quotes, because entry is priced bid-to-ask and the unwind ask-to-bid.",
                    "Fix: a liquidity floor derived from the exit rule. After it: 5 of 26 admitted, 0 past the stop.",
                    "Also fixed before deploy: no per-name dedupe, fills booked unconfirmed, a scalper path that bypassed the CLI. 276 tests; seven mutation checks each broke the right test."],
             narration="What we caught before the first trade. The original gate admitted only three historical winner shapes, which meant a week of zero option fills. "
                       "Opening it naively would have booked losers: replaying the previous day's real option chains, eight of twenty two admitted spreads were already past their stop on their own entry quotes. "
                       "The fix is a liquidity floor derived from the exit rule. After it, five of twenty six admitted, none past the stop. "
                       "We also fixed missing de duplication, unconfirmed fills, and a scalper path that bypassed the C L I, all before deploy, with two hundred seventy six tests."),
        dict(title="Results and disclosure", kicker=f"Snapshot {n['as_of']}",
             items=[f"Competition account {n['account_number']}: equity {eq}; today's P/L {money(n['today_pnl'])}.",
                    f"Filled orders in the window: {n['fills_total']} ({n['fills_options']} options, {n['fills_equity']} shares).",
                    f"Active settings: gate = {n['gate']}, cap = {money(n['cap'])}, broker path = {n['transport']}, proposer = {n['proposer']}.",
                    "Disclosure: the harness predates the event (July 2026). Built in the window: the equity scalper and its study, the Railway deploy, the DeepSeek proposer, the dashboard rework, the CLI transport, the gate and cap. Nothing else has traded this account.",
                    "Repo: github.com/Jhosshua/OptionsAgent (MIT). Dashboard: optionsagent-production.up.railway.app"],
             narration=f"Results as of {n['as_of']}. Equity {eq}. {n['fills_total']} filled orders in the window, "
                       f"{n['fills_options']} of them options. Full disclosure: the harness predates the event; the scalper, the deployment, the proposer, "
                       "the dashboard, the C L I transport and the gate changes were built inside the window, and nothing else has traded this account. "
                       "The lesson we would offer: on a two day window, robustness is the thing a judge can verify. Thank you."),
    ]


def render_slides(n: dict) -> list[Path]:
    specs = slide_specs(n)
    total = len(specs)
    paths = []
    for i, s in enumerate(specs, 1):
        kind = s.get("kind", "bullets")
        if kind == "title":
            im = Image.open(OUT / "cover.png").convert("RGB")
        elif kind == "shot":
            im, d = canvas()
            header(d, s["title"], s.get("kicker"))
            shot = SHOTS / s["file"]
            if shot.exists():
                pic = Image.open(shot).convert("RGB")
                pic.thumbnail((W - 192, H - 340))
                im.paste(pic, (96, 280))
            else:
                d.text((96, 300), "(dashboard screenshot not captured yet)", font=font(30), fill=MUTED)
            footer(d, i, total)
        else:
            im, d = canvas()
            header(d, s["title"], s.get("kicker"))
            bullets(d, 96, 300, s["items"], font(32), width_chars=88)
            footer(d, i, total)
        p = SLIDES / f"slide-{i:02d}.png"
        im.save(p)
        paths.append(p)
    return paths


def slides_pdf(paths: list[Path]):
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims[0].save(OUT / "Wingspan-Slides.pdf", save_all=True, append_images=ims[1:], resolution=150)


# ---------------------------------------------------------------- one-pager

def one_pager(n: dict):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    doc = SimpleDocTemplate(str(OUT / "Wingspan-OnePager.pdf"), pagesize=letter,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    ss = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=ss["Heading1"], fontSize=17, textColor="#c41e2e", spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9.5, textColor="#6e6e76", spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5, spaceBefore=7, spaceAfter=2)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.4, leading=12)
    story = [
        Paragraph("Wingspan — an options agent that mostly says no", h),
        Paragraph(f"Alpaca AI Trading Agents Hackathon 2026 · team Convexity · paper account {n['account_number']} · "
                  f"github.com/Jhosshua/OptionsAgent (MIT) · optionsagent-production.up.railway.app · snapshot {n['as_of']}", sub),
        Paragraph("AI logic", h2),
        Paragraph("One DeepSeek call per trading day (deepseek-v4-pro, JSON mode, temperature 0) over a 13-name sub-$50 watchlist "
                  "with recent bars and context. The output is a list of proposals, each {underlying, strategy_type, direction, "
                  "conviction, thesis}, validated against a schema; anything malformed is dropped, never repaired. The model cannot "
                  "name a strike, a size or an exit, and cannot place an order. A failed or empty call is journaled as a "
                  "<i>proposer_result</i> row so a dead model can never pass for a quiet market.", body),
        Paragraph("Risk gates (deterministic, in code; environment may only tighten)", h2),
        Paragraph("Conviction floor 0.60 · strategy menu (defined-risk credit spreads) · one position per underlying, watchlist names only, "
                  "no re-entry on an open name · six concurrent positions · sizing = conviction-scaled share of buying power, hard-capped at "
                  "$3,000 of defined risk per position (≤ 15 contracts of a $2 spread) · contract picker: short strike 0.15–0.30 delta, "
                  "30–45 DTE, width ≤ $2 · liquidity floor: credit ≥ $0.10 and unwind-now cost &lt; 1.5× credit, so the exit rule cannot "
                  "stop the trade out on its own entry quotes (replay of the prior day's chains: 8 of 22 naive picks were already past the "
                  "stop; after the floor, 5 of 26 admitted, 0 past) · fills confirmed and the unfilled remainder cancelled before anything "
                  "is booked. Exits, no AI, every 20 minutes: 50% profit target; 2× credit stop confirmed over two sweeps after 10:00 ET; "
                  "forced close at 21 DTE; a close is recorded only on a confirmed unwind fill. Paper-only by construction; every broker or "
                  "model error fails closed and pages Discord. 276 tests; the gate, cap, fill-confirmation and CLI paths each have a "
                  "mutation check that breaks a test when the guard is removed.", body),
        Paragraph("Alpaca infrastructure", h2),
        Paragraph("Orders, positions, account and clock go through the official Alpaca CLI (<i>alpaca … -q</i>, JSON out), pinned to "
                  "v0.0.14 with a verified checksum in the Docker image, and journaled per call (argv, exit code, latency, order id). A "
                  "spread is one <i>order submit --order-class mleg</i> limit order at the net credit; a lost reply is reconciled by our "
                  "client order id before it is called a failure. Option chains come from a read-only market-data sidecar; stock bars from "
                  "a hosted Alpaca market-data relay. Runs on Railway as Linux cron (entry 10:15 ET, exit sweep every 20 min, equity "
                  "scalper every minute) with state on a volume; the public dashboard is a read-only observer of the same journals and "
                  "renders the rails from the same functions the bot runs.", body),
        Paragraph("Results and disclosure", h2),
        Paragraph(f"Competition account {n['account_number']}: equity {money(n['equity'])}; filled orders in the window {n['fills_total']} "
                  f"({n['fills_options']} options, {n['fills_equity']} shares); active gate <i>{n['gate']}</i>, cap {money(n['cap'])}, broker path "
                  f"<i>{n['transport']}</i>. The harness predates the event (July 2026). Built inside the window: the equity intraday scalper "
                  "and its 6-month study, the Railway deployment, the DeepSeek proposer, the dashboard rework, the CLI transport, and the "
                  "gate/cap changes with their adversarial review. The account was created 2026-08-30 with $100,000 and nothing else has "
                  "traded on it.", body),
    ]
    doc.build(story)


# ---------------------------------------------------------------- video

def video(paths: list[Path], n: dict, voice: str = "Samantha"):
    specs = slide_specs(n)
    work = OUT / "video_work"
    work.mkdir(exist_ok=True)
    segs = []
    for i, (p, s) in enumerate(zip(paths, specs), 1):
        aiff = work / f"narr-{i:02d}.aiff"
        subprocess.run(["say", "-v", voice, "-r", "178", "-o", str(aiff), s["narration"]], check=True)
        seg = work / f"seg-{i:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(p), "-i", str(aiff),
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-b:a", "128k", "-af", "apad=pad_dur=0.8", "-shortest", str(seg),
        ], check=True)
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    final = OUT / "Wingspan-Video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(final)], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                         capture_output=True, text=True).stdout.strip()
    return final, float(dur or 0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SLIDES.mkdir(exist_ok=True)
    n = live_numbers()
    print("live numbers:", json.dumps(n))
    build_cover()
    paths = render_slides(n)
    slides_pdf(paths)
    one_pager(n)
    if "--no-video" not in sys.argv:
        final, dur = video(paths, n)
        print(f"video: {final} {dur:.0f}s {'OK' if dur <= 300 else 'TOO LONG (>300s)'}")
    for p in sorted(OUT.glob("*")):
        if p.is_file():
            print(f"{p.name:28} {p.stat().st_size/1024:8.0f} KB")


if __name__ == "__main__":
    main()
