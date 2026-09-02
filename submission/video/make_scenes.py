#!/usr/bin/env python3
"""Emit the nine animated 1920x1080 scene artboards (Scene01..Scene09.dc.html)
plus canvas.json for the design canvas. The SAME files are what render.py
captures frame-by-frame into the video, so the canvas is the single source of
truth for the look.

Design tokens are lifted from dashboard/app.css (Nunito Sans, --accent #e5484d,
--accent-dark #b8383c, --ink #222, --muted #717171, --line #ebebeb, radius 16px)
so the video looks like the product it demos.

Animation contract (used by render.py): every motion is a CSS animation with
`animation-fill-mode: both`; the renderer pauses all animations and seeks
`currentTime`. Scene length is injected as the CSS variable --dur (seconds), so
slow pans (Ken Burns) stretch to the narration while reveals stay fixed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
sys.path.insert(0, str(HERE.parent))  # submission/
from build import live_numbers, money  # noqa: E402

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
.stage { position:relative; width:1920px; height:1080px; overflow:hidden; background:var(--bg); }
.topbar { position:absolute; left:0; top:0; width:1920px; height:12px; background:var(--accent); }
.brand { position:absolute; left:96px; top:56px; display:flex; align-items:center; gap:14px; }
.brand .mark { width:44px; height:44px; border-radius:12px; background:var(--accent); display:grid; place-items:center; }
.brand .name { font-weight:800; font-size:26px; letter-spacing:-.4px; }
.brand .kick { color:var(--muted); font-weight:600; font-size:24px; margin-left:10px; }
.foot { position:absolute; left:96px; bottom:48px; color:var(--faint); font-size:24px; font-weight:600; }
.pn { position:absolute; right:96px; bottom:48px; color:var(--faint); font-size:24px; font-weight:600; }
h1 { margin:0; font-weight:900; letter-spacing:-1.5px; line-height:1.02; }
.rise { animation: rise .7s cubic-bezier(.2,.7,.2,1) both; animation-delay: var(--d, 0s); }
.pop  { animation: pop .55s cubic-bezier(.34,1.56,.64,1) both; animation-delay: var(--d, 0s); }
.fade { animation: fade .6s ease-out both; animation-delay: var(--d, 0s); }
@keyframes rise { from { opacity:0; transform: translateY(28px); } to { opacity:1; transform:none; } }
@keyframes pop  { from { opacity:0; transform: scale(.82); } to { opacity:1; transform: scale(1); } }
@keyframes fade { from { opacity:0; } to { opacity:1; } }
.kb { animation: kb var(--dur) linear both; transform-origin: 50% 40%; }
@keyframes kb { from { transform: scale(1); } to { transform: scale(1.035); } }
.chip { display:inline-flex; align-items:center; gap:12px; padding:14px 26px; border-radius:999px; background:var(--wash);
        color:var(--accent-dark); font-weight:800; font-size:30px; }
.card { background:#fff; border:1px solid var(--line); border-radius:var(--radius); box-shadow:0 10px 30px rgba(0,0,0,.06); }
/* alpaca mascot */
.alpaca { position:absolute; width:260px; height:260px; }
.alpaca .leg { transform-origin: 50% 0; }
.alpaca.walk .leg.a { animation: step .5s ease-in-out infinite alternate; }
.alpaca.walk .leg.b { animation: step .5s ease-in-out infinite alternate-reverse; }
.alpaca.walk .body, .alpaca.idle .body { animation: bob 1.1s ease-in-out infinite alternate; transform-origin:50% 100%; }
.alpaca .head { transform-origin: 30% 90%; }
.alpaca.nod .head { animation: nod 1.6s ease-in-out infinite; }
.alpaca .lid { transform-origin: 50% 50%; animation: blink 3.4s linear infinite; }
@keyframes step  { from { transform: rotate(-14deg); } to { transform: rotate(14deg); } }
@keyframes bob   { from { transform: translateY(0); } to { transform: translateY(-7px); } }
@keyframes nod   { 0%,60%,100% { transform: rotate(0); } 75% { transform: rotate(9deg); } 90% { transform: rotate(-4deg); } }
@keyframes blink { 0%,92%,100% { transform: scaleY(1); } 95% { transform: scaleY(.1); } }
"""

# A flat alpaca, drawn once. Legs split into two phase groups (a/b) for the walk cycle.
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


def alpaca(cls: str, style: str) -> str:
    return ALPACA_SVG.format(cls=cls, style=style)


def page(title: str, css: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
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


def chrome(kicker: str, n: int, total: int = 10) -> str:
    return (f'<div class="topbar"></div>'
            f'<div class="brand rise" style="--d:.05s"><div class="mark">{W_MARK.format(s=28, c="#fff")}</div>'
            f'<div class="name">Wingspan</div><div class="kick">{kicker}</div></div>'
            f'<div class="foot">Alpaca AI Trading Agents Hackathon 2026 · paper account PA371G5THNUO</div>'
            f'<div class="pn">{n} / {total}</div>')


def scene01() -> str:
    css = """
    .stage { background:#18181c; }
    .panel { position:absolute; left:0; top:0; width:560px; height:1080px; background:var(--accent); }
    .bigw { position:absolute; left:110px; top:360px; }
    .bigw path { stroke-dasharray: 60; stroke-dashoffset: 60; animation: draw .9s cubic-bezier(.2,.7,.2,1) .15s both; }
    @keyframes draw { to { stroke-dashoffset: 0; } }
    .title { position:absolute; left:660px; top:340px; }
    .title h1 { font-size:168px; color:#fff; }
    .tag { position:absolute; left:664px; top:530px; font-size:56px; font-weight:700; color:#fff; letter-spacing:-.6px; }
    .meta { position:absolute; left:664px; bottom:64px; font-size:26px; color:#9a9aa3; font-weight:600; }
    .walkin { position:absolute; right:120px; bottom:130px; animation: walkin 2.2s cubic-bezier(.3,.7,.3,1) 1.9s both; }
    @keyframes walkin { from { transform: translateX(560px); } to { transform: translateX(0); } }
    """
    body = f"""
    <div class="panel"></div>
    <div class="bigw">{W_MARK.format(s=340, c="#fff")}</div>
    <div class="title fade" style="--d:.9s"><h1>WINGSPAN</h1></div>
    <div class="tag fade" style="--d:var(--c-agent, 1.6s)">An options agent that mostly says no.</div>
    <div class="meta fade" style="--d:1.6s">Alpaca AI Trading Agents Hackathon 2026 · team Convexity · paper account PA371G5THNUO</div>
    <div class="walkin">{alpaca("walk", "position:relative; width:250px; height:250px;")}</div>
    """
    return page("Scene 1 · Cover", css, body)



# A flat developer at a laptop. Eyebrows and mouth are separate so the face can change.
DEV_SVG = """
<svg class="dev" viewBox="0 0 420 420" fill="none" style="{style}">
  <rect x="60" y="300" width="300" height="18" rx="9" fill="#e6e1da"/>
  <rect x="150" y="236" width="150" height="70" rx="8" fill="#3a3a42"/>
  <rect x="158" y="244" width="134" height="52" rx="4" fill="#5d5d68"/>
  <rect x="140" y="300" width="170" height="10" rx="5" fill="#2a2a30"/>
  <path d="M110 300 q0 -80 60 -100 l60 0 q60 20 60 100 Z" fill="#222"/>
  <path d="M170 210 q-40 20 -30 90" stroke="#222" stroke-width="26" stroke-linecap="round"/>
  <path d="M250 210 q40 20 30 90" stroke="#222" stroke-width="26" stroke-linecap="round"/>
  <circle cx="210" cy="150" r="56" fill="#f1c9a5"/>
  <path d="M154 140 q10 -60 66 -58 q54 -2 60 58 q-20 -30 -60 -28 q-40 -2 -66 28 Z" fill="#2b2118"/>
  <g class="brows"><path d="M184 128 l20 -4" stroke="#2b2118" stroke-width="5" stroke-linecap="round"/><path d="M216 124 l20 4" stroke="#2b2118" stroke-width="5" stroke-linecap="round"/></g>
  <circle cx="192" cy="146" r="4.5" fill="#222"/><circle cx="228" cy="146" r="4.5" fill="#222"/>
  <path class="mouth" d="M196 172 q14 10 28 0" stroke="#8b4a3c" stroke-width="4" stroke-linecap="round" fill="none"/>
  <text class="bang" x="292" y="96" font-family="Nunito Sans, sans-serif" font-weight="900" font-size="72" fill="#222">!</text>
</svg>
"""


def scene02() -> str:
    """The problem, as a 10 second vignette: a developer hands an LLM the keys."""
    css = """
    .stage { background:var(--paper); }
    .who { position:absolute; left:120px; top:180px; color:var(--muted); font-weight:700; font-size:26px; letter-spacing:.06em; text-transform:uppercase; }
    .dev { position:absolute; left:120px; top:300px; width:560px; height:560px; }
    .dev .brows { transform-origin: 210px 130px; animation: worry .5s ease-out var(--c-idea, 9.8s) both; }
    @keyframes worry { to { transform: translateY(-9px) rotate(-6deg); } }
    .dev .mouth { animation: flat .5s ease-out var(--c-idea, 9.8s) both; }
    @keyframes flat { to { d: path("M196 176 q14 -6 28 0"); } }
    .dev .bang { opacity:0; animation: pop .35s cubic-bezier(.34,1.56,.64,1) var(--c-idea, 9.8s) both; }
    .say { position:absolute; padding:26px 34px; border-radius:26px; font-size:38px; font-weight:700; line-height:1.35; box-shadow:0 10px 30px rgba(0,0,0,.06); }
    .say.me { left:560px; top:330px; background:#fff; border:1px solid var(--line); border-bottom-left-radius:6px; animation: pop .45s cubic-bezier(.2,.8,.3,1.1) var(--c-point, .5s) both; }
    .say.llm { left:760px; top:480px; background:var(--ink); color:#fff; border-bottom-right-radius:6px; max-width:900px; animation: pop .45s cubic-bezier(.2,.8,.3,1.1) var(--c-finds, 3.5s) both; }
    .say.llm b { color:#ff8a8e; font-weight:900; }
    .tag { font-size:22px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:#9a9aa3; display:block; margin-bottom:6px; }
    .say.me .tag { color:var(--muted); }
    .meter { position:absolute; left:760px; top:690px; width:900px; }
    .meter .l { display:flex; justify-content:space-between; font-size:26px; font-weight:800; color:var(--muted); margin-bottom:12px; }
    .meter .l b { color:var(--loss); }
    .meter .bar { height:30px; border-radius:10px; background:#e6e1da; overflow:hidden; }
    .meter .bar i { display:block; height:100%; width:0; background:var(--loss); animation: fill 1.6s cubic-bezier(.2,.7,.2,1) var(--c-178, 7.6s) both; }
    @keyframes fill { to { width:35.6%; } }
    .meter { opacity:0; animation: fade .3s var(--c-178, 7.6s) both; }
    .meter .big { font-size:64px; font-weight:900; letter-spacing:-2px; color:var(--ink); line-height:1; }
    .tag { font-size:24px; }
    .line { position:absolute; left:120px; top:880px; font-size:44px; font-weight:800; letter-spacing:-.6px; animation: fade .5s var(--c-never, 10.6s) both; }
    .line em { font-style:normal; color:var(--accent-dark); }
    """
    body = chrome("The problem", 2) + f"""
    <div class="who fade" style="--d:.2s">A developer points a language model at an Alpaca account</div>
    {DEV_SVG.format(style="")}
    <div class="say me"><span class="tag">developer</span>Find me a trade.</div>
    <div class="say llm"><span class="tag">language model</span>Sure. Sell call spreads on T.</div>
    <div class="meter"><div class="l"><span><span class="big">178</span>&nbsp; spreads. Our own first dry run sized it.</span><b>$35,600 · a third of the account</b></div><div class="bar"><i></i></div></div>
    <div class="line">It will always find a trade. It never says no, and it <em>can't count contracts.</em></div>
    """
    return page("Scene 2 · Problem", css, body)


def scene_scalper(n_index: int) -> str:
    """Engine two: the share scalper. No AI. Two mined rules on SPY and QQQ."""
    css = """
    .stage { background:var(--paper); }
    .h { position:absolute; left:120px; top:160px; } .h h1 { font-size:72px; }
    .chart { position:absolute; left:120px; top:300px; width:1040px; height:600px; }
    .chart .line { fill:none; stroke:var(--ink); stroke-width:5; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:2400; stroke-dashoffset:2400; animation: draw 3.2s cubic-bezier(.3,.6,.3,1) .6s both; }
    @keyframes draw { to { stroke-dashoffset:0; } }
    .chart .vwap { fill:none; stroke:var(--muted); stroke-width:3; stroke-dasharray:10 10; opacity:0; animation: fade .4s 1.0s both; }
    .chart .range { fill:rgba(34,34,34,.08); stroke:#b0b0b0; stroke-width:2; opacity:0; animation: fade .4s 1.4s both; }
    .chart text { font-family:"Nunito Sans", sans-serif; font-weight:800; }
    .row span { font-size:26px; }
    .mk { opacity:0; animation: pop .4s cubic-bezier(.34,1.56,.64,1) both; }
    .side { position:absolute; left:1240px; top:300px; width:560px; display:flex; flex-direction:column; gap:16px; }
    .row { display:flex; justify-content:space-between; align-items:center; padding:20px 28px; border-radius:14px; background:#fff; border:1px solid var(--line); font-size:30px; font-weight:800; }
    .row span { color:var(--muted); font-weight:700; font-size:26px; }
    .row.dark { background:var(--ink); color:#fff; } .row.dark span { color:#c9c9d1; }
    """
    body = chrome("Engine two", n_index) + f"""
    <div class="h fade" style="--d:.2s"><h1>The second engine trades shares. No AI in it.</h1></div>
    <svg class="chart fade" style="--d:.4s" viewBox="0 0 1040 600">
      <rect class="range" x="60" y="230" width="36" height="200" rx="6"/>
      <text x="60" y="466" font-size="24" fill="#717171">first 15 min</text>
      <path class="vwap" d="M60 340 C 260 330, 520 380, 980 300"/>
      <text x="700" y="372" font-size="24" fill="#717171">VWAP</text>
      <path class="line" d="M60 340 L80 290 L96 410 L125 200 L180 300 L260 350 L340 300 L420 380 L500 330 L565 230 L640 250 L720 220 L800 260 L900 230 L980 250"/>
      <g class="mk" style="animation-delay:var(--c-fade, 5.5s)"><circle cx="125" cy="200" r="16" fill="#222"/><text x="150" y="176" font-size="28" fill="#222">10:15 · fade the overshoot</text></g>
      <g class="mk" style="animation-delay:var(--c-gap, 6.5s)"><circle cx="565" cy="230" r="16" fill="#222"/><text x="590" y="206" font-size="28" fill="#222">13:00 · follow a big gap</text></g>
      <line x1="60" y1="530" x2="980" y2="530" stroke="#ebebeb" stroke-width="2"/>
      <text x="60" y="566" font-size="24" fill="#717171">09:30</text><text x="560" y="566" font-size="24" fill="#717171">13:00</text><text x="860" y="566" font-size="24" fill="#717171">15:50 flat</text>
    </svg>
    <div class="side">
      <div class="row fade" style="--d:var(--c-spy, 4.2s)">SPY and QQQ <span>shares only</span></div>
      <div class="row fade" style="--d:var(--c-rules, 5.3s)">10:15 fade <span>13:00 gap follow</span></div>
      <div class="row fade" style="--d:var(--c-twenty, 8.0s)">$20,000 <span>per trade</span></div>
      <div class="row fade" style="--d:var(--c-twenty2, 8.9s)">0.7% stop <span>out after 120 minutes</span></div>
      <div class="row fade" style="--d:var(--c-two, 9.5s)">2 trades a day <span>$300 daily halt</span></div>
      <div class="row dark fade" style="--d:var(--c-flat, 11.0s)">Flat by 15:50 <span>same CLI, same journal</span></div>
    </div>
    """
    return page("Scene · Engine two", css, body)


def scene02_old() -> str:
    css = """
    .stage { background:var(--paper); }
    .who { position:absolute; left:120px; top:180px; color:var(--muted); font-weight:700; font-size:26px; letter-spacing:.06em; text-transform:uppercase; }
    .line { position:absolute; left:120px; top:240px; font-size:60px; font-weight:800; letter-spacing:-.8px; line-height:1.2; max-width:1400px; }
    .num { position:absolute; left:112px; top:440px; font-size:420px; font-weight:900; letter-spacing:-18px; line-height:1; color:var(--ink); }
    .cap { position:absolute; left:126px; top:900px; font-size:44px; font-weight:600; color:var(--muted); }
    .cap b { color:var(--accent-dark); font-weight:800; }
    """
    body = chrome("The problem", 2) + """
    <div class="who fade" style="--d:.2s">Customer: a developer pointing an LLM at an Alpaca account</div>
    <div class="line fade" style="--d:.4s">Give a language model a brokerage account and it will always find a trade.<br>It never says no, and it can't count contracts.</div>
    <div class="num fade" style="--d:5.2s">178</div>
    <div class="cap fade" style="--d:6.2s">contracts on <b>one idea</b>. Our first dry run, $100k paper account, before the cap.</div>
    """
    return page("Scene 2 · Problem", css, body)


def scene03() -> str:
    css = """
    .stage { background:var(--paper); }
    .cols { position:absolute; left:120px; top:280px; display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:72px; width:1680px; }
    .col h2 { margin:0 0 26px; font-size:30px; font-weight:800; color:var(--muted); letter-spacing:.05em; text-transform:uppercase; }
    .bubble { padding:40px 44px; border-radius:28px 28px 28px 6px; background:#fff; border:1px solid var(--line); box-shadow:0 10px 30px rgba(0,0,0,.06); font-size:44px; line-height:1.45; }
    .bubble b { color:var(--ink); font-weight:900; }
    .bubble .q { display:block; font-size:30px; color:var(--muted); margin-top:14px; }
    .stamps { display:flex; flex-direction:column; gap:20px; }
    .stamp { display:flex; align-items:center; justify-content:space-between; padding:24px 34px; border-radius:var(--radius); background:var(--ink); color:#fff; font-size:40px; font-weight:800; }
    .stamp span { color:#c9c9d1; font-weight:600; font-size:28px; }
    .stamp.red { background:var(--accent); } .stamp.red span { color:#ffe1e3; }
    .land { animation: land .42s cubic-bezier(.2,.8,.3,1.06) both; animation-delay: var(--d); }
    @keyframes land { from { opacity:0; transform: scale(1.18); } to { opacity:1; transform: scale(1); } }
    .h { position:absolute; left:120px; top:170px; } .h h1 { font-size:76px; }
    """
    body = chrome("The product", 3) + """
    <div class="h fade" style="--d:.2s"><h1>So we split the job.</h1></div>
    <div class="cols">
      <div class="col">
        <h2 class="fade" style="--d:.4s">The model answers one question</h2>
        <div class="bubble fade" style="--d:var(--c-model, 2.1s)"><b>T</b> · bearish · conviction <b>0.70</b>
          <span class="q">“Extended run into resistance on thin volume. Sell the premium.”</span></div>
      </div>
      <div class="col">
        <h2 class="fade" style="--d:.4s">Code does everything with a dollar sign</h2>
        <div class="stamps">
          <div class="stamp land" style="--d:var(--c-code, 7.6s)">Strike <span>0.15 to 0.30 delta · 30 to 45 days</span></div>
          <div class="stamp land" style="--d:var(--c-code2, 8.3s)">Size <span>hard cap $3,000</span></div>
          <div class="stamp land" style="--d:var(--c-code3, 9.0s)">Exit <span>50% profit · 2× stop, confirmed twice · 21 days</span></div>
          <div class="stamp land" style="--d:var(--c-code4, 9.7s)">Order <span>official Alpaca CLI</span></div>
        </div>
      </div>
    </div>
    """
    return page("Scene 3 · Product", css, body)


def scene04() -> str:
    css = """
    .stage { background:var(--paper); }
    .h { position:absolute; left:120px; top:170px; } .h h1 { font-size:72px; }
    .funnel { position:absolute; left:640px; top:300px; width:900px; display:flex; flex-direction:column; gap:16px; }
    .gate { height:86px; border-radius:14px; background:#fff; border:2px solid var(--line); display:flex; align-items:center; padding:0 34px; font-size:34px; font-weight:800; color:var(--muted); }
    .gate.g5 { animation: reject .45s var(--c-dies, 12.4s) both; }
    @keyframes reject { to { background:var(--wash); border-color:var(--accent); color:var(--accent-dark); } }
    .gate.g5 .no { margin-left:auto; color:var(--accent-dark); opacity:0; font-size:30px; animation: fade .3s var(--c-dies, 12.4s) both; }
    .token { position:absolute; left:560px; top:322px; width:44px; height:44px; border-radius:50%; background:var(--ink);
             animation: drop 6s cubic-bezier(.2,.7,.2,1) var(--c-drop, 1.2s) both; }
    @keyframes drop { 0% { transform: translateY(0); } 25% { transform: translateY(0); } 30% { transform: translateY(102px); }
                      45% { transform: translateY(102px); } 50% { transform: translateY(204px); } 65% { transform: translateY(204px); }
                      70% { transform: translateY(306px); } 83% { transform: translateY(306px); } 88%,100% { transform: translateY(408px); } }
    .side { position:absolute; left:120px; top:320px; width:380px; font-size:30px; color:var(--muted); line-height:1.5; }
    .side b { color:var(--ink); display:block; font-size:44px; margin-bottom:12px; }
    .note { position:absolute; left:120px; top:880px; font-size:40px; font-weight:800; color:var(--ink); animation: fade .4s var(--c-most, 13.8s) both; }
    """
    body = chrome("The rails", 4) + """
    <div class="h fade" style="--d:.2s"><h1>Then the idea has to survive the rails.</h1></div>
    <div class="side fade" style="--d:.5s"><b>Five gates</b>Any one can stop it. None can be loosened by config or by the model.</div>
    <div class="funnel">
      <div class="gate g1 fade" style="--d:.4s">Conviction ≥ 0.60</div>
      <div class="gate g2 fade" style="--d:.5s">One position per name · 3 spreads max</div>
      <div class="gate g3 fade" style="--d:.6s">$3,000 cap per position</div>
      <div class="gate g4 fade" style="--d:.7s">Strike rules · 0.15 to 0.30 delta · 30 to 45 days</div>
      <div class="gate g5 fade" style="--d:.8s">Liquidity: unwind cost &lt; 1.5× credit <span class="no">rejected</span></div>
    </div>
    <div class="token"></div>
    <div class="note">Most ideas die here. On purpose.</div>
    """
    return page("Scene 4 · Rails", css, body)


def _ui_scene(n: int, kicker: str, title: str, img: str, focus: tuple[float, float, float, float], start: float) -> str:
    """One highlighted region (left%, top%, width%, height%); everything else dims to 30%."""
    css = """
    .stage { background:var(--paper); }
    .h { position:absolute; left:120px; top:150px; } .h h1 { font-size:64px; }
    .shot { position:absolute; left:120px; top:270px; width:1680px; height:757px; border-radius:18px; overflow:hidden; border:1px solid var(--line); box-shadow:0 20px 60px rgba(0,0,0,.12); }
    .shot img { width:1680px; height:757px; display:block; transform: translateY(var(--imgy, 0px)); }
    .kb { position:relative; width:1680px; height:757px; }
    .focus { position:absolute; border-radius:14px; box-shadow: 0 0 0 4px var(--accent), 0 0 0 9999px rgba(250,248,245,.72); opacity:0; animation: fade .6s ease-out both; }
    """
    l, t, w, h = focus
    body = chrome(kicker, n + 1) + f"""
    <div class="h fade" style="--d:.2s"><h1>{title}</h1></div>
    <div class="shot fade" style="--d:.3s"><div class="kb"><img src="{img}">
      <div class="focus" style="left:{l}%; top:{t}%; width:{w}%; height:{h}%; animation-delay:var(--c-ring, {start}s)"></div></div></div>
    """
    return page(f"Scene {n} · {kicker}", css, body)


def scene05() -> str:
    return _ui_scene(5, "Live app", "The live app. Both engines, one book.", "dash_overview.jpg",
                     (83.0, 16.0, 14.8, 30.5), 2.6)


def scene06() -> str:
    return _ui_scene(6, "Live app", "That $3,000 comes from the same function the bot calls.", "dash_risk.jpg",
                     (23.2, 89.8, 73.2, 8.4), 3.5)


def scene07() -> str:
    cmd = ("alpaca order submit --order-class mleg --qty 15 --type limit --limit-price=-0.28 "
           "--time-in-force day --legs '[{\"symbol\":\"T261002C00030000\",\"side\":\"sell\",\"ratio_qty\":\"1\"},"
           "{\"symbol\":\"T261002C00032000\",\"side\":\"buy\",\"ratio_qty\":\"1\"}]'")
    css = """
    .stage { background:#18181c; }
    .brand .name, .foot, .pn { color:#fff; } .brand .kick { color:#9a9aa3; }
    .h { position:absolute; left:120px; top:160px; } .h h1 { font-size:72px; color:#fff; }
    .term { position:absolute; left:120px; top:320px; width:1680px; height:600px; border-radius:18px; background:#0f0f12; border:1px solid #2a2a30; padding:38px 44px; font-family: "SF Mono", Menlo, monospace; font-size:30px; line-height:1.55; color:#e8e8ec; }
    .dots { display:flex; gap:10px; margin-bottom:26px; } .dots i { width:14px; height:14px; border-radius:50%; background:#3a3a42; display:block; }
    .cmd { white-space:pre-wrap; word-break:break-all; color:#e8e8ec; }
    .typed { display:inline; }
    .typed span { opacity:0; animation: fade .01s linear both; }
    .prompt { color:#7ee2a0; }
    .out { margin-top:22px; color:#6f6f7a; white-space:pre; animation: fade .05s var(--c-json, 5.0s) both; }
    .out b { color:#7ee2a0; font-weight:700; }
    .jl { margin-top:24px; color:#6f6f7a; font-size:26px; animation: fade .05s var(--c-exit, 6.8s) both; }
    .jl b { color:#fff; }
    .fc { margin-top:14px; color:#fff; font-size:30px; font-weight:800; animation: fade .05s var(--c-fails, 8.0s) both; }
    """
    # per-character typewriter: deterministic under seek (steps() on max-width is not, for wrapped text)
    typed = "".join(f'<span style="animation-delay:{0.6 + k * 0.019:.3f}s">{c}</span>' for k, c in enumerate(cmd))
    body = chrome("Alpaca", 8) + f"""
    <div class="h fade" style="--d:.2s"><h1>Every order goes out through Alpaca's own CLI.</h1></div>
    <div class="term fade" style="--d:.3s">
      <div class="dots"><i></i><i></i><i></i></div>
      <div class="cmd"><span class="prompt">$ </span><span class="typed">{typed}</span></div>
      <div class="out">{{
  "id": "1c9e…a4f2",  "client_order_id": "oa-4dacc2da-8f31c0e2",
  "order_class": "mleg",  "status": <b>"accepted"</b>,  "legs": 2
}}</div>
      <div class="jl">data/cli_calls.jsonl · {{"argv":["alpaca","order","submit",…],"ok":true,<b>"exit_code":0,"ms":171</b>}}</div>
      <div class="fc">If the CLI fails, nothing opens.</div>
    </div>
    """
    return page("Scene 7 · Alpaca CLI", css, body)


def scene08() -> str:
    css = """
    .stage { background:var(--paper); }
    .h { position:absolute; left:120px; top:160px; } .h h1 { font-size:72px; }
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
    .cap { position:absolute; left:120px; top:540px; font-size:40px; line-height:1.5; max-width:1300px; color:var(--ink); }
    .cap .a { animation: fade .4s var(--c-eight, 4.5s) both; display:block; }
    .cap .b { animation: fade .4s var(--c-five, 12.0s) both; display:block; }
    .tests { position:absolute; left:120px; bottom:120px; font-size:28px; font-weight:700; color:var(--muted); }
    """
    reds = {1, 4, 6, 9, 12, 15, 18, 21}
    keeps = {2, 7, 11, 16, 20}
    dots = []
    for k in range(23):
        if k in reds:
            dots.append(f'<div class="dot r" style="--d:calc(var(--c-eight, 4.5s) + {0.08 * len([r for r in reds if r < k]):.2f}s)"></div>')
        elif k in keeps:
            dots.append('<div class="dot k"></div>')
        else:
            dots.append('<div class="dot g"></div>')
    body = chrome("Proof", 9) + f"""
    <div class="h fade" style="--d:.2s"><h1>We replayed a day of real option chains first.</h1></div>
    <div class="lbl fade" style="--d:.5s">23 spreads the open gate would have taken</div>
    <div class="row fade" style="--d:.6s">{"".join(dots)}</div>
    <div class="cap"><span class="a"><b style="color:var(--loss)">8</b> were already past their own stop on the quotes they were picked from.</span>
      <span class="b">With the liquidity floor: <b style="color:var(--gain)">5 admitted, 0 past the stop.</b></span></div>
    <div class="zero">0<small>past the stop</small></div>
    <div class="tests">276 tests · replay of the Sept 1 chain snapshots</div>
    """
    return page("Scene 8 · Proof", css, body)


def scene09(n: dict) -> str:
    css = """
    .stage { background:#18181c; }
    .brand .name, .foot, .pn { color:#fff; } .brand .kick { color:#9a9aa3; }
    .h { position:absolute; left:120px; top:170px; } .h h1 { font-size:64px; color:#fff; }
    .url { position:absolute; left:120px; top:380px; font-size:88px; font-weight:900; color:#fff; letter-spacing:-2px; }
    .url span { color:#fff; }
    .line { position:absolute; left:124px; top:520px; font-size:40px; color:#d9d9de; font-weight:600; line-height:1.6; }
    .line b { color:#fff; }
    .repo { position:absolute; left:124px; bottom:130px; font-size:30px; color:#9a9aa3; font-weight:600; }
    .repo b { color:#fff; }
    """
    body = chrome("Results", 10) + f"""
    <div class="h fade" style="--d:.2s"><h1>Every idea and every no is on the dashboard. Go check it.</h1></div>
    <div class="url fade" style="--d:var(--c-dash, 7.3s)">optionsagent-production<span>.up.railway.app</span></div>
    <div class="line fade" style="--d:.4s">Paper account <b>{n['account_number']}</b> · $100,000 start · equity <b>{money(n['equity'])}</b><br>
      {n['fills_total']} filled orders in the window · {n['fills_options']} options · snapshot {n['as_of']}</div>
    <div class="repo fade" style="--d:var(--c-check, 8.4s)"><b>github.com/Jhosshua/OptionsAgent</b> · MIT · team Convexity</div>
    {alpaca("idle", "right:130px; bottom:110px; width:240px; height:240px;")}
    """
    return page("Scene 9 · Results", css, body)



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
    <h1>An options agent that mostly says no.</h1>
    <div class="lede">A language model may propose a trade. Code decides every strike, size and exit, and Alpaca's official CLI places every order. Paper account {n['account_number']}, $100,000 start. This page describes the code that is running today.</div>

    <h2>The customer problem</h2>
    <p>Point a language model at a brokerage account and it will always find a trade. It never says no, and it cannot count contracts. Our own first dry run wanted 178 contracts on one idea. Wingspan is built for a developer who wants to hand an LLM an Alpaca account and not babysit it.</p>

    <div class="grid">
      <div>
        <h2>Engine one · credit spread seller</h2>
        <p>Once a day at 10:15 ET, DeepSeek reads 13 liquid names with forty days of price context and answers one question per name: is there a trade, which direction, how sure. It cannot name a strike, a size or an exit, and it cannot place an order.</p>
        <p>Code picks the contracts (short strike at 0.15 to 0.30 delta, 30 to 45 days out, at most $2 wide) and runs five gates: conviction of at least 0.60, one position per name and six open legs at most, a $3,000 cap per position, the strike rules, and a liquidity floor of ten cents credit with an unwind cost under 1.5 times the credit, so the exit rule cannot stop the trade out on its own entry.</p>
        <p>One multi leg limit order goes out at the net credit. Only the filled count is booked; the remainder is cancelled.</p>
        <p>Exits run every twenty minutes with no AI: half the credit, or twice the credit after 10:00 ET on two consecutive sweeps, or 21 days to expiry. A spread is closed only when the unwind fills.</p>
      </div>
      <div>
        <h2>Engine two · share scalper</h2>
        <p>No AI in it. Two rules on SPY and QQQ, mined from six months of minute bars and frozen on August 28. At 10:15 ET it fades a close that overshoots both the session VWAP and the first fifteen minutes' range. At 13:00 ET it follows a QQQ gap larger than 0.8%. Twenty thousand dollars a trade, two trades a day, a 0.7% stop, out after 120 minutes, flat by 15:50 ET, and a $300 daily loss halt.</p>
        <h2>Alpaca infrastructure</h2>
        <p>Account, positions, clock and every order run through the official Alpaca CLI as a subprocess inside the container, pinned to a checksummed release. Each call is journaled with its exit code and latency. A lost reply is looked up by our own client order id before it is called a failure. On any error nothing opens; the one exception is the scalper's end of day flatten, which may fall back to the SDK and says so in the journal. Option chains come from a read only market data sidecar, stock bars from a hosted Alpaca data relay. Railway runs it as cron; the public dashboard renders the rails from the same functions the bot calls.</p>
        <h2>What we proved before trading</h2>
        <p>We replayed the September 1 option chains. Eight of the twenty three spreads the open gate would have taken were already past their own stop on the quotes they were picked from. With the liquidity floor: five admitted, zero past the stop. 276 tests.</p>
      </div>
    </div>

    <h2>Numbers, straight from the account · {n['as_of']}</h2>
    <div class="kv">
      <div><div class="l">Equity</div><div class="v">{money(n['equity'])}</div></div>
      <div><div class="l">Filled orders in the window</div><div class="v">{n['fills_total']} <span style="font-size:12px; color:var(--muted); font-weight:700;">· {n['fills_options']} options</span></div></div>
      <div><div class="l">Max risk per position</div><div class="v">$3,000</div></div>
    </div>
    <div class="box"><p><b>Disclosure.</b> The harness predates the event (July 2026). Built inside the window: the share scalper and its study, the Railway deployment, the DeepSeek proposer, the dashboard rework, the CLI transport, and the open gate with its cap and liquidity floor. The account was created August 30; nothing else has traded on it.</p></div>
    <div class="foot"><span>github.com/Jhosshua/OptionsAgent · MIT</span><span>optionsagent-production.up.railway.app</span></div>
    """
    return page("One-pager", css, body)


def main():
    SCENES.mkdir(parents=True, exist_ok=True)
    n = live_numbers()
    scenes = [scene01(), scene02(), scene03(), scene04(), scene_scalper(5), scene05(), scene06(), scene07(), scene08(), scene09(n)]
    files = []
    for i, html in enumerate(scenes, 1):
        p = SCENES / f"Scene{i:02d}.dc.html"
        p.write_text(html)
        files.append(p.name)
    # Main.dc.html = the cover (entry artboard for the canvas)
    (SCENES / "Main.dc.html").write_text(scenes[0])
    (SCENES / "OnePager.dc.html").write_text(onepager(n))
    boards = [{"file": "Main.dc.html", "x": 0, "y": 0, "w": 1920, "h": 1080, "title": "Scene 1 · Cover"}]
    for i, f in enumerate(files[1:], 2):
        col, row = (i - 1) % 3, (i - 1) // 3
        boards.append({"file": f, "x": col * 2040, "y": row * 1260, "w": 1920, "h": 1080, "title": f"Scene {i}"})
    boards.append({"file": "OnePager.dc.html", "x": 2040, "y": 3 * 1260, "w": 816, "h": 1056, "title": "One-pager (Letter)", "print": "fixed"})
    canvas = {"artboards": boards,
              "annotations": [{"id": "brief", "x": 0, "y": -220, "w": 900,
                               "text": "Wingspan hackathon video storyboard · each artboard is one scene, 1920x1080, "
                                       "24 fps. The video is rendered frame-by-frame from these exact files "
                                       "(submission/video/render.py). Motion is CSS; the renderer seeks it."}],
              "launch": {"view": "canvas"}}
    (SCENES / "canvas.json").write_text(json.dumps(canvas, indent=1))
    print("scenes:", ["Main.dc.html", *files[1:]], "numbers:", json.dumps(n))


if __name__ == "__main__":
    main()
