# Dashboard brand: Wingspan

Chosen 2026-09-01. The dashboard's wordmark is **Wingspan**; the system is still
called OptionsAgent everywhere else (repo, Railway service, Discord channel,
footer reads "Wingspan · OptionsAgent v1.1.0").

The mark is a W drawn as two option-spread payoff diagrams (flat feet = the
plateau where a credit spread keeps its full premium; an iron condor is named
after a bird, and a spread's strike width is its "wings"). It is inline SVG in
`dashboard/index.html`: 24px in the sidebar, 14px in the footer, and a
data-URI favicon in `<head>` (the server only serves an allowlist of static
files, so no favicon route was added). Colors are the existing tokens
(`--accent` red, white stroke).

The `.dc.html` files and `canvas.json` here are the working files for the
design canvas (Claude Design preview, artifact "Wingspan Brand"). Two unchosen
directions, Thetafox and Ratchet, sit on the canvas's second page. To change
the brand, edit these files and re-seed the canvas; the dashboard markup is
edited by hand.
