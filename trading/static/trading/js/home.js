/* ═══════════════════════════════════════════════════════════
   home.js — Robot performance charts
   ═══════════════════════════════════════════════════════════ */

const ACCENT  = '#b8e036';
const ACCENT2 = '#2ee8c4';
const RED     = '#e05555';
const DIM     = 'rgba(255,255,255,0.18)';
const BG      = '#0d0d0d';

Chart.defaults.color          = 'rgba(255,255,255,0.35)';
Chart.defaults.borderColor    = 'rgba(255,255,255,0.06)';
Chart.defaults.font.family    = "'IBM Plex Sans', sans-serif";

/* ── State ───────────────────────────────────────────────── */
let currentTicker  = 'AAPL';
let currentProfile = 'aggressive';
let equityChart    = null;
let winLossChart   = null;
let fetchController = null;

/* ── Scroll-reveal animation ─────────────────────────────── */
const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
  });
}, { threshold: 0.12 });

document.querySelectorAll('.feature-card, .rmetric-card, .rchart-panel').forEach(el => {
  el.classList.add('reveal');
  observer.observe(el);
});

/* ── Demo data (shown when logged out or API unavailable) ── */
function makeDemoData() {
  /* Simulate ~500 days of agent vs B&H starting at $10,000  */
  const n = 500;
  const dates = [];
  let agentVal = 10000, bahVal = 10000;
  const equityAgent = [], equityBah = [];

  const baseDate = new Date('2020-07-01');
  let d = new Date(baseDate);
  for (let i = 0; i < n; i++) {
    // skip weekends
    while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
    dates.push(d.toISOString().slice(0, 10));

    // B&H: random walk biased +0.04%/day  (mimics AAPL ~85% over period)
    const bahRet = (Math.random() - 0.482) * 0.022;
    bahVal *= (1 + bahRet);

    // Agent: slightly better + lower vol
    const agentRet = (Math.random() - 0.470) * 0.018 + 0.0001;
    agentVal *= (1 + agentRet);

    equityBah.push(+bahVal.toFixed(2));
    equityAgent.push(+agentVal.toFixed(2));
    d.setDate(d.getDate() + 1);
  }

  const agFinal  = equityAgent[equityAgent.length - 1];
  const bahFinal = equityBah[equityBah.length - 1];
  const agRet    = ((agFinal / 10000 - 1) * 100).toFixed(1);
  const bahRet2  = ((bahFinal / 10000 - 1) * 100).toFixed(1);

  return {
    metrics: {
      total_return_pct:     parseFloat(agRet),
      bah_return_pct:       parseFloat(bahRet2),
      outperform_pct:       parseFloat((agRet - bahRet2).toFixed(1)),
      sharpe:               1.42,
      bah_sharpe:           0.98,
      max_drawdown_pct:     -14.3,
      bah_max_drawdown_pct: -23.8,
      trades:               87,
      win_rate_pct:         64.4,
      agent_final:          agFinal,
      bah_final:            bahFinal,
    },
    equity_curve: equityAgent,
    bah_curve:    equityBah,
    dates,
    _demo: true,
  };
}

/* ── Thin out dates for x-axis labels ───────────────────── */
function sparseLabels(dates, maxTicks = 10) {
  const step = Math.max(1, Math.floor(dates.length / maxTicks));
  return dates.map((d, i) => i % step === 0 ? d.slice(0, 7) : '');
}

/* ── Render equity chart ─────────────────────────────────── */
function renderEquityChart(data) {
  const ctx = document.getElementById('equityChart').getContext('2d');

  const agentGrad = ctx.createLinearGradient(0, 0, 0, 320);
  agentGrad.addColorStop(0, ACCENT + '28');
  agentGrad.addColorStop(1, ACCENT + '00');

  if (equityChart) equityChart.destroy();

  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.dates,
      datasets: [
        {
          label: 'Agent',
          data: data.equity_curve,
          borderColor: ACCENT,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.35,
          fill: true,
          backgroundColor: agentGrad,
          order: 1,
        },
        {
          label: 'Buy & Hold',
          data: data.bah_curve,
          borderColor: DIM,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.35,
          fill: false,
          borderDash: [4, 4],
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600, easing: 'easeOutQuart' },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#111',
          titleColor: 'rgba(255,255,255,0.45)',
          bodyColor: '#fff',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          padding: 12,
          titleFont:  { family: 'IBM Plex Sans', size: 11 },
          bodyFont:   { family: 'IBM Plex Mono', size: 13 },
          callbacks: {
            title: items => items[0].label,
            label: item => ` ${item.dataset.label}: $${item.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: 'rgba(255,255,255,0.2)',
            font: { family: 'IBM Plex Mono', size: 10 },
            maxTicksLimit: 10,
            maxRotation: 0,
            callback: function(val, idx) {
              const label = this.getLabelForValue(val);
              const step = Math.max(1, Math.floor(data.dates.length / 10));
              return idx % step === 0 ? label.slice(0, 7) : '';
            },
          },
        },
        y: {
          position: 'right',
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: 'rgba(255,255,255,0.2)',
            font: { family: 'IBM Plex Mono', size: 10 },
            callback: v => '$' + (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v.toFixed(0)),
          },
        },
      },
    },
  });
}

/* ── Render win/loss donut ───────────────────────────────── */
function renderWinLoss(metrics) {
  const ctx = document.getElementById('winLossChart').getContext('2d');

  const wins   = Math.round(metrics.trades * metrics.win_rate_pct / 100);
  const losses = metrics.trades - wins;

  document.getElementById('wins-val').textContent   = wins;
  document.getElementById('losses-val').textContent  = losses;
  document.getElementById('donut-pct').textContent   = metrics.win_rate_pct.toFixed(1) + '%';

  if (winLossChart) winLossChart.destroy();

  winLossChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Wins', 'Losses'],
      datasets: [{
        data: [wins, losses],
        backgroundColor: [ACCENT + 'cc', RED + '88'],
        borderColor:     [ACCENT,         RED],
        borderWidth: 1.5,
        hoverOffset: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '74%',
      animation: { duration: 700, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#111',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          padding: 10,
          bodyFont: { family: 'IBM Plex Mono', size: 13 },
          callbacks: { label: i => ` ${i.label}: ${i.raw}` },
        },
      },
    },
  });
}

/* ── Update metrics row ───────────────────────────────────── */
function updateMetrics(m) {
  const fmt = (v, decimals = 1) => (v > 0 ? '+' : '') + v.toFixed(decimals);
  const pct = v => fmt(v) + '%';

  const retEl = document.getElementById('rm-return');
  retEl.textContent = pct(m.total_return_pct);
  retEl.className   = 'rmetric-value ' + (m.total_return_pct >= 0 ? 'pos' : 'neg');

  document.getElementById('rm-bah-return').textContent   = 'vs B&H ' + pct(m.bah_return_pct);
  document.getElementById('rm-outperform').textContent   = pct(m.outperform_pct);
  document.getElementById('rm-sharpe').textContent       = m.sharpe.toFixed(2);
  document.getElementById('rm-bah-sharpe').textContent   = 'vs B&H ' + m.bah_sharpe.toFixed(2);
  document.getElementById('rm-winrate').textContent      = m.win_rate_pct.toFixed(1) + '%';
  document.getElementById('rm-trades').textContent       = m.trades + ' trades';
  document.getElementById('rm-dd').textContent           = pct(m.max_drawdown_pct);
  document.getElementById('rm-bah-dd').textContent       = 'vs B&H ' + pct(m.bah_max_drawdown_pct);

  const outEl = document.getElementById('rm-outperform');
  outEl.className = 'rmetric-value ' + (m.outperform_pct >= 0 ? 'pos' : 'neg');
}

/* ── Load data ────────────────────────────────────────────── */
async function loadRobotData(ticker, profile) {
  // Show loading
  document.getElementById('equity-loading').style.opacity = '1';
  document.getElementById('equity-loading').style.pointerEvents = 'all';

  // Cancel any in-flight request
  if (fetchController) fetchController.abort();
  fetchController = new AbortController();

  let data;
  try {
    // Public endpoint — real backtest data for all visitors
    const resp = await fetch('/api/robot/backtest/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ ticker, risk_profile: profile }),
      signal: fetchController.signal,
    });
    data = await resp.json();
    if (data.error || !data.equity_curve?.length) throw new Error(data.error || 'empty');
  } catch (e) {
    if (e.name === 'AbortError') return;
    data = makeDemoData();
    data._demo = true;
  }

  document.getElementById('equity-loading').style.opacity = '0';
  document.getElementById('equity-loading').style.pointerEvents = 'none';

  updateMetrics(data.metrics);
  renderEquityChart(data);
  renderWinLoss(data.metrics);

  // Demo badge
  const badge = document.getElementById('demo-badge');
  if (data._demo && badge) {
    badge.style.display = 'inline-flex';
  } else if (badge) {
    badge.style.display = 'none';
  }
}

/* ── CSRF helper ─────────────────────────────────────────── */
function getCookie(name) {
  const v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return v ? v.pop() : '';
}

/* ── Pill controls ───────────────────────────────────────── */
document.getElementById('rb-ticker-pills')?.addEventListener('click', e => {
  const pill = e.target.closest('.rctrl-pill');
  if (!pill) return;
  document.querySelectorAll('#rb-ticker-pills .rctrl-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
  currentTicker = pill.dataset.ticker;
  loadRobotData(currentTicker, currentProfile);
});

document.getElementById('rb-profile-pills')?.addEventListener('click', e => {
  const pill = e.target.closest('.rctrl-pill');
  if (!pill) return;
  document.querySelectorAll('#rb-profile-pills .rctrl-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
  currentProfile = pill.dataset.profile;
  loadRobotData(currentTicker, currentProfile);
});

/* ── Init ────────────────────────────────────────────────── */
loadRobotData(currentTicker, currentProfile);