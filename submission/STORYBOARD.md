# Wingspan video v3 — storyboard + script (target 1:50–2:05, PM-style)

Audience: hackathon judges (Alpaca product + trading API leads, lablab). They see ~60 videos.
Job of the video: in 2 minutes, make them believe (1) there is a real customer problem,
(2) this agent solves it in a way they can verify, (3) it runs on their stack correctly.

Voice: Microsoft neural (edge-tts), rate +12%, short sentences, contractions, no lists read aloud.
Every scene has motion: text reveals, a slow push on UI shots, the alpaca mascot moving.

| # | Scene (visual) | Motion | Narration (spoken) | ~s |
|---|---|---|---|---|
| 1 | Cover: red panel, W mark, WINGSPAN | W draws itself; title slides up; alpaca walks in from the right and stops | "Meet Wingspan. It's an options agent that mostly says no." | 6 |
| 2 | THE PROBLEM. Big line: "Retail options traders lose on size, not on ideas." Three short chips appear: too big · wrong strike · no exit plan | chips pop in one by one; alpaca looks at each | "Here's the customer problem. Retail options traders don't lose because their ideas are bad. They lose because they size too big, pick the wrong strike, and never plan the exit. Give an A I your account and it makes the same three mistakes, faster." | 16 |
| 3 | THE PRODUCT. Split: left "AI proposes" (a chat bubble: T · bearish · 0.7), right "Code decides" (strike, size, exit, order stamped one by one) | bubble slides in; four stamps land with a bounce | "So Wingspan splits the job. The A I only proposes: which name, which direction, how sure. Code decides everything with a dollar sign on it: the strike, the size, the exit, the order." | 14 |
| 4 | THE RAILS. Five gates as a vertical funnel; a proposal token drops through; one gate turns red and the token stops | token animation; gate glow | "Every idea drops through hard gates. A conviction floor. One position per name. A three thousand dollar cap. A liquidity check that rejects any spread the exit rule would stop out on day one. Most ideas die here, on purpose." | 15 |
| 5 | LIVE UI: dashboard Overview (real screenshot) | slow push-in; a highlight box moves from Today P/L to "AI trade ideas" | "This is the live app. Equity, today's P and L, and every A I idea with the gate that accepted or rejected it. A refusal is a first-class result." | 12 |
| 6 | LIVE UI: Risk rails tab | push-in; highlight on Max per position $3,000 and Broker path | "The risk page is rendered from the same functions the bot runs, so it can't drift from the code." | 8 |
| 7 | ALPACA. CLI terminal card: `alpaca order submit --order-class mleg …` typing out, JSON reply; alpaca mascot nods | typewriter; reply fades in | "Every order goes through Alpaca's official command line, inside the container, journaled with its exit code. If the C L I fails, the trade fails. No silent fallback." | 12 |
| 8 | PROOF. Replay table: 22 → 8 red, then 26 → 5 green, 0 red | bars animate | "Before the first trade we replayed real option chains. Eight of twenty two spreads the naive gate would take were already past their stop. A liquidity floor fixed it. Two hundred seventy six tests back that." | 14 |
| 9 | RESULTS + CTA: account, equity, fills (live numbers), repo + dashboard URLs; alpaca sits down | numbers count up | "Live numbers as of the snapshot. Paper account, one hundred thousand start. Robustness is what a judge can verify in two days. Thanks for watching." | 11 |

Total narration ≈ 108 s + transitions ≈ 1:55.

## Design notes for the reviewer to attack
- Palette: red #C41E2E, ink #18181C, paper #FAF8F5. Arial (available offline). 1920x1080, 24 fps.
- Alpaca mascot: simple flat vector alpaca (body, neck, head, ears, legs), drawn in code, 3-frame walk cycle + idle bob. Appears on scenes 1, 2, 7, 9. Must not read as a logo of Alpaca Inc.
- Transitions: 0.4 s crossfade between scenes. Text reveals: 120 ms stagger, ease-out.
- Audio: each scene's clip = narration + 0.7 s tail; scene length is set from the AUDIO length (the v2 bug was `-shortest`, which clipped the last word).
- No bullet lists on screen longer than 6 words; the narration carries detail.
