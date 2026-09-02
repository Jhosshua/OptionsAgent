(() => {
  const $ = (id) => document.getElementById(id);
  const state = { summary: null, trades: [], positions: [], risk: null, system: null, positionsKnown: null };

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
  const whenET = (value) => (value ? `${etDate(value, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET` : "Never");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
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
  function row(label, value, cls = "") {
    return `<div class="detail-row"><span>${label}</span><strong class="${cls}">${value}</strong></div>`;
  }

  // One sentence about the AI call on the most recent seller cycle. The point
  // of this is that a dead model and a quiet market look identical in the
  // trade list; only the journaled call tells them apart.
  function aiStatus(cycle) {
    if (!cycle || !cycle.cycle_id) return { text: "No run yet", cls: "muted" };
    if (!cycle.ai) return { text: "Last run predates AI logging · check back after the next daily run", cls: "muted" };
    if (!cycle.ai.ok) return { text: `AI call failed, nothing traded (safe) · ${esc(cycle.ai.error) || "no error text"}`, cls: "loss" };
    const tries = (cycle.ai.attempts ?? 1) > 1 ? ` after ${esc(cycle.ai.attempts)} tries` : "";
    return { text: `AI responded in ${esc(cycle.ai.latency_s ?? "—")}s${tries}`, cls: "gain" };
  }

  function setStatusBanner(summary) {
    const unavailable = summary.stale || !summary.paper;
    $("warning").hidden = !unavailable;
    $("warning-title").textContent = !summary.paper ? "Live trading is blocked" : summary.stale ? "Broker snapshot unavailable or stale" : "Dashboard status";
    $("warning-detail").textContent = !summary.paper ? "ALPACA_PAPER must be true. No live orders will be sent." : summary.stale ? `Last successful refresh: ${summary.as_of || "never"}. No values are fabricated.` : "Running in paper mode. No live orders will be sent.";
    const mode = summary.trading_enabled ? "PAPER · ACTIVE" : "PAPER · DISARMED";
    $("mode-pill").innerHTML = `<span class="dot"></span> ${mode}`;
  }
  function renderSummary(data) {
    state.summary = data; setStatusBanner(data);
    paintMoney($("today-pnl"), data.today_pnl_usd);
    $("today-pnl-sub").textContent = data.today_pnl_usd == null ? "Closed today, P/L not journaled"
      : data.stale ? "Broker data stale" : "Realized today, both engines";
    $("account-equity").textContent = data.equity_usd == null ? "—" : plainMoney(data.equity_usd);
    $("open-positions").textContent = data.open_positions ?? "—"; $("open-cap").textContent = "on the book";
    $("open-breakdown").textContent = `${plural(data.open_spreads ?? 0, "spread")} · ${plural(data.open_scalps ?? 0, "scalp")}`;
    $("buying-power").textContent = data.buying_power_usd == null ? "—" : plainMoney(data.buying_power_usd);
    const cycle = data.seller_cycle || {};
    $("seller-proposals").textContent = cycle.proposals ?? "—";
    const status = aiStatus(cycle);
    const opened = cycle.opened == null ? "" : `${cycle.opened} traded · `;
    $("seller-status").textContent = `${opened}${status.text}`;
    $("seller-status").className = `status-text ${status.cls}`;
    renderEquity(data.equity_curve || []);
    renderAiCard(cycle);
  }
  function renderAiCard(cycle) {
    const status = aiStatus(cycle);
    $("ai-badge").textContent = status.cls === "gain" ? "● OK" : status.cls === "loss" ? "● Failed" : "● Unknown";
    $("ai-badge").className = `status-text ${status.cls}`;
    const ai = cycle.ai || {};
    $("ai-rows").innerHTML =
      row("When", cycle.started ? whenET(cycle.started) : "No run yet") +
      row("Model", ai.provider ? `${esc(ai.provider)} · ${esc(ai.model)}` : "—") +
      row("AI call", status.text, status.cls) +
      row("Ideas proposed", cycle.proposals ?? "—") +
      row("Traded", cycle.opened ?? "—", cycle.opened > 0 ? "gain" : "");
    const list = $("ai-rejections"); list.innerHTML = "";
    const rejections = cycle.rejections || [];
    if (!cycle.cycle_id) list.innerHTML = "<li>The credit-spread engine has not run yet.</li>";
    else if (ai.ok === false) list.innerHTML = "<li>The AI call failed, so there were no ideas to judge. Nothing was traded, which is the safe default.</li>";
    else if (cycle.proposals == null) list.innerHTML = "<li>This run happened before the dashboard started logging AI calls, so its result is unknown. The next daily run will show here.</li>";
    else if (cycle.proposals === 0) list.innerHTML = "<li>The AI proposed nothing this run. That is allowed; it is a selective bot.</li>";
    else if (!rejections.length && (cycle.opened ?? 0) > 0) list.innerHTML = "<li>Every idea became a trade.</li>";
    else rejections.forEach((r) => { const li = document.createElement("li"); li.textContent = `${r.reason} (${r.count})`; list.appendChild(li); });
  }
  function renderEquity(points) {
    const line = $("equity-line"); const dots = $("equity-points"); dots.innerHTML = "";
    if (!points.length) { line.setAttribute("d", "M54 110 L492 110"); return; }
    const safePoints = points.filter((point) => Number.isFinite(Number(point.cumulative_pnl_usd))); if (!safePoints.length) { line.setAttribute("d", "M54 110 L492 110"); ["axis-top", "axis-mid", "axis-bottom"].forEach((id) => { $(id).textContent = "$0"; }); return; }
    const values = safePoints.map((point) => Number(point.cumulative_pnl_usd)); const min = Math.min(0, ...values); const max = Math.max(0, ...values); const span = Math.max(1, max - min); const xStep = safePoints.length > 1 ? 438 / (safePoints.length - 1) : 438;
    const coords = safePoints.map((point, index) => [54 + index * xStep, 200 - ((Number(point.cumulative_pnl_usd) - min) / span) * 180]); line.setAttribute("d", coords.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ")); $("axis-top").textContent = plainMoney(max); $("axis-mid").textContent = plainMoney((max + min) / 2); $("axis-bottom").textContent = plainMoney(min); coords.forEach((point, index) => { const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); circle.setAttribute("cx", point[0]); circle.setAttribute("cy", point[1]); circle.setAttribute("r", "3.5"); const title = document.createElementNS("http://www.w3.org/2000/svg", "title"); title.textContent = `${safePoints[index].date}: ${money(values[index])} cumulative`; circle.appendChild(title); dots.appendChild(circle); });
    $("axis-first").textContent = safePoints[0].date ? etDate(`${safePoints[0].date}T12:00:00Z`, { month: "short", day: "numeric" }) : "Start";
  }
  function renderHistory(rows) {
    state.trades = rows || [];
    const typeLabel = (r) => (r.rule ? `${esc(r.strategy)} · ${esc(r.rule)}` : esc(r.strategy));
    const pnlClass = (value) => (value > 0 ? "gain" : value < 0 ? "loss" : "muted");
    const target = $("history-rows"); target.innerHTML = "";
    rows.slice(0, 5).forEach((r) => {
      const el = document.createElement("div"); el.className = "history-row";
      el.innerHTML = `<strong>${esc(r.underlying)}</strong><span class="type">${typeLabel(r)}</span><span>${titleCase(r.side)}</span><span>${r.qty ?? "—"}</span><strong class="${pnlClass(r.pnl_usd)}">${money(r.pnl_usd)}</strong><span class="exit">${etDate(r.closed_ts)}</span>`;
      el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); target.appendChild(el);
    });
    if (!target.children.length) target.innerHTML = `<div class="detail-row muted">No closed trades yet since the 08-28 reset.</div>`;
    const table = $("trades-table"); table.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>TYPE</span><span>SIDE</span><span>QTY</span><span>ENTRY → EXIT</span><span>P/L</span><span>CLOSED</span></div>`;
    rows.forEach((r) => {
      const el = document.createElement("div"); el.className = "wide-row";
      // A credit spread has a width and a credit; a scalp has entry/exit prices.
      const legs = r.width != null || r.credit != null
        ? `${r.width == null ? "—" : `$${Number(r.width).toFixed(2)}`} wide · ${r.credit == null ? "—" : `$${Number(r.credit).toFixed(2)}`} credit`
        : `${price(r.entry_price)} → ${price(r.exit_price)}`;
      const reason = r.reason ? `<span class="muted small">${titleCase(r.reason)}</span>` : "";
      el.innerHTML = `<strong>${esc(r.underlying)}</strong><span>${typeLabel(r)}</span><span>${titleCase(r.side)}</span><span>${r.qty ?? "—"}</span><span class="muted">${legs}</span><strong class="${pnlClass(r.pnl_usd)}">${money(r.pnl_usd)}</strong><span class="muted">${r.closed_ts ? etDate(r.closed_ts, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Unknown"}<br>${reason}</span>`;
      el.setAttribute("role", "row"); el.querySelectorAll("strong,span").forEach((cell) => cell.setAttribute("role", "cell")); table.appendChild(el);
    });
    if (!rows.length) table.innerHTML += `<div class="detail-row muted">No closed trades since the 08-28 reset.</div>`;
  }
  function renderBars(rows) {
    const target = $("daily-bars"); target.innerHTML = ""; const known = rows.filter((r) => Number.isFinite(Number(r.pnl_usd))).slice(-30); const values = known.map((r) => Number(r.pnl_usd)); const max = Math.max(1, ...values.map(Math.abs));
    (known.length ? known : [{ date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }, { date: "", pnl_usd: 0 }]).forEach((r) => { const value = Number(r.pnl_usd); const bar = document.createElement("div"); bar.className = `bar ${value < 0 ? "loss" : value === 0 ? "zero" : ""}`; const height = value === 0 ? 2 : Math.max(8, Math.round(Math.abs(value) / max * 86)); bar.style.height = `${height}px`; bar.style.marginTop = value < 0 ? "110px" : `${110 - height}px`; bar.title = r.date ? `${r.date}: ${money(value)}` : "No known realized P/L"; target.appendChild(bar); });
    const total = values.reduce((a, b) => a + b, 0);
    $("daily-total").textContent = values.length ? `${plural(values.length, "day")} · ${money(total)}` : "No realized closes";
    $("daily-accessible").textContent = known.length ? known.map((r) => `${r.date}: ${money(r.pnl_usd)}`).join("; ") : "No known realized P/L in the selected period.";
  }
  function renderPositions(rows) {
    state.positions = rows || [];
    const target = $("positions-table");
    target.innerHTML = `<div class="wide-head"><span>SYMBOL</span><span>STRATEGY</span><span>QTY</span><span>ENTRY</span><span>MARKET VALUE</span><span>UNREALIZED P/L</span><span>STATUS</span></div>`;
    rows.forEach((r) => {
      const el = document.createElement("div"); el.className = "wide-row";
      const unrealized = r.unrealized_pnl_usd;
      const cls = unrealized > 0 ? "gain" : unrealized < 0 ? "loss" : "muted";
      el.innerHTML = `<strong>${esc(r.display_symbol || r.symbol)}</strong><span>${esc(r.strategy)}</span><span>${r.qty ?? "—"}</span><span>${price(r.entry_price)}</span><span>${r.market_value == null ? "—" : plainMoney(r.market_value)}</span><strong class="${cls}">${money(unrealized)}</strong><span class="gain">● ${r.status}</span>`;
      target.appendChild(el);
    });
    if (!rows.length) target.innerHTML += state.positionsKnown === false
      ? `<div class="detail-row muted">Broker snapshot unavailable — the position list is unknown, not empty.</div>`
      : `<div class="detail-row muted">Nothing open right now. The scalper flattens by 15:50 ET every day, and the seller has no spreads on.</div>`;
  }
  function renderRisk(data) {
    state.risk = data; const rails = data.rails || {}; const eq = data.equity_scalp_rails || {}; const ai = data.proposer || {};
    const windows = (eq.entry_windows || []).map((w) => `${titleCase(w[0])} ${w[1]}-${w[2]} ET`).join(" · ") || "—";
    const profiles = (rails.allowed_profiles || []).map((p) => `<li>${esc(p)}</li>`).join("");
    const floorPct = rails.conviction_floor == null ? "—" : `${Math.round(Number(rails.conviction_floor) * 100)}%`;
    $("risk-list").innerHTML =
      `<article class="card detail-card"><h3>Credit spread seller</h3>` +
      row("Engine", rails.trading_enabled ? "Enabled" : "Disarmed", rails.trading_enabled ? "gain" : "muted") +
      row("Runs", "Once a day, 10:15 ET, weekdays") +
      row("AI proposer", ai.provider ? `${esc(ai.provider)} · ${esc(ai.model)}` : "—") +
      row("Strategy phase", titleCase(data.phase)) +
      row("Minimum conviction", floorPct) +
      row("Max open option legs", rails.max_concurrent_positions ?? "—") +
      row("Mandatory close", `${rails.mandatory_close_dte ?? "—"} days before expiry`) +
      row("Execution mode", "PAPER ONLY", "gain") +
      `<p class="rail-note"><strong>Allowed profiles.</strong> A proposal must land on one of these three shapes or it is rejected before any order. Everything else the AI suggests is logged and dropped.</p><ul class="profile-list">${profiles}</ul>` +
      `</article>` +
      `<article class="card detail-card"><h3>Equity scalper</h3>` +
      row("Engine", eq.enabled ? "Enabled" : "Disarmed", eq.enabled ? "gain" : "muted") +
      row("Runs", "Every minute, 09:45-15:55 ET, weekdays") +
      row("Decides with", "Mined rules, no AI") +
      row("Notional per trade", plainMoney(eq.notional_per_trade_usd)) +
      row("Max trades per day", eq.max_trades_per_day ?? "—") +
      row("Max open at once", eq.max_concurrent ?? "—") +
      row("Stop loss", eq.stop_loss_pct == null ? "—" : `${(Number(eq.stop_loss_pct) * 100).toFixed(2)}% adverse move`) +
      row("Daily loss stop", plainMoney(eq.daily_loss_stop_usd)) +
      row("Time exit", `${eq.time_exit_minutes ?? "—"} min after entry`) +
      row("Mandatory flatten", `${eq.eod_flatten_et ?? "—"} ET`) +
      row("Entry windows", windows) +
      row("Execution mode", "PAPER ONLY", "gain") +
      `</article>`;
  }
  function renderSystem(data) {
    state.system = data;
    const eq = data.equity_scalp || {};
    const ai = data.proposer || {}; const last = ai.last || {}; const cycle = ai.cycle || {};
    const status = aiStatus(cycle);
    const stamp = (value, opts) => (value ? `${etDate(value, opts)} ET` : "Never");
    const scalpState = !eq.enabled ? `<strong class="muted">Disarmed</strong>`
      : eq.halted ? `<strong class="loss">Halted · ${esc(eq.halt_reason) || "reason not logged"}</strong>`
      : eq.has_state ? `<strong class="gain">Running</strong>`
      : `<strong class="loss">No state written for ${esc(eq.date)}</strong>`;
    $("system-detail").innerHTML =
      `<article class="card detail-card"><h3>Runtime</h3>` +
      row("Trading gate", data.trading_enabled ? "Enabled" : "Disarmed", data.trading_enabled ? "gain" : "muted") +
      row("Broker mode", data.paper_only ? "Paper" : "Blocked", "gain") +
      row("Strategy phase", titleCase(data.phase)) +
      row("Options data provider", esc(data.provider)) +
      row("Stock data source", esc(data.stock_data_source) || "—") +
      row("Alerts", esc(data.alert_transport) || "—") +
      row("Broker snapshot", stamp(data.as_of, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })) +
      row("Refresh failures", data.consecutive_failures, data.consecutive_failures > 0 ? "loss" : "") +
      `</article>` +
      `<article class="card detail-card"><h3>AI proposer</h3>` +
      row("Provider", esc(ai.provider) || "—") +
      row("Model", esc(ai.model) || "—") +
      row("Last seller cycle", stamp(data.last_cycle, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" })) +
      row("Last call", status.text, status.cls) +
      (last.error ? row("Error", esc(last.error), "loss") : "") +
      row("Proposals → opened", cycle.proposals == null ? "—" : `${cycle.proposals} → ${cycle.opened ?? 0}`) +
      `</article>` +
      `<article class="card detail-card"><h3>Equity scalper — today (${esc(eq.date) || "—"})</h3><div class="detail-row"><span>Status</span>${scalpState}</div>` +
      row("Trades taken", `${eq.trades_today ?? "—"} of ${eq.max_trades_per_day ?? "—"}`) +
      row("Rules fired", (eq.rules_taken_day || []).map(titleCase).join(" · ") || "None") +
      row("Realized today (scalper only)", money(eq.realized_today_usd), eq.realized_today_usd > 0 ? "gain" : eq.realized_today_usd < 0 ? "loss" : "muted") +
      row("Daily loss stop", plainMoney(eq.daily_loss_stop_usd)) +
      row("Open scalps", eq.open_scalps ?? 0) +
      `</article>`;
  }
  function setView(view) { document.querySelectorAll("[data-view-panel]").forEach((el) => { el.hidden = el.dataset.viewPanel !== view; }); document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view)); window.scrollTo({ top: 0 }); }
  async function api(path) { const response = await fetch(path, { cache: "no-store" }); if (!response.ok) throw new Error("API " + response.status); return response.json(); }
  // Each section loads on its own: one failing endpoint must not blank the
  // whole page (it used to, via Promise.all).
  async function load() {
    const sections = [
      ["summary", "/api/summary", (d) => renderSummary(d)],
      ["trades", "/api/trades", (d) => { renderHistory(d.trades || []); renderBars(d.daily_pnl || []); }],
      ["positions", "/api/positions", (d) => { state.positionsKnown = d.positions_known; renderPositions(d.positions || []); }],
      ["risk", "/api/risk", (d) => renderRisk(d)],
      ["system", "/api/system", (d) => renderSystem(d)],
    ];
    const results = await Promise.allSettled(sections.map(([, path]) => api(path)));
    const failed = [];
    results.forEach((result, index) => {
      const [name, , render] = sections[index];
      if (result.status === "fulfilled") { try { render(result.value); } catch (error) { failed.push(name); } }
      else failed.push(name);
    });
    if (failed.length) {
      $("warning").hidden = false;
      $("warning-title").textContent = failed.length === sections.length ? "Dashboard data unavailable" : "Some sections could not load";
      $("warning-detail").textContent = `${failed.join(", ")} — the server is alive but those reads failed. Retry, or check the dashboard log.`;
    }
    $("refreshed").textContent = `Updated ${new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date())} ET`;
  }
  $("retry").addEventListener("click", load);
  document.addEventListener("click", (event) => { const view = event.target.closest("[data-view], [data-view-link]"); if (view) setView(view.dataset.view || view.dataset.viewLink); });
  dateLabel(); setInterval(dateLabel, 30000); load(); setInterval(load, 60000);
})();
