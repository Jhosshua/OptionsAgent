#!/usr/bin/env python3
"""Emit the animated 1920x1080 scene artboards (Scene01..Scene13.dc.html), the
Letter one-pager, the idea boards, and canvas.json. The SAME scene files are
what render.py captures frame-by-frame into the video, so the design canvas is
the single source of truth for the look.

Design tokens are lifted from dashboard/app.css (Nunito Sans, --accent #e5484d,
--accent-dark #b8383c, --ink #222, --muted #717171, --line #ebebeb, radius 16px).

Animation contract (used by render.py): every motion is a CSS animation with
`animation-fill-mode: both`; the renderer pauses all animations and seeks
`currentTime`. Reveal times are CSS variables `--c-<cue>` that render.py sets
from the narration's per-word timestamps, with the defaults below as fallback.
Scene length is injected as `--dur` (seconds).

Language rule: no trading jargon on screen. Say "contract", "bet", "fee",
"the two biggest index funds", never delta / DTE / spread / VWAP / mleg.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
sys.path.insert(0, str(HERE.parent))  # submission/
from build import live_numbers, money  # noqa: E402

TOTAL = 13

FONT_LINK = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito+Sans:'
             'opsz,wght@6..12,400;6..12,600;6..12,700;6..12,800;6..12,900&display=swap">')

BASE_CSS = """
:root { --ink:#222; --muted:#717171; --faint:#b0b0b0; --line:#ebebeb; --paper:#faf8f5; --bg:#fff;
        --accent:#e5484d; --accent-dark:#b8383c; --wash:#fff3f3; --gain:#067647; --gain-wash:#eef8f2;
        --loss:#c13515; --radius:16px; --dur:10s; }
* { box-sizing:border-box; }
html,body { margin:0; }
body { width:1920px; height:1080px; overflow:hidden; background:var(--bg); color:var(--ink);
       font-family:"Nunito Sans","Avenir Next","Segoe UI",sans-serif; -webkit-font-smoothing:antialiased; }
a { color:var(--accent-dark); } a:hover { color:var(--accent); }
.stage { position:relative; width:1920px; height:1080px; overflow:hidden; background:var(--paper); }
.topbar { position:absolute; left:0; top:0; width:1920px; height:12px; background:var(--accent); }
.brand { position:absolute; left:96px; top:56px; display:flex; align-items:center; gap:14px; }
.brand .mark { width:44px; height:44px; border-radius:12px; background:var(--accent); display:grid; place-items:center; }
.brand .name { font-weight:800; font-size:26px; letter-spacing:-.4px; }
.brand .kick { color:var(--muted); font-weight:600; font-size:24px; margin-left:10px; }
.foot { position:absolute; left:96px; bottom:48px; color:var(--faint); font-size:24px; font-weight:600; }
.pn { position:absolute; right:96px; bottom:48px; color:var(--faint); font-size:24px; font-weight:600; }
h1 { margin:0; font-weight:900; letter-spacing:-1.5px; line-height:1.05; }
.h { position:absolute; left:120px; top:160px; } .h h1 { font-size:72px; max-width:1680px; }
.fade { animation: fade .6s ease-out both; animation-delay: var(--d, 0s); }
.pop  { animation: pop .5s cubic-bezier(.2,.8,.3,1.1) both; animation-delay: var(--d, 0s); }
@keyframes fade { from { opacity:0; } to { opacity:1; } }
@keyframes pop  { from { opacity:0; transform: scale(.86); } to { opacity:1; transform: scale(1); } }
.kb { animation: kb var(--dur) linear both; transform-origin: 50% 40%; }
@keyframes kb { from { transform: scale(1); } to { transform: scale(1.035); } }
.card { background:#fff; border:1px solid var(--line); border-radius:var(--radius); box-shadow:0 10px 30px rgba(0,0,0,.06); }
.dark .stage { background:#18181c; } .dark .brand .name, .dark .foot, .dark .pn, .dark h1 { color:#fff; } .dark .brand .kick { color:#9a9aa3; }
/* alpaca mascot (cover and closing scene only) */
.alpaca { position:absolute; width:260px; height:260px; }
.alpaca .leg { transform-origin: 50% 0; }
.alpaca.walk .leg.a { animation: step .5s ease-in-out infinite alternate; }
.alpaca.walk .leg.b { animation: step .5s ease-in-out infinite alternate-reverse; }
.alpaca.walk .body, .alpaca.idle .body { animation: bob 1.1s ease-in-out infinite alternate; transform-origin:50% 100%; }
.alpaca .lid { transform-origin: 50% 50%; animation: blink 3.4s linear infinite; }
@keyframes step  { from { transform: rotate(-14deg); } to { transform: rotate(14deg); } }
@keyframes bob   { from { transform: translateY(0); } to { transform: translateY(-7px); } }
@keyframes blink { 0%,92%,100% { transform: scaleY(1); } 95% { transform: scaleY(.1); } }
"""

ALPACA_SVG = """
<svg class="alpaca {cls}" style="{style}" viewBox="0 0 220 220" fill="none">
  <g class="body">
    <g class="leg a"><rect x="62" y="150" width="16" height="48" rx="7" fill="#ead9c0"/></g>
    <g class="leg b"><rect x="88" y="150" width="16" height="48" rx="7" fill="#f3e6d2"/></g>
    <g class="leg b"><rect x="122" y="150" width="16" height="48" rx="7" fill="#ead9c0"/></g>
    <g class="leg a"><rect x="148" y="150" width="16" height="48" rx="7" fill="#f3e6d2"/></g>
    <rect x="46" y="100" width="128" height="66" rx="33" fill="#f3e6d2"/>
    <circle cx="50" cy="106" r="16" fill="#f3e6d2"/>
    <rect x="146" y="44" width="30" height="76" rx="15" fill="#f3e6d2"/>
    <g class="head">
      <rect x="132" y="24" width="60" height="40" rx="19" fill="#f3e6d2"/>
      <path d="M144 28 L150 8 L158 28 Z" fill="#f3e6d2"/>
      <path d="M170 28 L178 9 L184 28 Z" fill="#f3e6d2"/>
      <ellipse cx="182" cy="52" rx="9" ry="7" fill="#e6d3bb"/>
      <circle cx="166" cy="42" r="3.6" fill="#222"/>
      <rect class="lid" x="161" y="37" width="10" height="10" rx="5" fill="#f3e6d2" opacity="0"/>
      <path d="M176 57 q4 3 8 0" stroke="#8b6f52" stroke-width="2" stroke-linecap="round"/>
    </g>
    <path d="M62 128 q-12 -2 -14 8" stroke="#e6d3bb" stroke-width="6" stroke-linecap="round"/>
  </g>
</svg>
"""

W_MARK = ('<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.6" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 8.5 L6.5 16 H9.5 L12 10.5 L14.5 16 H17.5 L21.5 8.5"/></svg>')

# The customer: an everyday trader on the couch with a phone. Not a developer.
TRADER_SVG = """
<svg class="trader" viewBox="0 0 520 420" fill="none" style="{style}">
  <rect x="40" y="250" width="440" height="110" rx="34" fill="#e6e1da"/>
  <rect x="40" y="200" width="70" height="120" rx="30" fill="#ddd6cc"/>
  <rect x="410" y="200" width="70" height="120" rx="30" fill="#ddd6cc"/>
  <path d="M150 340 q0 -100 60 -120 l100 0 q60 20 60 120 Z" fill="#2f5d7c"/>
  <path d="M215 232 q-40 30 -20 90" stroke="#2f5d7c" stroke-width="26" stroke-linecap="round"/>
  <path d="M305 232 q40 30 20 90" stroke="#2f5d7c" stroke-width="26" stroke-linecap="round"/>
  <g class="phone"><rect x="238" y="262" width="52" height="88" rx="10" fill="#222"/><rect x="244" y="270" width="40" height="70" rx="6" fill="#f4f4f6"/></g>
  <circle cx="260" cy="160" r="56" fill="#c68642"/>
  <path d="M204 150 q10 -62 68 -58 q52 4 56 58 q-24 -26 -60 -26 q-40 0 -64 26 Z" fill="#1b1b1f"/>
  <g class="brows"><path d="M234 138 l20 -3" stroke="#1b1b1f" stroke-width="5" stroke-linecap="round"/><path d="M266 135 l20 3" stroke="#1b1b1f" stroke-width="5" stroke-linecap="round"/></g>
  <circle cx="242" cy="156" r="4.5" fill="#222"/><circle cx="278" cy="156" r="4.5" fill="#222"/>
  <path class="mouth" d="M246 182 q14 10 28 0" stroke="#7a3f2a" stroke-width="4" stroke-linecap="round" fill="none"/>
</svg>
"""


def alpaca(cls: str, style: str) -> str:
    return ALPACA_SVG.format(cls=cls, style=style)


def page(title: str, css: str, body: str, dark: bool = False) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body class="{'dark' if dark else ''}">
<x-dc>
<helmet>
  {FONT_LINK}
  <style>{BASE_CSS}{css}</style>
</helmet>
<div class="stage">
{body}
</div>
</x-dc>
</body>
</html>
"""


def chrome(kicker: str, n: int) -> str:
    return (f'<div class="topbar"></div>'
            f'<div class="brand fade" style="--d:.05s"><div class="mark">{W_MARK.format(s=28, c="#fff")}</div>'
            f'<div class="name">Wingspan</div><div class="kick">{kicker}</div></div>'
            f'<div class="foot">Alpaca AI Trading Agents Hackathon 2026 · paper account PA371G5THNUO</div>'
            f'<div class="pn">{n} / {TOTAL}</div>')


# --------------------------------------------------------------------------- scenes

def scene01() -> str:
    css = """
    .stage { background:#18181c; }
    .panel { position:absolute; left:0; top:0; width:560px; height:1080px; background:var(--accent); }
    .bigw { position:absolute; left:110px; top:360px; }
    .bigw path { stroke-dasharray: 60; stroke-dashoffset: 60; animation: draw .9s cubic-bezier(.2,.7,.2,1) .15s both; }
    @keyframes draw { to { stroke-dashoffset: 0; } }
    .title { position:absolute; left:660px; top:340px; } .title h1 { font-size:168px; color:#fff; }
    .tag { position:absolute; left:664px; top:530px; font-size:56px; font-weight:700; color:#fff; letter-spacing:-.6px; }
    .meta { position:absolute; left:664px; bottom:64px; font-size:26px; color:#9a9aa3; font-weight:600; }
    .walkin { position:absolute; right:120px; bottom:130px; animation: walkin 2.2s cubic-bezier(.3,.7,.3,1) var(--c-mostly, 1.9s) both; }
    @keyframes walkin { from { transform: translateX(560px); } to { transform: translateX(0); } }
    """
    body = f"""
    <div class="panel"></div>
    <div class="bigw">{W_MARK.format(s=340, c="#fff")}</div>
    <div class="title fade" style="--d:.9s"><h1>WINGSPAN</h1></div>
    <div class="tag fade" style="--d:var(--c-trading, 1.6s)">A trading helper that knows when to say no.</div>
    <div class="meta fade" style="--d:2.4s">Alpaca AI Trading Agents Hackathon 2026 · team Convexity · paper account PA371G5THNUO</div>
    <div class="walkin">{alpaca("walk", "position:relative; width:250px; height:250px;")}</div>
    """
    return page("Scene 1 · Cover", css, body)


def scene02() -> str:
    """The customer: an everyday options trader on the couch. A losing streak, then a bigger bet."""
    css = """
    .who { position:absolute; left:120px; top:180px; color:var(--muted); font-weight:700; font-size:26px; letter-spacing:.06em; text-transform:uppercase; }
    .trader { position:absolute; left:100px; top:330px; width:640px; height:520px; }
    .trader .brows { transform-origin: 260px 140px; animation: worry .5s ease-out var(--c-lost, 6.0s) both; }
    @keyframes worry { to { transform: translateY(-8px) rotate(-6deg); } }
    .trader .mouth { animation: flat .5s ease-out var(--c-lost, 6.0s) both; }
    @keyframes flat { to { d: path("M246 186 q14 -6 28 0"); } }
    .trader .phone { transform-origin: 264px 306px; animation: buzz .12s linear var(--c-phone, 1.2s) 6 alternate; }
    @keyframes buzz { from { transform: rotate(-3deg); } to { transform: rotate(3deg); } }
    .notif { position:absolute; left:820px; width:900px; padding:26px 32px; border-radius:22px; background:#fff; border:1px solid var(--line); box-shadow:0 10px 30px rgba(0,0,0,.08); font-size:36px; font-weight:700; display:flex; align-items:center; gap:22px; }
    .notif .ic { width:52px; height:52px; border-radius:14px; display:grid; place-items:center; flex:0 0 52px; background:#f1efe9; }
    .notif small { display:block; font-size:22px; color:var(--muted); font-weight:700; letter-spacing:.05em; text-transform:uppercase; margin-bottom:4px; }
    .n1 { top:300px; animation: pop .45s cubic-bezier(.2,.8,.3,1.1) var(--c-phone, 1.2s) both; }
    .n2 { top:440px; animation: pop .45s cubic-bezier(.2,.8,.3,1.1) var(--c-lost, 6.0s) both; }
    .n2 b { color:var(--loss); }
    .n3 { top:580px; background:var(--ink); color:#fff; border-color:var(--ink); animation: pop .45s cubic-bezier(.2,.8,.3,1.1) var(--c-bigger, 9.5s) both; }
    .n3 small { color:#9a9aa3; }
    .line { position:absolute; left:120px; top:900px; font-size:42px; font-weight:800; letter-spacing:-.6px; animation: fade .5s var(--c-that, 12.5s) both; }
    .line em { font-style:normal; color:var(--accent-dark); }
    """
    body = chrome("The customer", 2) + f"""
    <div class="who fade" style="--d:.2s">Someone who trades options on their phone after work</div>
    {TRADER_SVG.format(style="")}
    <div class="notif n1"><div class="ic">{W_MARK.format(s=26, c="#717171")}</div><div><small>Tuesday · trading app</small>Your call options are up 38% today</div></div>
    <div class="notif n2"><div class="ic">{W_MARK.format(s=26, c="#717171")}</div><div><small>Thursday · trading app</small><b>Down $1,240</b> this week</div></div>
    <div class="notif n3"><div class="ic" style="background:#2a2a30">{W_MARK.format(s=26, c="#fff")}</div><div><small>Thursday · 3:52 pm</small>Doubles the next bet to make it back</div></div>
    <div class="line">That last move is the one that empties accounts. <em>And a person can't stop themselves at 3:52.</em></div>
    """
    return page("Scene 2 · Customer", css, body)


def scene03() -> str:
    """Why people would want this: the evidence."""
    css = """
    .h h1 { font-size:68px; }
    .tiles { position:absolute; left:120px; top:320px; display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:32px; width:1680px; }
    .t { padding:38px 40px; }
    .t .v { font-size:112px; font-weight:900; letter-spacing:-4px; line-height:1; }
    .t .v.red { color:var(--loss); }
    .t .l { font-size:32px; font-weight:800; margin-top:14px; line-height:1.3; }
    .t .s { font-size:22px; color:var(--muted); font-weight:600; margin-top:16px; line-height:1.4; }
    .line { position:absolute; left:120px; top:820px; font-size:40px; font-weight:800; letter-spacing:-.6px; max-width:1680px; line-height:1.3; animation: fade .5s var(--c-problem, 14s) both; }
    .line em { font-style:normal; color:var(--accent-dark); }
    """
    body = chrome("Why it matters", 3) + """
    <div class="h fade" style="--d:.2s"><h1>This is not one person's bad week.</h1></div>
    <div class="tiles">
      <div class="t card pop" style="--d:var(--c-two, 2.0s)"><div class="v red">$2.1B</div><div class="l">lost by everyday options traders in twenty months</div><div class="s">Most of it was the cost of trading, not bad picks. Journal of Finance, 2023.</div></div>
      <div class="t card pop" style="--d:var(--c-sixty, 6.5s)"><div class="v">60%</div><div class="l">of same-day S&amp;P 500 option trades now come from everyday traders</div><div class="s">Cboe, 2025. Record volume six years running.</div></div>
      <div class="t card pop" style="--d:var(--c-streak, 10s)"><div class="v">2×</div><div class="l">after a losing streak, people bet bigger and more often</div><div class="s">The pattern behavior research finds again and again.</div></div>
    </div>
    <div class="line">The problem isn't picking stocks. <em>It's how much, when to get out, and knowing when to do nothing.</em></div>
    """
    return page("Scene 3 · Evidence", css, body)


def scene04() -> str:
    """What Wingspan is, in one picture."""
    css = """
    .h h1 { font-size:68px; }
    .cols { position:absolute; left:120px; top:320px; display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:64px; width:1680px; }
    .col h2 { margin:0 0 22px; font-size:30px; font-weight:800; color:var(--muted); letter-spacing:.05em; text-transform:uppercase; }
    .bubble { padding:40px 44px; border-radius:28px 28px 28px 6px; background:#fff; border:1px solid var(--line); box-shadow:0 10px 30px rgba(0,0,0,.06); font-size:40px; line-height:1.45; }
    .bubble b { font-weight:900; }
    .stamps { display:flex; flex-direction:column; gap:18px; }
    .stamp { display:flex; align-items:center; justify-content:space-between; padding:22px 32px; border-radius:var(--radius); background:var(--ink); color:#fff; font-size:38px; font-weight:800; }
    .stamp span { color:#c9c9d1; font-weight:600; font-size:26px; }
    .land { animation: land .42s cubic-bezier(.2,.8,.3,1.06) both; animation-delay: var(--d); }
    @keyframes land { from { opacity:0; transform: scale(1.18); } to { opacity:1; transform: scale(1); } }
    .line { position:absolute; left:120px; top:900px; font-size:40px; font-weight:800; animation: fade .5s var(--c-never, 12s) both; }
    """
    body = chrome("What it is", 4) + """
    <div class="h fade" style="--d:.2s"><h1>Wingspan does the boring part perfectly.</h1></div>
    <div class="cols">
      <div class="col">
        <h2 class="fade" style="--d:.4s">The AI has ideas</h2>
        <div class="bubble fade" style="--d:var(--c-idea, 3.0s)">“I think <b>AT&amp;T</b> stays flat or drifts up for a few weeks. I'm about <b>70%</b> sure.”</div>
      </div>
      <div class="col">
        <h2 class="fade" style="--d:.4s">The rules decide everything else</h2>
        <div class="stamps">
          <div class="stamp land" style="--d:var(--c-much, 6.5s)">How much <span>never more than $3,000 at risk</span></div>
          <div class="stamp land" style="--d:var(--c-when, 7.6s)">When to get out <span>take the win, cut the loss, on a clock</span></div>
          <div class="stamp land" style="--d:var(--c-nothing, 8.8s)">When to do nothing <span>most days</span></div>
        </div>
      </div>
    </div>
    <div class="line">The AI never touches the money. It can't place an order, pick a size, or move a stop.</div>
    """
    return page("Scene 4 · What it is", css, body)


def scene05() -> str:
    """Engine one, step 1 and 2: the idea and the bet, in plain words."""
    css = """
    .h h1 { font-size:64px; }
    .steps { position:absolute; left:120px; top:300px; width:1680px; display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:32px; }
    .st { padding:36px 38px; min-height:520px; }
    .st .n { width:56px; height:56px; border-radius:50%; background:var(--ink); color:#fff; display:grid; place-items:center; font-weight:900; font-size:28px; }
    .st h3 { margin:22px 0 14px; font-size:36px; font-weight:900; letter-spacing:-.5px; }
    .st p { margin:0; font-size:28px; line-height:1.5; color:var(--ink); }
    .st p b { color:var(--accent-dark); }
    .pay { margin-top:22px; height:120px; }
    .pay path { fill:none; stroke:var(--ink); stroke-width:6; stroke-linecap:round; }
    .pay .cap { stroke:var(--accent); }
    .pay text { font-family:"Nunito Sans", sans-serif; font-weight:800; font-size:22px; fill:var(--muted); }
    """
    body = chrome("Engine one", 5) + """
    <div class="h fade" style="--d:.2s"><h1>Engine one: a small, capped bet that the AI's idea holds.</h1></div>
    <div class="steps">
      <div class="st card pop" style="--d:var(--c-morning, 1.0s)"><div class="n">1</div><h3>Every morning, one question</h3><p>The AI reads six weeks of prices for thirteen well-known stocks and answers: <b>is there a bet here, and how sure am I?</b> That's all it's allowed to say.</p></div>
      <div class="st card pop" style="--d:var(--c-fee, 6.0s)"><div class="n">2</div><h3>The rules build the bet</h3><p>Sell a contract five to six weeks out at a price the stock <b>probably won't reach</b>, and collect a fee. Buy a second contract behind it so <b>the most you can lose is fixed</b> before the order goes out.</p>
        <svg class="pay" viewBox="0 0 460 120"><path d="M20 40 L230 40 L330 100"/><path class="cap" d="M330 100 L440 100"/><text x="20" y="28">keep the fee</text><text x="336" y="90">loss capped</text></svg></div>
      <div class="st card pop" style="--d:var(--c-five, 12.0s)"><div class="n">3</div><h3>Five checks, any one says no</h3><p>Sure enough? Not already in this stock? Small enough? Far enough from today's price? And <b>cheap enough to get out of</b> if it goes wrong. Most ideas stop here.</p></div>
    </div>
    """
    return page("Scene 5 · Engine one", css, body)


def scene06() -> str:
    """Engine one, the exit: a separate program with no AI."""
    css = """
    .h h1 { font-size:64px; }
    .clock { position:absolute; left:120px; top:330px; width:520px; height:520px; }
    .clock circle.face { fill:#fff; stroke:var(--line); stroke-width:6; }
    .clock .hand { stroke:var(--ink); stroke-width:10; stroke-linecap:round; transform-origin: 260px 260px; animation: tick var(--dur) linear both; }
    @keyframes tick { to { transform: rotate(720deg); } }
    .clock text { font-family:"Nunito Sans", sans-serif; font-weight:800; font-size:28px; fill:var(--muted); }
    .rules { position:absolute; left:720px; top:330px; width:1080px; display:flex; flex-direction:column; gap:20px; }
    .r { padding:26px 32px; display:flex; align-items:center; gap:24px; font-size:34px; font-weight:800; }
    .r .k { width:60px; height:60px; border-radius:16px; display:grid; place-items:center; font-size:30px; font-weight:900; color:#fff; flex:0 0 60px; }
    .r span { font-size:26px; color:var(--muted); font-weight:600; display:block; margin-top:4px; }
    .g { background:var(--gain); } .l { background:var(--loss); } .t { background:var(--ink); }
    .note { position:absolute; left:120px; top:900px; font-size:38px; font-weight:800; animation: fade .5s var(--c-noai, 12s) both; }
    """
    body = chrome("Engine one · getting out", 6) + """
    <div class="h fade" style="--d:.2s"><h1>Getting out is decided by a clock and three rules. No AI.</h1></div>
    <svg class="clock fade" style="--d:.4s" viewBox="0 0 520 520"><circle class="face" cx="260" cy="260" r="220"/><line class="hand" x1="260" y1="260" x2="260" y2="90"/><circle cx="260" cy="260" r="12" fill="#222"/><text x="200" y="470">every 20 minutes</text></svg>
    <div class="rules">
      <div class="r card pop" style="--d:var(--c-win, 3.5s)"><div class="k g">✓</div><div>Take the win at half<span>when the contract is worth half the fee you collected, buy it back</span></div></div>
      <div class="r card pop" style="--d:var(--c-loss, 6.5s)"><div class="k l">✕</div><div>Cut the loss at double<span>only after 10 am, and only when two checks in a row agree</span></div></div>
      <div class="r card pop" style="--d:var(--c-weeks, 9.5s)"><div class="k t">21</div><div>Never hold the last three weeks<span>that's when small moves start to hurt</span></div></div>
    </div>
    <div class="note">Same rules, every day, written before the trade, never bent after it.</div>
    """
    return page("Scene 6 · Exits", css, body)


def scene07() -> str:
    """Engine two: shares of the two biggest index funds, in plain words."""
    css = """
    .h h1 { font-size:64px; }
    .chart { position:absolute; left:120px; top:300px; width:1040px; height:600px; }
    .chart .line { fill:none; stroke:var(--ink); stroke-width:5; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:2400; stroke-dashoffset:2400; animation: draw 3.2s cubic-bezier(.3,.6,.3,1) .6s both; }
    @keyframes draw { to { stroke-dashoffset:0; } }
    .chart .avg { fill:none; stroke:var(--muted); stroke-width:3; stroke-dasharray:10 10; opacity:0; animation: fade .4s 1.0s both; }
    .chart .range { fill:rgba(34,34,34,.08); stroke:#b0b0b0; stroke-width:2; opacity:0; animation: fade .4s 1.4s both; }
    .chart text { font-family:"Nunito Sans", sans-serif; font-weight:800; }
    .mk { opacity:0; animation: pop .4s cubic-bezier(.34,1.56,.64,1) both; }
    .side { position:absolute; left:1240px; top:300px; width:560px; display:flex; flex-direction:column; gap:16px; }
    .row { display:flex; justify-content:space-between; align-items:center; padding:20px 28px; border-radius:14px; background:#fff; border:1px solid var(--line); font-size:30px; font-weight:800; }
    .row span { color:var(--muted); font-weight:700; font-size:26px; }
    .row.dark { background:var(--ink); color:#fff; } .row.dark span { color:#c9c9d1; }
    """
    body = chrome("Engine two", 7) + """
    <div class="h fade" style="--d:.2s"><h1>Engine two trades shares. No AI at all.</h1></div>
    <svg class="chart fade" style="--d:.4s" viewBox="0 0 1040 600">
      <rect class="range" x="60" y="230" width="36" height="200" rx="6"/>
      <text x="60" y="466" font-size="24" fill="#717171">first 15 minutes</text>
      <path class="avg" d="M60 340 C 260 330, 520 380, 980 300"/>
      <text x="700" y="372" font-size="24" fill="#717171">the day's average price</text>
      <path class="line" d="M60 340 L80 290 L96 410 L125 200 L180 300 L260 350 L340 300 L420 380 L500 330 L565 230 L640 250 L720 220 L800 260 L900 230 L980 250"/>
      <g class="mk" style="animation-delay:var(--c-fast, 5.0s)"><circle cx="125" cy="200" r="16" fill="#222"/><text x="150" y="170" font-size="28" fill="#222">10:15 · ran too far too fast? bet on a pullback</text></g>
      <g class="mk" style="animation-delay:var(--c-jump, 9.0s)"><circle cx="565" cy="230" r="16" fill="#222"/><text x="380" y="206" font-size="28" fill="#222">1:00 · big jump at the open? go with it</text></g>
      <line x1="60" y1="530" x2="980" y2="530" stroke="#ebebeb" stroke-width="2"/>
      <text x="60" y="566" font-size="24" fill="#717171">9:30</text><text x="560" y="566" font-size="24" fill="#717171">1:00</text><text x="840" y="566" font-size="24" fill="#717171">3:50 all closed</text>
    </svg>
    <div class="side">
      <div class="row fade" style="--d:var(--c-spy, 3.0s)">SPY and QQQ <span>shares only</span></div>
      <div class="row fade" style="--d:var(--c-rules, 4.0s)">Two rules <span>found in 6 months of data</span></div>
      <div class="row fade" style="--d:var(--c-twenty, 12.0s)">$20,000 <span>per trade</span></div>
      <div class="row fade" style="--d:var(--c-stop, 13.0s)">Out at a 0.7% loss <span>or after 2 hours</span></div>
      <div class="row fade" style="--d:var(--c-twoaday, 14.5s)">2 trades a day <span>halts after a $300 loss</span></div>
      <div class="row dark fade" style="--d:var(--c-closed, 16.0s)">All closed by 3:50 <span>nothing overnight</span></div>
    </div>
    """
    return page("Scene 7 · Engine two", css, body)


def _ui_scene(n: int, kicker: str, title: str, img: str, focus: tuple[float, float, float, float], start: float) -> str:
    css = """
    .h { top:150px; } .h h1 { font-size:60px; }
    .shot { position:absolute; left:120px; top:270px; width:1680px; height:757px; border-radius:18px; overflow:hidden; border:1px solid var(--line); box-shadow:0 20px 60px rgba(0,0,0,.12); }
    .shot img { width:1680px; height:757px; display:block; }
    .kb { position:relative; width:1680px; height:757px; }
    .focus { position:absolute; border-radius:14px; box-shadow: 0 0 0 4px var(--accent), 0 0 0 9999px rgba(250,248,245,.72); opacity:0; animation: fade .6s ease-out both; }
    """
    l, t, w, h = focus
    body = chrome(kicker, n) + f"""
    <div class="h fade" style="--d:.2s"><h1>{title}</h1></div>
    <div class="shot fade" style="--d:.3s"><div class="kb"><img src="{img}">
      <div class="focus" style="left:{l}%; top:{t}%; width:{w}%; height:{h}%; animation-delay:var(--c-ring, {start}s)"></div></div></div>
    """
    return page(f"Scene {n} · {kicker}", css, body)


def _focus(key: str, default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Highlight rectangle measured from the live page at capture time
    (scenes/focus.json, written by the screenshot step); falls back to the
    hand-set default. Small padding so the ring does not touch the card."""
    try:
        r = json.loads((SCENES / "focus.json").read_text())[key]
        pad_x, pad_y = 0.4, 0.9
        return (r["l"] - pad_x, r["t"] - pad_y, r["w"] + 2 * pad_x, r["h"] + 2 * pad_y)
    except Exception:
        return default


def scene08() -> str:
    return _ui_scene(8, "The live app", "Every idea, and every no, on one page.", "dash_overview.jpg",
                     _focus("overview", (83.0, 16.0, 14.8, 30.5)), 2.6)


def scene09() -> str:
    return _ui_scene(9, "The live app", "The limits page reads straight from the code that trades.", "dash_risk.jpg",
                     _focus("risk", (23.2, 89.8, 73.2, 8.4)), 3.5)


def scene10() -> str:
    cmd = ("alpaca order submit --order-class mleg --qty 15 --type limit --limit-price=-0.28 "
           "--time-in-force day --legs '[{\"symbol\":\"T261002C00030000\",\"side\":\"sell\",\"ratio_qty\":\"1\"},"
           "{\"symbol\":\"T261002C00032000\",\"side\":\"buy\",\"ratio_qty\":\"1\"}]'")
    css = """
    .stage { background:#18181c; }
    .term { position:absolute; left:120px; top:320px; width:1680px; height:600px; border-radius:18px; background:#0f0f12; border:1px solid #2a2a30; padding:38px 44px; font-family: "SF Mono", Menlo, monospace; font-size:30px; line-height:1.55; color:#e8e8ec; }
    .dots { display:flex; gap:10px; margin-bottom:26px; } .dots i { width:14px; height:14px; border-radius:50%; background:#3a3a42; display:block; }
    .cmd { white-space:pre-wrap; word-break:break-all; color:#e8e8ec; }
    .typed span { opacity:0; animation: fade .01s linear both; }
    .prompt { color:#7ee2a0; }
    .out { margin-top:22px; color:#6f6f7a; white-space:pre; animation: fade .05s var(--c-reply, 5.0s) both; }
    .out b { color:#7ee2a0; font-weight:700; }
    .jl { margin-top:24px; color:#6f6f7a; font-size:26px; animation: fade .05s var(--c-logged, 6.8s) both; }
    .jl b { color:#fff; }
    .fc { margin-top:14px; color:#fff; font-size:30px; font-weight:800; animation: fade .05s var(--c-fails, 8.0s) both; }
    """
    typed = "".join(f'<span style="animation-delay:{0.6 + k * 0.019:.3f}s">{c}</span>' for k, c in enumerate(cmd))
    body = chrome("Alpaca", 10) + f"""
    <div class="h fade" style="--d:.2s"><h1>Every order goes out through Alpaca's own command line tool.</h1></div>
    <div class="term fade" style="--d:.3s">
      <div class="dots"><i></i><i></i><i></i></div>
      <div class="cmd"><span class="prompt">$ </span><span class="typed">{typed}</span></div>
      <div class="out">{{
  "id": "1c9e…a4f2",  "client_order_id": "oa-4dacc2da-8f31c0e2",
  "order_class": "mleg",  "status": <b>"accepted"</b>,  "legs": 2
}}</div>
      <div class="jl">data/cli_calls.jsonl · {{"argv":["alpaca","order","submit",…],"ok":true,<b>"exit_code":0,"ms":171</b>}}</div>
      <div class="fc">If the tool fails, nothing opens. There is no backup path for new bets.</div>
    </div>
    """
    return page("Scene 10 · Alpaca", css, body, dark=True)


def scene11() -> str:
    css = """
    .h h1 { font-size:64px; }
    .row { position:absolute; left:120px; top:420px; display:flex; gap:14px; }
    .dot { width:46px; height:46px; border-radius:50%; background:var(--ink); }
    .dot.r { animation: red .35s ease-out both; animation-delay: var(--d); }
    @keyframes red { to { background: var(--loss); transform: scale(1.12); } }
    .dot.g { animation: grey .5s ease-out var(--c-floor, 10.7s) both; }
    @keyframes grey { to { background:#d9d5cf; } }
    .dot.k { animation: keep .5s ease-out var(--c-floor, 10.7s) both; }
    @keyframes keep { to { background:var(--gain); } }
    .lbl { position:absolute; left:120px; top:340px; font-size:34px; font-weight:800; color:var(--muted); }
    .zero { position:absolute; left:1560px; top:300px; font-size:240px; font-weight:900; letter-spacing:-12px; color:var(--gain); line-height:1; animation: fade .4s var(--c-zero, 13.0s) both; }
    .zero small { display:block; font-size:34px; letter-spacing:0; color:var(--muted); font-weight:700; margin-top:-10px; }
    .cap { position:absolute; left:120px; top:540px; font-size:40px; line-height:1.5; max-width:1300px; }
    .cap .a { animation: fade .4s var(--c-eight, 4.5s) both; display:block; }
    .cap .b { animation: fade .4s var(--c-five, 12.0s) both; display:block; }
    .tests { position:absolute; left:120px; bottom:120px; font-size:28px; font-weight:700; color:var(--muted); }
    """
    reds = {1, 4, 6, 9, 12, 15, 18, 21}
    keeps = {0, 2, 3, 5, 7, 8, 10, 11, 13, 14, 16, 17, 19, 20, 22}
    dots = []
    for k in range(23):
        if k in reds:
            dots.append(f'<div class="dot r" style="--d:calc(var(--c-eight, 4.5s) + {0.08 * len([r for r in reds if r < k]):.2f}s)"></div>')
        elif k in keeps:
            dots.append('<div class="dot k"></div>')
        else:
            dots.append('<div class="dot g"></div>')
    body = chrome("Proof", 11) + f"""
    <div class="h fade" style="--d:.2s"><h1>We replayed a real day before betting. It found a bug.</h1></div>
    <div class="lbl fade" style="--d:.5s">23 bets the old rules would have made</div>
    <div class="row fade" style="--d:.6s">{"".join(dots)}</div>
    <div class="cap"><span class="a"><b style="color:var(--loss)">8</b> were losers the moment they opened: the price to get out was more than the fee coming in.</span>
      <span class="b">Fixed how the pair is chosen, added the last check: <b style="color:var(--gain)">15 bets allowed, 0 losers on arrival.</b></span></div>
    <div class="zero">0<small>losers on arrival</small></div>
    <div class="tests">276 automated tests · replay of the Sept 1 option prices</div>
    """
    return page("Scene 11 · Proof", css, body)


def scene12() -> str:
    """Honesty scene: what it is not."""
    css = """
    .h h1 { font-size:64px; }
    .grid { position:absolute; left:120px; top:320px; width:1680px; display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:40px; }
    .b { padding:40px 44px; }
    .b h3 { margin:0 0 18px; font-size:30px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); }
    .b p { margin:0; font-size:34px; line-height:1.5; }
    .b.no h3 { color:var(--accent-dark); }
    """
    body = chrome("Straight talk", 12) + """
    <div class="h fade" style="--d:.2s"><h1>What it is, and what it isn't.</h1></div>
    <div class="grid">
      <div class="b card pop" style="--d:var(--c-is, 1.5s)"><h3>It is</h3><p>A discipline machine. It puts the same small, capped bet on the same rules every day, and it writes down every idea it turned away, so you can check its work.</p></div>
      <div class="b card no pop" style="--d:var(--c-isnt, 7.0s)"><h3>It isn't</h3><p>A money printer. Two days on a practice account is not a track record. What you can verify today is the behavior: how it sizes, how it exits, and how often it says no.</p></div>
    </div>
    """
    return page("Scene 12 · Straight talk", css, body)


def scene13(n: dict) -> str:
    css = """
    .stage { background:#18181c; }
    .h h1 { font-size:60px; }
    .url { position:absolute; left:120px; top:380px; font-size:88px; font-weight:900; color:#fff; letter-spacing:-2px; }
    .line { position:absolute; left:124px; top:520px; font-size:38px; color:#d9d9de; font-weight:600; line-height:1.6; }
    .line b { color:#fff; }
    .repo { position:absolute; left:124px; bottom:130px; font-size:30px; color:#9a9aa3; font-weight:600; }
    .repo b { color:#fff; }
    """
    body = chrome("Go check it", 13) + f"""
    <div class="h fade" style="--d:.2s"><h1>Every idea and every no is on the dashboard. Go check it.</h1></div>
    <div class="url fade" style="--d:var(--c-dash, 7.3s)">optionsagent-production.up.railway.app</div>
    <div class="line fade" style="--d:.4s">Practice account <b>{n['account_number']}</b> · $100,000 start · now <b>{money(n['equity'])}</b><br>
      {n['fills_total']} completed orders in the window · {n['fills_options']} option bets · snapshot {n['as_of']}</div>
    <div class="repo fade" style="--d:var(--c-check, 8.4s)"><b>github.com/Jhosshua/OptionsAgent</b> · MIT · team Convexity</div>
    {alpaca("idle", "right:130px; bottom:110px; width:240px; height:240px;")}
    """
    return page("Scene 13 · Results", css, body, dark=True)


# --------------------------------------------------------------------------- one-pager

def onepager(n: dict) -> str:
    css = """
    @page { size: 8.5in 11in; margin: 0; }
    html, body { width:816px; height:1056px; overflow:hidden; }
    .stage { width:816px; height:1056px; background:#fff; padding:44px 48px 40px; position:relative; }
    .top { display:flex; align-items:center; gap:10px; }
    .top .mark { width:30px; height:30px; border-radius:8px; background:var(--accent); display:grid; place-items:center; }
    .top .name { font-weight:800; font-size:18px; letter-spacing:-.3px; }
    .top .kick { color:var(--muted); font-size:12px; font-weight:600; margin-left:6px; }
    h1 { font-size:26px; letter-spacing:-.6px; margin:14px 0 4px; }
    .lede { font-size:12.5px; color:var(--muted); font-weight:600; line-height:1.4; }
    h2 { margin:14px 0 6px; font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color:var(--accent-dark); }
    p { margin:0 0 6px; font-size:11.6px; line-height:1.45; }
    .grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:0 28px; }
    .box { border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin-top:6px; background:var(--paper); }
    .box p { font-size:11.2px; }
    .kv { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:10px; margin-top:8px; }
    .kv > div { border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
    .kv .l { font-size:10px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }
    .kv .v { font-size:18px; font-weight:900; letter-spacing:-.4px; margin-top:2px; }
    .foot { position:absolute; left:48px; right:48px; bottom:26px; font-size:10px; color:var(--faint); font-weight:600; display:flex; justify-content:space-between; }
    """
    body = f"""
    <div class="top"><div class="mark">{W_MARK.format(s=18, c="#fff")}</div><div class="name">Wingspan</div><div class="kick">Alpaca AI Trading Agents Hackathon 2026 · team Convexity</div></div>
    <h1>A trading helper that knows when to say no.</h1>
    <div class="lede">An AI is allowed to have ideas. Fixed rules decide how much to bet, when to get out, and when to do nothing, and Alpaca's official command line tool places every order. Practice account {n['account_number']}, $100,000 start. This page describes the code that is running today.</div>

    <h2>Who it is for, and why</h2>
    <p>Everyday options traders, the people trading on a phone after work. They are now up to 60% of same-day S&amp;P 500 option volume (Cboe, 2025), and as a group they lost $2.1 billion in twenty months, most of it to the cost of trading rather than bad picks (Journal of Finance, 2023). Behavior research finds the same pattern after a losing streak: bet bigger, trade more. The problem is not picking stocks. It is size, exits, and knowing when to do nothing. Wingspan does exactly those three things, and nothing else.</p>

    <div class="grid">
      <div>
        <h2>Engine one · a small, capped bet</h2>
        <p>Every morning the AI reads six weeks of prices for thirteen well-known stocks and answers one question per stock: is there a bet here, and how sure am I. It cannot pick a size, a price, or an exit, and it cannot place an order.</p>
        <p>The rules turn a yes into a bet with a fixed worst case: sell a contract five to six weeks out at a price the stock probably will not reach and collect a fee, then buy a second contract behind it so the most you can lose is set before the order goes out. Five checks follow. Sure enough (70% or more). Not already in this stock, three bets at most. Never more than $3,000 at risk. Far enough from today's price. And cheap enough to get out of: the fee must be at least ten cents, and the cost to undo the bet on the same prices must be under one and a half times the fee, so the exit rule cannot fire the moment the bet opens.</p>
        <p>The order goes out as one order for both contracts. Only what actually filled is recorded; the rest is cancelled.</p>
        <p>Getting out is a separate program with no AI, every twenty minutes: take the win at half the fee, cut the loss at double the fee (only after 10 am and only when two checks in a row agree), and never hold into the last three weeks. A bet is marked closed only when the exit order actually fills.</p>
      </div>
      <div>
        <h2>Engine two · shares, no AI</h2>
        <p>It watches the two biggest index funds, SPY and QQQ. If the price runs too far too fast in the first forty five minutes, at 10:15 it bets on a pullback. If the market opened with a jump of more than 0.8%, at 1 pm it goes with the jump. Two rules, found in six months of minute by minute data and frozen on August 28. Each trade is $20,000, out at a 0.7% loss or after two hours, two trades a day, everything closed by 3:50 pm, and it stops for the day after losing $300.</p>
        <h2>Alpaca</h2>
        <p>Account, positions, the market clock and every order run through Alpaca's official command line tool inside the container, pinned to a checked release. Each call is written to a log with whether it worked and how long it took. A lost reply is looked up by our own order id before it is called a failure. If the tool fails, no new bet opens; the one exception is engine two's 3:50 close, which may fall back to the software library and says so in the log. Prices come from separate read only data feeds. It runs on Railway on a schedule, and the public dashboard draws its limits page from the same functions the bot calls.</p>
        <h2>Checked before the first bet</h2>
        <p>We replayed the September 1 option prices. Eight of the twenty three bets the old rules would have made were losers the moment they opened. Two fixes: choose the pair that is cheapest to get out of, and refuse anything that still is not. Result: fifteen bets allowed, zero losers on arrival. On September 2 the live rules rejected both of the AI's ideas for exactly that reason, and the fix shipped the same morning. 280 automated tests.</p>
      </div>
    </div>

    <h2>Numbers, straight from the account · {n['as_of']}</h2>
    <div class="kv">
      <div><div class="l">Account value</div><div class="v">{money(n['equity'])}</div></div>
      <div><div class="l">Completed orders in the window</div><div class="v">{n['fills_total']} <span style="font-size:12px; color:var(--muted); font-weight:700;">· {n['fills_options']} option bets</span></div></div>
      <div><div class="l">Most at risk per bet</div><div class="v">$3,000</div></div>
    </div>
    <div class="box"><p><b>Disclosure.</b> The base code predates the event (July 2026). Built inside the window: engine two and its study, the Railway deployment, the DeepSeek AI, the dashboard rework, the command line transport, and the open gate with its cap and last check. The account was created August 30; nothing else has traded on it. Two days on a practice account is not a track record; what can be verified today is the behavior.</p></div>
    <div class="foot"><span>github.com/Jhosshua/OptionsAgent · MIT</span><span>optionsagent-production.up.railway.app</span></div>
    """
    return page("One-pager", css, body)


# --------------------------------------------------------------------------- idea boards (canvas page 2)

def idea_board(title: str, lines: list[str], picked: bool = False) -> str:
    css = """
    body { width:960px; height:540px; } .stage { width:960px; height:540px; padding:40px 44px; background:#fffdf8; border:2px dashed #cfc9bf; }
    h1 { font-size:34px; margin:0 0 18px; }
    .tag { display:inline-block; font-size:14px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color:#fff; background:var(--gain); padding:4px 10px; border-radius:999px; margin-bottom:12px; }
    p { margin:0 0 10px; font-size:20px; line-height:1.4; color:#3a3a42; }
    """
    body = (('<div class="tag">used in the video</div>' if picked else '') + f"<h1>{title}</h1>" + "".join(f"<p>{l}</p>" for l in lines))
    return page(title, css, body)


def main():
    SCENES.mkdir(parents=True, exist_ok=True)
    n = live_numbers()
    scenes = [scene01(), scene02(), scene03(), scene04(), scene05(), scene06(), scene07(), scene08(), scene09(),
              scene10(), scene11(), scene12(), scene13(n)]
    assert len(scenes) == TOTAL
    for old in SCENES.glob("Scene*.dc.html"):
        old.unlink()
    files = []
    for i, html in enumerate(scenes, 1):
        p = SCENES / f"Scene{i:02d}.dc.html"
        p.write_text(html)
        files.append(p.name)
    (SCENES / "Main.dc.html").write_text(scenes[0])
    (SCENES / "OnePager.dc.html").write_text(onepager(n))

    ideas = {
        "IdeaCouchTrader": ("The couch trader", [
            "Someone with a day job, trading options on a phone after work.",
            "Beat: a win notification, then a losing week, then \"double the next bet to make it back\".",
            "Why: it dramatizes the exact behavior the research finds after a losing streak.",
            "Risk: needs to stay warm, not mocking."], True),
        "IdeaGroupChat": ("The group chat", [
            "A friends' chat lights up with a hot tip; three people pile in; one screenshot of a big win, then silence.",
            "Why: shows how ideas arrive in real life. Wingspan's point is that ideas are the cheap part.",
            "Risk: more characters, harder to read in 12 seconds."], False),
        "IdeaCommuter": ("The commuter", [
            "On the train home, one thumb, checking a position every 30 seconds, missing the stop.",
            "Why: the anxiety of managing exits by hand is the thing the exit engine removes.",
            "Risk: quieter emotionally than the losing streak."], False),
        "IdeaCustomerNeed": ("Customer need, with sources", [
            "$2.1B lost by retail options traders Nov 2019 to Jun 2021, mostly trading costs. Bryzgalova, Pavlova, Sikorskaya, Journal of Finance 2023.",
            "Retail up to 60% of same-day S&P 500 option volume; record volume six years running. Cboe / John Lothian News 2025.",
            "After a losing streak traders increase size and frequency. Behavior research summarised by PnL blog and RIA 2026.",
            "Retail loses 5 to 9% on average around earnings, 10 to 14% on high expected volatility. MIT Sloan / de Silva et al."], False),
    }
    for fname, (title, lines, picked) in ideas.items():
        (SCENES / f"{fname}.dc.html").write_text(idea_board(title, lines, picked))

    boards = [{"file": "Main.dc.html", "x": 0, "y": 0, "w": 1920, "h": 1080, "title": "Scene 1 · Cover", "page": "video"}]
    for i, f in enumerate(files[1:], 2):
        col, row = (i - 1) % 3, (i - 1) // 3
        boards.append({"file": f, "x": col * 2040, "y": row * 1260, "w": 1920, "h": 1080, "title": f"Scene {i}", "page": "video"})
    boards.append({"file": "OnePager.dc.html", "x": 2040, "y": 4 * 1260, "w": 816, "h": 1056, "title": "One-pager (Letter)", "print": "fixed", "page": "video"})
    for k, fname in enumerate(ideas):
        boards.append({"file": f"{fname}.dc.html", "x": (k % 2) * 1080, "y": (k // 2) * 680, "w": 960, "h": 540, "page": "ideas"})
    canvas = {
        "pages": [{"id": "video", "name": "Video scenes"}, {"id": "ideas", "name": "Ideas + research"}],
        "artboards": boards,
        "annotations": [
            {"id": "brief", "x": 0, "y": -220, "w": 900, "page": "video",
             "text": "Wingspan hackathon video. Each artboard is one scene, 1920x1080, 24 fps. The video is rendered frame-by-frame from these exact files (submission/video/render.py); reveals lock to the narration's word timings."},
            {"id": "ideas-note", "x": 0, "y": -200, "w": 900, "page": "ideas",
             "text": "Customer vignette directions. The couch trader is in the video; the other two are sketched here to compare. The research board lists the sources behind scene 3."},
        ],
        "launch": {"view": "canvas", "page": "video"},
    }
    (SCENES / "canvas.json").write_text(json.dumps(canvas, indent=1))
    print("scenes:", len(files), "ideas:", len(ideas), "numbers:", json.dumps(n))


if __name__ == "__main__":
    main()
