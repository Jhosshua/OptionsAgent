(() => {
  const TOKEN_KEY = "optionsagent.dashboard.token";
  const $ = (id) => document.getElementById(id);
  const state = { summary: null, trades: [], research: null, positions: [], risk: null, system: null };

  function money(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    const n = Number(value);
    return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  function plainMoney(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  function etDate(value, options = { year: "numeric", month: "numeric", day: "numeric" }) {
    if (!value) return "Unknown";
    const date = new Date(value); if (Number.isNaN(date.getTime())) return "Unknown";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", ...options }).format(date);
  }
  function dateLabel() {
    const now = new Date();
    const dateParts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "long", month: "long", day: "numeric", year: "numeric" }).formatToParts(now);
    $("page-date").textContent = `${dateParts.find((p) => p.type === "weekday").value}, ${dateParts.find((p) => p.type === "month").value} ${dateParts.find((p) => p.type === "day").value}`;
    $("page-year").textContent = dateParts.find((p) => p.type === "year").value;
    $("clock").textContent = `◷ ${new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }).format(now)} ET`;
  }
  function paintMoney(el, value) {
    el.textContent = money(value); el.classList.remove("gain", "loss");
    if (Number(value) > 0) el.classList.add("gain"); else if (Number(value) < 0) el.classList.add("loss");
  }
  function setStatusBanner(summary) {
    const unavailable = summary.stale || !summary.paper;
    $("warning").hidden = !unavailable;
    $("warning-title").textContent = !summary.paper ? "Live trading is blocked" : summary.stale ? "Broker snapshot unavailable or stale" : "Dashboard status";
    $("warning-detail").textContent = !summary.paper ? "ALPACA_PAPER must be true. No live orders will be sent." : summary.stale ? `Last successful refresh: ${summary.as_of || "never"}. No values are fabricated.` : "Running in paper mode. No live orders will be sent.";
    const mode = summary.trading_enabled ? "PAPER · ACTIVE" : "PAPER · DISARMED";
    $("mode-pill").innerHTML = `<span class="dot"></span> ${mode}`;
    $("profile-status").textContent = summary.stale ? "● Unavailable" : "● Active";
    $("profile-status").className = `status-text ${summary.stale ? "muted" : ""}`;
  }
  function renderSummary(data) {
    state.summary = data; setStatusBanner(data);
    paintMoney($("today-pnl"), data.today_pnl_usd); $("today-pnl-sub").textContent = data.stale ? "Broker data stale" : "Realized, market open";
    $("open-spreads").textContent = data.open_spreads ?? "—"; $("open-cap").textContent = data.open_positions_cap == null ? "" : `of ${data.open_positions_cap}`;
    $("buying-power").textContent = data.buying_power_usd == null ? "—" : plainMoney(data.buying_power_usd);
    $("winner-rules").textContent = data.winner_rules ?? "—";
    renderEquity(data.equity_curve || []);
  }
  function renderEquity(points) {
    const line = $("equity-line"); const dots = $("equity-points"); dots.innerHTML = "";
    if (!points.length) { line.setAttribute("d", "M54 110 L492 110"); return; }
    const safePoints = points.filter((point) => Number.isFinite(Number(point.pnl_usd))); if (!safePoints.length) { line.setAttribute("d", "M54 110 L492 110"); ["axis-top", "axis-mid", "axis-bottom"].forEach((id) => { $(id).textContent = "$0"; }); return; }
    const values = safePoints.map((point) => Number(point.pnl_usd)); const min = Math.min(0, ...values); const max = Math.max(0, ...values); const span = Math.max(1, max - min); const xStep = safePoints.length > 1 ? 438 / (safePoints.length - 1) : 438;
    const coords = safePoints.map((point, index) => [54 + index * xStep, 200 - ((Number(point.pnl_usd) - min) / span) * 180]); line.setAttribute("d", coords.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ")); $("axis-top").textContent = plainMoney(max); $("axis-mid").textContent = plainMoney((max + min) / 2); $("axis-bottom").textContent = plainMoney(min); coords.forEach((point) => { const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); circle.setAttribute("cx", point[0]); circle.setAttribute("cy", point[1]); circle.setAttribute("r", "3.5"); dots.appendChild(circle); });
  }
  function renderHistory(rows) {
    state.trades = rows || [];
    const target = $("history-rows"); target.innerHTML = "";
    rows.filter((r) => r.strategy === "Credit Spread").slice(0, 5).forEach((row) => {
      const el = document.createElement("div"); el.className = "history-row";
      el.innerHTML = `<strong>${row.underlying}</strong><span class="type">${row.strategy}</span><span>${row.width == null ? "—" : `$${Number(row.width).toFixed(2)}`}</span><span>${row.credit == null ? "—" : `$${Number(row.credit).toFixed(2)}`}</span><strong class="${row.pnl_usd > 0 ? "gain" : row.pnl_usd < 0 ? "loss" : "muted"}">${money(row.pnl_usd)}</strong><span class="exit">${etDate(row.closed_ts)}</span>`;
      el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); target.appendChild(el);
    });
    if (!target.children.length) target.innerHTML = `<div class="detail-row muted">No closed credit spreads on this volume.</div>`;
    const table = $("trades-table"); table.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>TYPE</span><span>WIDTH</span><span>CREDIT</span><span>P/L</span><span>EXIT</span></div>`;
    rows.forEach((row) => { const el = document.createElement("div"); el.className = "wide-row"; el.innerHTML = `<strong>${row.underlying}</strong><span>${row.strategy}</span><span>${row.width == null ? "—" : `$${Number(row.width).toFixed(2)}`}</span><span>${row.credit == null ? "—" : `$${Number(row.credit).toFixed(2)}`}</span><strong class="${row.pnl_usd > 0 ? "gain" : row.pnl_usd < 0 ? "loss" : "muted"}">${money(row.pnl_usd)}</strong><span class="muted">${row.closed_ts ? etDate(row.closed_ts, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Unknown"}</span>`; el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); table.appendChild(el); });
    if (!rows.length) table.innerHTML += `<div class="detail-row muted">No closed trades on this volume.</div>`;
  }
  function renderBars(rows) {
    const target = $("daily-bars"); target.innerHTML = ""; const known = rows.filter((r) => Number.isFinite(Number(r.pnl_usd))).slice(-30); const values = known.map((r) => Number(r.pnl_usd)); const max = Math.max(1, ...values.map(Math.abs));
    (known.length ? known : [{ date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }]).forEach((row) => { const value = Number(row.pnl_usd); const bar = document.createElement("div"); bar.className = `bar ${value < 0 ? "loss" : value === 0 ? "zero" : ""}`; const height = value === 0 ? 2 : Math.max(8, Math.round(Math.abs(value) / max * 86)); bar.style.height = `${height}px`; bar.style.marginTop = value < 0 ? "110px" : `${110 - height}px`; bar.title = row.date ? `${row.date}: ${money(value)}` : "No known realized P/L"; target.appendChild(bar); });
    $("daily-total").textContent = values.length ? `${values.length} days` : "No realized closes";
    $("daily-accessible").textContent = known.length ? known.map((row) => `${row.date}: ${money(row.pnl_usd)}`).join("; ") : "No known realized P/L in the selected period.";
  }
  function renderPositions(rows) {
    state.positions = rows || []; const target = $("positions-table"); target.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>STRATEGY</span><span>QTY</span><span>MARKET VALUE</span><span>COST BASIS</span><span>STATUS</span></div>`;
    rows.forEach((row) => { const el = document.createElement("div"); el.className = "wide-row"; el.innerHTML = `<strong>${row.display_symbol || row.symbol}</strong><span>${row.strategy}</span><span>${row.qty ?? "—"}</span><span>${row.market_value == null ? "—" : plainMoney(row.market_value)}</span><span>${row.cost_basis == null ? "—" : plainMoney(row.cost_basis)}</span><span class="gain">● ${row.status}</span>`; target.appendChild(el); });
    if (!rows.length) target.innerHTML += `<div class="detail-row muted">No broker positions reported.</div>`;
  }
  function renderResearch(data) {
    state.research = data; $("research-days").textContent = `${data.entry_days} entry days`; $("research-records").textContent = `${data.records} archived records`; paintMoney($("research-realized"), data.realized_pnl); paintMoney($("research-profile"), data.profile_pnl);
    const realizedClass = Number.isFinite(Number(data.realized_pnl)) ? (data.realized_pnl < 0 ? "loss" : "gain") : "muted"; const profileClass = Number.isFinite(Number(data.profile_pnl)) ? (data.profile_pnl < 0 ? "loss" : "gain") : "muted";
    $("research-detail").innerHTML = `<article class="card detail-card"><h3>Replay summary</h3><div class="detail-row"><span>Entry days</span><strong>${data.entry_days}</strong></div><div class="detail-row"><span>Archived records</span><strong>${data.records}</strong></div><div class="detail-row"><span>Realized P/L</span><strong class="${realizedClass}">${money(data.realized_pnl)}</strong></div><div class="detail-row"><span>Filtered profile replay</span><strong class="${profileClass}">${money(data.profile_pnl)}</strong></div><div class="detail-row"><span>Unknown P/L closes</span><strong>${data.unknown_pnl_closes}</strong></div></article><article class="card detail-card"><h3>Winner rules</h3>${(data.rules || []).map((rule) => `<div class="detail-row"><span>${rule}</span><strong class="gain">Active</strong></div>`).join("")}</article>`;
  }
  function renderRisk(data) {
    state.risk = data; const rails = data.rails || {}; $("risk-list").innerHTML = `<article class="card detail-card"><h3>Deterministic hard rails</h3><div class="detail-row"><span>Rollout phase</span><strong>${data.phase}</strong></div><div class="detail-row"><span>Conviction floor</span><strong>${rails.conviction_floor}</strong></div><div class="detail-row"><span>Maximum concurrent positions</span><strong>${rails.max_concurrent_positions}</strong></div><div class="detail-row"><span>Mandatory close</span><strong>${rails.mandatory_close_dte} DTE</strong></div><div class="detail-row"><span>Execution mode</span><strong class="gain">PAPER ONLY</strong></div></article>`;
  }
  function renderSystem(data) { state.system = data; $("system-detail").innerHTML = `<article class="card detail-card"><h3>Runtime</h3><div class="detail-row"><span>Trading gate</span><strong class="${data.trading_enabled ? "gain" : "muted"}">${data.trading_enabled ? "Enabled" : "Disarmed"}</strong></div><div class="detail-row"><span>Broker mode</span><strong class="gain">${data.paper_only ? "Paper" : "Blocked"}</strong></div><div class="detail-row"><span>Market-data provider</span><strong>${data.provider}</strong></div><div class="detail-row"><span>Snapshot</span><strong>${data.as_of ? `${etDate(data.as_of, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })} ET` : "Never"}</strong></div><div class="detail-row"><span>Refresh failures</span><strong>${data.consecutive_failures}</strong></div></article>`; }
  function setView(view) { document.querySelectorAll("[data-view-panel]").forEach((el) => { el.hidden = el.dataset.viewPanel !== view; }); document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view)); }
  async function api(path) { const token = sessionStorage.getItem(TOKEN_KEY); const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }); if (response.status === 401) { sessionStorage.removeItem(TOKEN_KEY); showAuth("Token rejected or expired. Enter it again."); throw new Error("unauthorized"); } if (!response.ok) throw new Error(`API ${response.status}`); return response.json(); }
  function showAuth(message = "") { $("app").hidden = true; $("auth-screen").hidden = false; $("auth-error").textContent = message; $("token-input").value = ""; requestAnimationFrame(() => $("token-input").focus()); }
  async function load() { try { const [summary, trades, positions, research, risk, system] = await Promise.all([api("/api/summary"), api("/api/trades"), api("/api/positions"), api("/api/research"), api("/api/risk"), api("/api/system")]); renderSummary(summary); renderHistory(trades.trades); renderBars(trades.daily_pnl || []); renderPositions(positions.positions); renderResearch(research); renderRisk(risk); renderSystem(system); $("app").hidden = false; $("auth-screen").hidden = true; } catch (error) { if (error.message !== "unauthorized") { $("warning").hidden = false; $("warning-title").textContent = "Dashboard data unavailable"; $("warning-detail").textContent = "The server is alive but its cached data could not be read."; } } }
  $("auth-form").addEventListener("submit", async (event) => { event.preventDefault(); const token = $("token-input").value; if (token.length < 32) { $("auth-error").textContent = "Token must be at least 32 characters."; return; } sessionStorage.setItem(TOKEN_KEY, token); await load(); });
  $("clear-token").addEventListener("click", () => { sessionStorage.removeItem(TOKEN_KEY); showAuth("Token cleared."); }); $("retry").addEventListener("click", load);
  document.addEventListener("click", (event) => { const view = event.target.closest("[data-view], [data-view-link]"); if (view) setView(view.dataset.view || view.dataset.viewLink); });
  dateLabel(); setInterval(dateLabel, 30000); const existing = sessionStorage.getItem(TOKEN_KEY); if (existing) load();
})();
