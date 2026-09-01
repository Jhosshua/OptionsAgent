(() => {
  const $ = (id) => document.getElementById(id);
  const state = { summary: null, trades: [], research: null, positions: [], risk: null, system: null };

  function money(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    const n = Number(value);
    // Scalp P/L lands in single dollars; rounding it to whole dollars throws
    // away the number. Cents below $1,000, whole dollars above.
    const digits = Math.abs(n) < 1000 ? 2 : 0;
    return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  }
  function plainMoney(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    const n = Number(value);
    return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  function price(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return `$${Number(value).toFixed(2)}`;
  }
  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function titleCase(value) {
    if (!value) return "—";
    return esc(String(value).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
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
    paintMoney($("today-pnl"), data.today_pnl_usd);
    $("today-pnl-sub").textContent = data.today_pnl_usd == null ? "Closed today, P/L not journaled"
      : data.stale ? "Broker data stale" : "Realized today, both engines";
    $("account-equity").textContent = data.equity_usd == null ? "—" : plainMoney(data.equity_usd);
    $("open-positions").textContent = data.open_positions ?? "—"; $("open-cap").textContent = "on the book";
    $("open-breakdown").textContent = `${data.open_spreads ?? 0} spread${data.open_spreads === 1 ? "" : "s"} · ${data.open_scalps ?? 0} scalp${data.open_scalps === 1 ? "" : "s"}`;
    $("buying-power").textContent = data.buying_power_usd == null ? "—" : plainMoney(data.buying_power_usd);
    $("winner-rules").textContent = data.winner_rules ?? "—";
    renderEquity(data.equity_curve || []);
  }
  function renderEquity(points) {
    const line = $("equity-line"); const dots = $("equity-points"); dots.innerHTML = "";
    if (!points.length) { line.setAttribute("d", "M54 110 L492 110"); return; }
    const safePoints = points.filter((point) => Number.isFinite(Number(point.cumulative_pnl_usd))); if (!safePoints.length) { line.setAttribute("d", "M54 110 L492 110"); ["axis-top", "axis-mid", "axis-bottom"].forEach((id) => { $(id).textContent = "$0"; }); return; }
    const values = safePoints.map((point) => Number(point.cumulative_pnl_usd)); const min = Math.min(0, ...values); const max = Math.max(0, ...values); const span = Math.max(1, max - min); const xStep = safePoints.length > 1 ? 438 / (safePoints.length - 1) : 438;
    const coords = safePoints.map((point, index) => [54 + index * xStep, 200 - ((Number(point.cumulative_pnl_usd) - min) / span) * 180]); line.setAttribute("d", coords.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ")); $("axis-top").textContent = plainMoney(max); $("axis-mid").textContent = plainMoney((max + min) / 2); $("axis-bottom").textContent = plainMoney(min); coords.forEach((point) => { const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); circle.setAttribute("cx", point[0]); circle.setAttribute("cy", point[1]); circle.setAttribute("r", "3.5"); dots.appendChild(circle); });
  }
  function renderHistory(rows) {
    state.trades = rows || [];
    const typeLabel = (row) => (row.rule ? `${esc(row.strategy)} · ${esc(row.rule)}` : esc(row.strategy));
    const pnlClass = (value) => (value > 0 ? "gain" : value < 0 ? "loss" : "muted");
    const target = $("history-rows"); target.innerHTML = "";
    rows.slice(0, 5).forEach((row) => {
      const el = document.createElement("div"); el.className = "history-row";
      el.innerHTML = `<strong>${esc(row.underlying)}</strong><span class="type">${typeLabel(row)}</span><span>${titleCase(row.side)}</span><span>${row.qty ?? "—"}</span><strong class="${pnlClass(row.pnl_usd)}">${money(row.pnl_usd)}</strong><span class="exit">${etDate(row.closed_ts)}</span>`;
      el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); target.appendChild(el);
    });
    if (!target.children.length) target.innerHTML = `<div class="detail-row muted">No closed trades yet on this volume.</div>`;
    const table = $("trades-table"); table.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>TYPE</span><span>SIDE</span><span>QTY</span><span>ENTRY → EXIT</span><span>P/L</span><span>CLOSED</span></div>`;
    rows.forEach((row) => {
      const el = document.createElement("div"); el.className = "wide-row";
      // A credit spread has a width and a credit; a scalp has entry/exit prices.
      const legs = row.width != null || row.credit != null
        ? `${row.width == null ? "—" : `$${Number(row.width).toFixed(2)}`} wide · ${row.credit == null ? "—" : `$${Number(row.credit).toFixed(2)}`} credit`
        : `${price(row.entry_price)} → ${price(row.exit_price)}`;
      el.innerHTML = `<strong>${esc(row.underlying)}</strong><span>${typeLabel(row)}</span><span>${titleCase(row.side)}</span><span>${row.qty ?? "—"}</span><span class="muted">${legs}</span><strong class="${pnlClass(row.pnl_usd)}">${money(row.pnl_usd)}</strong><span class="muted">${row.closed_ts ? etDate(row.closed_ts, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Unknown"}</span>`;
      el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); table.appendChild(el);
    });
    if (!rows.length) table.innerHTML += `<div class="detail-row muted">No closed trades on this volume.</div>`;
  }
  function renderBars(rows) {
    const target = $("daily-bars"); target.innerHTML = ""; const known = rows.filter((r) => Number.isFinite(Number(r.pnl_usd))).slice(-30); const values = known.map((r) => Number(r.pnl_usd)); const max = Math.max(1, ...values.map(Math.abs));
    (known.length ? known : [{ date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }]).forEach((row) => { const value = Number(row.pnl_usd); const bar = document.createElement("div"); bar.className = `bar ${value < 0 ? "loss" : value === 0 ? "zero" : ""}`; const height = value === 0 ? 2 : Math.max(8, Math.round(Math.abs(value) / max * 86)); bar.style.height = `${height}px`; bar.style.marginTop = value < 0 ? "110px" : `${110 - height}px`; bar.title = row.date ? `${row.date}: ${money(value)}` : "No known realized P/L"; target.appendChild(bar); });
    $("daily-total").textContent = values.length ? `${values.length} days` : "No realized closes";
    $("daily-accessible").textContent = known.length ? known.map((row) => `${row.date}: ${money(row.pnl_usd)}`).join("; ") : "No known realized P/L in the selected period.";
  }
  function renderPositions(rows) {
    state.positions = rows || [];
    const target = $("positions-table");
    target.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>STRATEGY</span><span>QTY</span><span>ENTRY</span><span>MARKET VALUE</span><span>UNREALIZED P/L</span><span>STATUS</span></div>`;
    rows.forEach((row) => {
      const el = document.createElement("div"); el.className = "wide-row";
      const unrealized = row.unrealized_pnl_usd;
      const cls = unrealized > 0 ? "gain" : unrealized < 0 ? "loss" : "muted";
      el.innerHTML = `<strong>${esc(row.display_symbol || row.symbol)}</strong><span>${esc(row.strategy)}</span><span>${row.qty ?? "—"}</span><span>${price(row.entry_price)}</span><span>${row.market_value == null ? "—" : plainMoney(row.market_value)}</span><strong class="${cls}">${money(unrealized)}</strong><span class="gain">● ${row.status}</span>`;
      target.appendChild(el);
    });
    if (!rows.length) target.innerHTML += state.positionsKnown === false
      ? `<div class="detail-row muted">Broker snapshot unavailable — the position list is unknown, not empty.</div>`
      : `<div class="detail-row muted">No broker positions reported.</div>`;
  }
  function renderResearch(data) {
    state.research = data; $("research-days").textContent = `${data.entry_days} entry days`; $("research-records").textContent = `${data.records} archived records`; paintMoney($("research-realized"), data.realized_pnl); paintMoney($("research-profile"), data.profile_pnl);
    const realizedClass = Number.isFinite(Number(data.realized_pnl)) ? (data.realized_pnl < 0 ? "loss" : "gain") : "muted"; const profileClass = Number.isFinite(Number(data.profile_pnl)) ? (data.profile_pnl < 0 ? "loss" : "gain") : "muted";
    $("research-detail").innerHTML = `<article class="card detail-card"><h3>Replay summary</h3><div class="detail-row"><span>Entry days</span><strong>${data.entry_days}</strong></div><div class="detail-row"><span>Archived records</span><strong>${data.records}</strong></div><div class="detail-row"><span>Realized P/L</span><strong class="${realizedClass}">${money(data.realized_pnl)}</strong></div><div class="detail-row"><span>Filtered profile replay</span><strong class="${profileClass}">${money(data.profile_pnl)}</strong></div><div class="detail-row"><span>Unknown P/L closes</span><strong>${data.unknown_pnl_closes}</strong></div></article><article class="card detail-card"><h3>Winner rules</h3>${(data.rules || []).map((rule) => `<div class="detail-row"><span>${esc(rule)}</span><strong class="gain">Active</strong></div>`).join("")}</article>`;
  }
  function renderRisk(data) {
    state.risk = data; const rails = data.rails || {}; const eq = data.equity_scalp_rails || {};
    const windows = (eq.entry_windows || []).map((w) => `${titleCase(w[0])} ${w[1]}-${w[2]} ET`).join(" · ") || "—";
    $("risk-list").innerHTML = `<article class="card detail-card"><h3>Credit spread seller — deterministic hard rails</h3><div class="detail-row"><span>Rollout phase</span><strong>${esc(data.phase)}</strong></div><div class="detail-row"><span>Conviction floor</span><strong>${rails.conviction_floor}</strong></div><div class="detail-row"><span>Maximum concurrent positions</span><strong>${rails.max_concurrent_positions}</strong></div><div class="detail-row"><span>Mandatory close</span><strong>${rails.mandatory_close_dte} DTE</strong></div><div class="detail-row"><span>Execution mode</span><strong class="gain">PAPER ONLY</strong></div></article>` +
      `<article class="card detail-card"><h3>Equity scalper — deterministic hard rails</h3><div class="detail-row"><span>Engine</span><strong class="${eq.enabled ? "gain" : "muted"}">${eq.enabled ? "Enabled" : "Disarmed"}</strong></div><div class="detail-row"><span>Notional per trade</span><strong>${plainMoney(eq.notional_per_trade_usd)}</strong></div><div class="detail-row"><span>Max trades per day</span><strong>${eq.max_trades_per_day ?? "—"}</strong></div><div class="detail-row"><span>Max concurrent</span><strong>${eq.max_concurrent ?? "—"}</strong></div><div class="detail-row"><span>Stop loss</span><strong>${eq.stop_loss_pct == null ? "—" : `${(Number(eq.stop_loss_pct) * 100).toFixed(2)}%`}</strong></div><div class="detail-row"><span>Daily loss stop</span><strong>${plainMoney(eq.daily_loss_stop_usd)}</strong></div><div class="detail-row"><span>Time exit</span><strong>${eq.time_exit_minutes ?? "—"} min</strong></div><div class="detail-row"><span>Mandatory flatten</span><strong>${eq.eod_flatten_et ?? "—"} ET</strong></div><div class="detail-row"><span>Entry windows</span><strong>${windows}</strong></div></article>`;
  }
  function renderSystem(data) {
    state.system = data;
    const eq = data.equity_scalp || {};
    const stamp = (value, opts) => (value ? `${etDate(value, opts)} ET` : "Never");
    const scalpState = !eq.enabled ? `<strong class="muted">Disarmed</strong>`
      : eq.halted ? `<strong class="loss">Halted · ${esc(eq.halt_reason) || "reason not logged"}</strong>`
      : eq.has_state ? `<strong class="gain">Running</strong>`
      : `<strong class="loss">No state written for ${esc(eq.date)}</strong>`;
    $("system-detail").innerHTML = `<article class="card detail-card"><h3>Runtime</h3><div class="detail-row"><span>Trading gate</span><strong class="${data.trading_enabled ? "gain" : "muted"}">${data.trading_enabled ? "Enabled" : "Disarmed"}</strong></div><div class="detail-row"><span>Broker mode</span><strong class="gain">${data.paper_only ? "Paper" : "Blocked"}</strong></div><div class="detail-row"><span>Rollout phase</span><strong>${esc(data.phase)}</strong></div><div class="detail-row"><span>Options data provider</span><strong>${esc(data.provider)}</strong></div><div class="detail-row"><span>Stock data source</span><strong>${esc(data.stock_data_source) || "—"}</strong></div><div class="detail-row"><span>Last seller cycle</span><strong>${stamp(data.last_cycle, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" })}</strong></div><div class="detail-row"><span>Broker snapshot</span><strong>${stamp(data.as_of, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}</strong></div><div class="detail-row"><span>Refresh failures</span><strong>${data.consecutive_failures}</strong></div></article>` +
      `<article class="card detail-card"><h3>Equity scalper — today (${esc(eq.date) || "—"})</h3><div class="detail-row"><span>Status</span>${scalpState}</div><div class="detail-row"><span>Trades taken</span><strong>${eq.trades_today ?? "—"} of ${eq.max_trades_per_day ?? "—"}</strong></div><div class="detail-row"><span>Rules fired</span><strong>${(eq.rules_taken_day || []).map(titleCase).join(" · ") || "None"}</strong></div><div class="detail-row"><span>Realized today (scalper only)</span><strong class="${eq.realized_today_usd > 0 ? "gain" : eq.realized_today_usd < 0 ? "loss" : "muted"}">${money(eq.realized_today_usd)}</strong></div><div class="detail-row"><span>Daily loss stop</span><strong>${plainMoney(eq.daily_loss_stop_usd)}</strong></div><div class="detail-row"><span>Open scalps</span><strong>${eq.open_scalps ?? 0}</strong></div></article>`;
  }
  function setView(view) { document.querySelectorAll("[data-view-panel]").forEach((el) => { el.hidden = el.dataset.viewPanel !== view; }); document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view)); window.scrollTo({ top: 0 }); }
  async function api(path) { const response = await fetch(path, { cache: "no-store" }); if (!response.ok) throw new Error("API " + response.status); return response.json(); }
  async function load() { try { const [summary, trades, positions, research, risk, system] = await Promise.all([api("/api/summary"), api("/api/trades"), api("/api/positions"), api("/api/research"), api("/api/risk"), api("/api/system")]); renderSummary(summary); renderHistory(trades.trades); renderBars(trades.daily_pnl || []); state.positionsKnown = positions.positions_known; renderPositions(positions.positions); renderResearch(research); renderRisk(risk); renderSystem(system); } catch (error) { $("warning").hidden = false; $("warning-title").textContent = "Dashboard data unavailable"; $("warning-detail").textContent = "The server is alive but its cached data could not be read."; } }
  $("retry").addEventListener("click", load);
  document.addEventListener("click", (event) => { const view = event.target.closest("[data-view], [data-view-link]"); if (view) setView(view.dataset.view || view.dataset.viewLink); });
  dateLabel(); setInterval(dateLabel, 30000); load();
})();
