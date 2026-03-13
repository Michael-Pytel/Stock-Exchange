/* ═══════════════════════════════════════════════════════════════
   robot_page.js  —  PPO Robot page
   ═══════════════════════════════════════════════════════════════ */

/* ── State ─────────────────────────────────────────────────────── */
let currentProfile = "aggressive";
let equityChart    = null;

/* ── API call ──────────────────────────────────────────────────── */
async function robotApi(mode) {
  const resp = await fetch("/api/robot/", {
    method:  "POST",
    headers: {
      "Content-Type":  "application/json",
      "X-CSRFToken":   CSRF,
    },
    body: JSON.stringify({
      ticker:       SYMBOL,
      risk_profile: currentProfile,
      mode,
    }),
  });
  return resp.json();
}

/* ── Signal ────────────────────────────────────────────────────── */
async function loadSignal() {
  const loading = document.getElementById("signal-loading");
  const result  = document.getElementById("signal-result");
  const errEl   = document.getElementById("signal-error");
  const badge   = document.getElementById("signal-badge");
  const profTag = document.getElementById("signal-profile-tag");

  loading.style.display = "flex";
  result.style.display  = "none";
  errEl.style.display   = "none";

  try {
    const data = await robotApi("signal");

    if (data.error) throw new Error(data.error);

    const action = data.action; // "Buy" | "Hold" | "Sell"
    badge.textContent = action.toUpperCase();
    badge.className   = "signal-badge " + action.toLowerCase();
    profTag.textContent = currentProfile + " model";

    result.style.display  = "flex";
  } catch (e) {
    errEl.textContent     = e.message || "Could not load signal.";
    errEl.style.display   = "block";
  } finally {
    loading.style.display = "none";
  }
}

/* ── Backtest + chart ──────────────────────────────────────────── */
async function loadBacktest() {
  const chartLoading = document.getElementById("chart-loading");
  chartLoading.classList.add("visible");

  // Reset metrics
  ["m-return", "m-bah", "m-sharpe", "m-dd", "m-wr"].forEach(id => {
    document.getElementById(id).querySelector(".robot-metric-value").textContent = "—";
    document.getElementById(id).querySelector(".robot-metric-value").className   = "robot-metric-value";
  });

  try {
    const data = await robotApi("backtest");

    if (data.error) throw new Error(data.error);

    renderEquityChart(data.dates, data.equity_curve, data.bah_curve);
    renderMetrics(data.metrics);
    _cacheBacktestLog(data.trade_log || []);

  } catch (e) {
    console.error("Backtest failed:", e.message);
    showChartError(e.message);
  } finally {
    chartLoading.classList.remove("visible");
  }
}

/* ── Chart renderer ────────────────────────────────────────────── */
function renderEquityChart(dates, agentVals, bahVals) {
  const canvas = document.getElementById("equityChart");
  const ctx    = canvas.getContext("2d");

  if (equityChart) equityChart.destroy();

  const agentFinal = agentVals[agentVals.length - 1] || 0;
  const bahFinal   = bahVals[bahVals.length - 1]     || 0;
  const agentColor = agentFinal >= bahFinal ? "#b8e036" : "#e05555";

  function makeGradient(color) {
    const g = ctx.createLinearGradient(0, 0, 0, 280);
    g.addColorStop(0, color + "30");
    g.addColorStop(1, color + "00");
    return g;
  }

  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: dates,
      datasets: [
        {
          label:                   "Agent",
          data:                    agentVals,
          borderColor:             agentColor,
          borderWidth:             2,
          pointRadius:             0,
          pointHoverRadius:        4,
          pointHoverBackgroundColor: agentColor,
          tension:                 0.3,
          fill:                    true,
          backgroundColor:         makeGradient(agentColor),
        },
        {
          label:                   "Buy & Hold",
          data:                    bahVals,
          borderColor:             "rgba(255,255,255,0.2)",
          borderWidth:             1.5,
          borderDash:              [4, 4],
          pointRadius:             0,
          tension:                 0.3,
          fill:                    false,
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         { mode: "index", intersect: false },
      plugins: {
        legend: {
          display:  true,
          position: "top",
          align:    "end",
          labels: {
            color:     "rgba(255,255,255,0.4)",
            font:      { family: "IBM Plex Mono", size: 11 },
            boxWidth:  16,
            boxHeight: 2,
            padding:   16,
          },
        },
        tooltip: {
          backgroundColor: "#111",
          titleColor:      "rgba(255,255,255,0.4)",
          bodyColor:       "#fff",
          borderColor:     "rgba(255,255,255,0.07)",
          borderWidth:     1,
          padding:         12,
          titleFont:       { family: "IBM Plex Sans",  size: 11 },
          bodyFont:        { family: "IBM Plex Mono",  size: 13 },
          callbacks: {
            label: c => ` ${c.dataset.label}: $${c.parsed.y.toFixed(2)}`,
          },
        },
      },
      scales: {
        x: {
          grid:  { color: "rgba(255,255,255,0.04)", drawTicks: false },
          ticks: {
            color:          "#444",
            font:           { family: "IBM Plex Mono", size: 10 },
            maxTicksLimit:  7,
            maxRotation:    0,
          },
        },
        y: {
          position: "right",
          grid:     { color: "rgba(255,255,255,0.04)", drawTicks: false },
          ticks: {
            color:    "#444",
            font:     { family: "IBM Plex Mono", size: 10 },
            callback: v => "$" + v.toFixed(0),
          },
        },
      },
    },
  });
}

function showChartError(msg) {
  let errEl = document.querySelector(".robot-chart-error");
  if (!errEl) {
    errEl = document.createElement("div");
    errEl.className = "robot-chart-error";
    document.querySelector(".robot-chart-wrap").appendChild(errEl);
  }
  errEl.innerHTML = `<span>⚠</span><span>${msg || "Could not load backtest data."}</span>`;
  errEl.classList.add("visible");
}

/* ── Metrics renderer ──────────────────────────────────────────── */
function renderMetrics(m) {
  function set(id, text, colorClass) {
    const el = document.getElementById(id).querySelector(".robot-metric-value");
    el.textContent = text;
    el.className   = "robot-metric-value" + (colorClass ? " " + colorClass : "");
  }

  const agentRet = m.total_return_pct ?? 0;
  const bahRet   = m.bah_return_pct   ?? 0;

  set("m-return", fmt(agentRet, "%"), agentRet >= 0 ? "pos" : "neg");
  set("m-bah",    fmt(bahRet,   "%"), bahRet   >= 0 ? "pos" : "neg");
  set("m-sharpe", m.sharpe?.toFixed(2) ?? "—");
  set("m-dd",     fmt(-(Math.abs(m.max_drawdown_pct ?? 0)), "%"), "neg");
  set("m-wr",     fmt(m.win_rate_pct ?? 0, "%"));
}

function fmt(val, suffix = "") {
  const sign = val >= 0 ? "+" : "";
  return sign + val.toFixed(2) + suffix;
}

/* ── Profile toggle ────────────────────────────────────────────── */
document.getElementById("profile-toggle").addEventListener("click", e => {
  const btn = e.target.closest(".profile-btn");
  if (!btn) return;
  document.querySelectorAll(".profile-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  currentProfile = btn.dataset.profile;
  refresh();
});

/* ── Init ──────────────────────────────────────────────────────── */
function refresh() {
  loadSignal();
  loadBacktest();
}

refresh();


/* ══════════════════════════════════════════════════════════════
   DEPLOY / STOP / HISTORY
   ══════════════════════════════════════════════════════════════ */

let _backtestTradeLog = [];   // cached from last backtest call
let _activeHistoryTab = "backtest";

/* ── Tab switch ──────────────────────────────────────────────── */
function switchHistoryTab(tab) {
  _activeHistoryTab = tab;
  document.getElementById("tab-backtest").classList.toggle("active", tab === "backtest");
  document.getElementById("tab-live").classList.toggle("active", tab === "live");

  if (tab === "backtest") {
    renderBacktestLog(_backtestTradeLog);
  } else {
    loadLiveHistory();
  }
}

/* ── Render backtest log (round-trip transactions) ───────────── */
function renderBacktestLog(log) {
  const loading = document.getElementById("history-loading");
  const empty   = document.getElementById("history-empty");
  const table   = document.getElementById("history-table");
  const thead   = document.getElementById("history-thead");
  const tbody   = document.getElementById("history-tbody");

  loading.style.display = "none";

  if (!log.length) {
    empty.textContent   = "No completed transactions in backtest period.";
    empty.style.display = "block";
    table.style.display = "none";
    return;
  }

  thead.innerHTML = `<tr>
    <th>Buy Date</th>
    <th>Sell Date</th>
    <th class="num">Shares</th>
    <th class="num">Buy Price</th>
    <th class="num">Sell Price</th>
    <th class="num">P&amp;L</th>
    <th class="num">Net Worth</th>
  </tr>`;

  tbody.innerHTML = log.map((t, i) => {
    const pnlClass = t.pnl >= 0 ? "pnl-pos" : "pnl-neg";
    const pnlSign  = t.pnl >= 0 ? "+" : "";
    const isOpen   = t.sell_date === "Open";
    return `<tr>
      <td>${t.buy_date}</td>
      <td>${isOpen ? '<span class="open-badge">Open</span>' : t.sell_date}</td>
      <td class="num">${t.shares.toFixed(4)}</td>
      <td class="num">$${t.buy_price.toFixed(2)}</td>
      <td class="num">${isOpen ? "<span style='opacity:.4'>current</span>" : "$" + t.sell_price.toFixed(2)}</td>
      <td class="num ${pnlClass}">${pnlSign}$${t.pnl.toFixed(2)}</td>
      <td class="num">$${t.net_worth.toFixed(2)}</td>
    </tr>`;
  }).join("");

  empty.style.display = "none";
  table.style.display = "table";
}

/* ── Load live robot trades from DB ──────────────────────────── */
async function loadLiveHistory() {
  const loading = document.getElementById("history-loading");
  const empty   = document.getElementById("history-empty");
  const table   = document.getElementById("history-table");
  const thead   = document.getElementById("history-thead");
  const tbody   = document.getElementById("history-tbody");

  loading.style.display = "flex";
  empty.style.display   = "none";
  table.style.display   = "none";

  try {
    const resp = await fetch(`/api/robot/history/${SYMBOL}/`);
    const data = await resp.json();
    const trades = data.trades || [];

    if (!trades.length) {
      empty.textContent   = "No live robot trades yet for " + SYMBOL + ".";
      empty.style.display = "block";
      return;
    }

    thead.innerHTML = `<tr>
      <th>Date</th><th>Action</th>
      <th class="num">Price</th><th class="num">Shares</th>
      <th class="num">Budget After</th><th>Note</th>
    </tr>`;

    tbody.innerHTML = trades.map(t => `
      <tr>
        <td>${t.timestamp}</td>
        <td class="action-${t.action.toLowerCase()}">${t.action}</td>
        <td class="num">$${t.price.toFixed(2)}</td>
        <td class="num">${t.shares > 0 ? t.shares.toFixed(4) : "—"}</td>
        <td class="num">$${t.balance_after.toFixed(2)}</td>
        <td>${t.note}</td>
      </tr>
    `).join("");

    table.style.display = "table";
  } catch (e) {
    empty.textContent   = "Could not load history.";
    empty.style.display = "block";
  } finally {
    loading.style.display = "none";
  }
}

/* ── Populate backtest log cache after loadBacktest() ────────── */
function _cacheBacktestLog(tradeLog) {
  _backtestTradeLog = tradeLog || [];
  if (_activeHistoryTab === "backtest") {
    renderBacktestLog(_backtestTradeLog);
  }
}

/* ── Check if robot is already deployed for this ticker ──────── */
async function checkDeployStatus() {
  try {
    const resp = await fetch("/api/robot/deploy/");
    const data = await resp.json();
    const session = (data.sessions || []).find(s => s.symbol === SYMBOL);
    if (session) {
      setDeployedUI(session.risk_profile, session.budget);
    } else {
      setStoppedUI();
    }
  } catch (e) {
    console.error("Could not check deploy status:", e);
  }
}

function setDeployedUI(profile, budget) {
  const budgetStr = budget ? ` — $${Number(budget).toLocaleString()}` : "";
  document.getElementById("deploy-dot").className           = "deploy-dot active";
  document.getElementById("deploy-status-text").textContent = `Active — ${profile}${budgetStr}`;
  document.getElementById("btn-deploy").style.display       = "none";
  document.getElementById("btn-stop").style.display         = "inline-block";
  document.getElementById("budget-input").closest(".budget-input-group").style.opacity      = "0.4";
  document.getElementById("budget-input").closest(".budget-input-group").style.pointerEvents = "none";
}

function setStoppedUI() {
  document.getElementById("deploy-dot").className           = "deploy-dot inactive";
  document.getElementById("deploy-status-text").textContent = "Not deployed";
  document.getElementById("btn-deploy").style.display       = "inline-block";
  document.getElementById("btn-stop").style.display         = "none";
  document.getElementById("budget-input").closest(".budget-input-group").style.opacity      = "1";
  document.getElementById("budget-input").closest(".budget-input-group").style.pointerEvents = "auto";
}

/* ── Deploy ─────────────────────────────────────────────────── */
async function deployRobot() {
  const errEl  = document.getElementById("deploy-error");
  const budget = parseFloat(document.getElementById("budget-input").value);
  errEl.classList.remove("visible");

  if (!budget || budget < 100) {
    errEl.textContent = "Minimum budget is $100.";
    errEl.classList.add("visible");
    return;
  }

  try {
    const resp = await fetch("/api/robot/deploy/", {
      method:  "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body:    JSON.stringify({ ticker: SYMBOL, risk_profile: currentProfile, budget }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    setDeployedUI(currentProfile, data.budget);
  } catch (e) {
    errEl.textContent = e.message || "Deploy failed.";
    errEl.classList.add("visible");
  }
}

/* ── Stop ────────────────────────────────────────────────────── */
async function stopRobot() {
  const errEl = document.getElementById("deploy-error");
  errEl.classList.remove("visible");

  try {
    const resp = await fetch("/api/robot/stop/", {
      method:  "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body:    JSON.stringify({ ticker: SYMBOL }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    setStoppedUI();
  } catch (e) {
    errEl.textContent = e.message || "Stop failed.";
    errEl.classList.add("visible");
  }
}

/* ── History ─────────────────────────────────────────────────── */
async function loadHistory() {
  const loading = document.getElementById("history-loading");
  const empty   = document.getElementById("history-empty");
  const table   = document.getElementById("history-table");
  const tbody   = document.getElementById("history-tbody");

  loading.style.display = "flex";
  empty.style.display   = "none";
  table.style.display   = "none";

  try {
    const resp = await fetch(`/api/robot/history/${SYMBOL}/`);
    const data = await resp.json();
    const trades = data.trades || [];

    if (!trades.length) {
      empty.style.display = "block";
      return;
    }

    tbody.innerHTML = trades.map(t => `
      <tr>
        <td>${t.timestamp}</td>
        <td class="action-${t.action.toLowerCase()}">${t.action}</td>
        <td class="num">$${t.price.toFixed(2)}</td>
        <td class="num">${t.shares > 0 ? t.shares.toFixed(4) : "—"}</td>
        <td class="num">$${t.balance_after.toFixed(2)}</td>
        <td>${t.note}</td>
      </tr>
    `).join("");

    table.style.display = "table";
  } catch (e) {
    empty.textContent   = "Could not load history.";
    empty.style.display = "block";
  } finally {
    loading.style.display = "none";
  }
}

/* ── Init ────────────────────────────────────────────────────── */
checkDeployStatus();
// Backtest log is populated automatically when loadBacktest() completes
// Render empty state for history until backtest loads
renderBacktestLog([]);