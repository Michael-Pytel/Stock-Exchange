/* ─── STATE ───────────────────────────────────────────────── */
let currentTf    = '1M';
let currentMode  = 'buy';   // 'buy' | 'sell'
let latestPrice  = 0;
let userBalance  = parseFloat(document.getElementById('live-balance').textContent.replace(/[^0-9.]/g, ''));
let posShares    = HAS_POS ? parseFloat(document.getElementById('pos-shares').textContent) : 0;
let posAvg       = AVG_BUY;

/* ─── COMPANY NAMES ───────────────────────────────────────── */
const companies = {
  AAPL: 'Apple Inc.', AMZN: 'Amazon.com Inc.', GOOGL: 'Alphabet Inc.',
  JPM: 'JPMorgan Chase & Co.', META: 'Meta Platforms Inc.',
  MSFT: 'Microsoft Corporation', NVDA: 'NVIDIA Corporation',
  TSLA: 'Tesla Inc.', V: 'Visa Inc.',
};

/* ─── CHART ───────────────────────────────────────────────── */
const ctx = document.getElementById('stockChart').getContext('2d');
let chart = null;

function buildGradient(color) {
  const g = ctx.createLinearGradient(0, 0, 0, 380);
  g.addColorStop(0, color + '35');
  g.addColorStop(1, color + '00');
  return g;
}

function renderChart(labels, prices) {
  const isUp      = prices[prices.length - 1] >= prices[0];
  const lineColor = isUp ? '#b8e036' : '#e05555';
  if (chart) chart.destroy();

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: prices,
        borderColor: lineColor,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: lineColor,
        tension: 0.38,
        fill: true,
        backgroundColor: buildGradient(lineColor),
      }],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#111',
          titleColor: 'rgba(255,255,255,0.45)',
          bodyColor: '#fff',
          borderColor: 'rgba(255,255,255,0.07)',
          borderWidth: 1,
          padding: 12,
          titleFont: { family: 'IBM Plex Sans', size: 11 },
          bodyFont:  { family: 'IBM Plex Mono', size: 14 },
          callbacks: { label: c => ' $' + c.parsed.y.toFixed(2) },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: { color: '#444', font: { family: 'IBM Plex Mono', size: 11 }, maxTicksLimit: 8, maxRotation: 0 },
        },
        y: {
          position: 'right',
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: { color: '#444', font: { family: 'IBM Plex Mono', size: 11 }, callback: v => '$' + v.toFixed(0) },
        },
      },
    },
  });
}

/* ─── LOAD STOCK DATA ─────────────────────────────────────── */
async function loadStock(symbol, tf) {
  const loading = document.getElementById('chart-loading');
  loading.classList.add('visible');

  try {
    const resp = await fetch(`/api/stock/${symbol}/?tf=${tf}`);
    const data = await resp.json();
    if (data.error || !data.bars?.length) throw new Error(data.error || 'No data');

    const bars   = data.bars;
    const labels = bars.map(b => b.t);
    const prices = bars.map(b => b.c);
    latestPrice  = prices[prices.length - 1];
    const prev   = prices[0];
    const change = latestPrice - prev;
    const pct    = (change / prev) * 100;
    const isUp   = change >= 0;

    document.getElementById('chart-symbol').textContent  = symbol;
    document.getElementById('chart-company').textContent = companies[symbol] || symbol;
    document.getElementById('chart-price').textContent   = '$' + latestPrice.toFixed(2);

    const ce = document.getElementById('chart-change');
    ce.textContent = `${isUp ? '+' : ''}${change.toFixed(2)}  (${isUp ? '+' : ''}${pct.toFixed(2)}%)  ${tf}`;
    ce.className   = 'trade-change ' + (isUp ? 'pos' : 'neg');

    document.getElementById('order-price').textContent = '$' + latestPrice.toFixed(2);

    renderChart(labels, prices);
    updateEstimate();
    updatePositionBox();

  } catch(e) {
    document.getElementById('chart-price').textContent  = 'Unavailable';
    document.getElementById('chart-change').textContent = 'Could not load data';
  } finally {
    loading.classList.remove('visible');
  }
}

/* ─── TIMEFRAME ───────────────────────────────────────────── */
document.getElementById('tf-selector').addEventListener('click', e => {
  const btn = e.target.closest('.tf-btn');
  if (!btn) return;
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentTf = btn.dataset.tf;
  loadStock(SYMBOL, currentTf);
});

/* ─── ORDER PANEL ─────────────────────────────────────────── */
function switchTab(mode) {
  currentMode = mode;
  document.getElementById('tab-buy').classList.toggle('active',  mode === 'buy');
  document.getElementById('tab-sell').classList.toggle('active', mode === 'sell');

  const btn = document.getElementById('btn-order');
  btn.textContent = mode === 'buy' ? `Buy ${SYMBOL}` : `Sell ${SYMBOL}`;
  btn.className   = 'btn-order ' + mode;

  document.getElementById('shares-input').value = '';
  document.getElementById('order-estimate').textContent = '$0.00';
  hideError();
}

function updateEstimate() {
  const shares = parseFloat(document.getElementById('shares-input').value) || 0;
  const est    = shares * latestPrice;
  document.getElementById('order-estimate').textContent = '$' + est.toFixed(2);
  hideError();
}

function showError(msg) {
  const el = document.getElementById('order-error');
  el.textContent = msg;
  el.classList.add('visible');
}

function hideError() {
  document.getElementById('order-error').classList.remove('visible');
}

/* ─── UPDATE POSITION BOX ─────────────────────────────────── */
function updatePositionBox() {
  const box = document.getElementById('position-box');
  if (posShares <= 0) { box.style.display = 'none'; return; }

  box.style.display = 'flex';
  const value   = posShares * latestPrice;
  const cost    = posShares * posAvg;
  const pnl     = value - cost;
  const pnlPct  = (pnl / cost) * 100;
  const isUp    = pnl >= 0;

  document.getElementById('pos-shares').textContent = posShares.toFixed(4);
  document.getElementById('pos-value').textContent  = '$' + value.toFixed(2);

  const retEl = document.getElementById('pos-return');
  retEl.textContent = `${isUp ? '+' : ''}$${pnl.toFixed(2)} (${isUp ? '+' : ''}${pnlPct.toFixed(2)}%)`;
  retEl.className   = 'order-value ' + (isUp ? 'pos' : 'neg');
}

/* ─── SUBMIT ORDER ────────────────────────────────────────── */
async function submitOrder() {
  const shares = parseFloat(document.getElementById('shares-input').value);
  if (!shares || shares <= 0) { showError('Enter a valid share quantity.'); return; }

  if (currentMode === 'buy') {
    const cost = shares * latestPrice;
    if (cost > userBalance) { showError('Insufficient balance.'); return; }
  } else {
    if (shares > posShares) { showError('Not enough shares to sell.'); return; }
  }

  const btn = document.getElementById('btn-order');
  btn.disabled = true;

  const url  = currentMode === 'buy' ? '/api/buy/' : '/api/sell/';
  const body = new URLSearchParams({ symbol: SYMBOL, shares: shares, csrfmiddlewaretoken: CSRF });

  try {
    const resp = await fetch(url, { method: 'POST', body });
    const data = await resp.json();

    if (data.error) { showError(data.error); return; }

    // Update local state
    userBalance = data.balance;
    posShares   = data.shares;
    if (data.avg) posAvg = data.avg;

    document.getElementById('live-balance').textContent  = '$' + userBalance.toFixed(2);
    document.getElementById('order-balance').textContent = '$' + userBalance.toFixed(2);
    document.getElementById('shares-input').value = '';
    document.getElementById('order-estimate').textContent = '$0.00';

    updatePositionBox();
    hideError();

    // Flash balance green
    const balEl = document.getElementById('live-balance');
    balEl.style.color = '#b8e036';
    setTimeout(() => balEl.style.color = '', 1200);

  } catch(e) {
    showError('Network error. Please try again.');
  } finally {
    btn.disabled = false;
  }
}

/* ─── DISCLAIMER ──────────────────────────────────────────── */
const overlay = document.getElementById('disclaimer-overlay');
if (overlay) {
  document.getElementById('btn-accept').addEventListener('click', async () => {
    await fetch('/api/disclaimer/accept/', {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF },
    });
    overlay.style.opacity = '0';
    overlay.style.transition = 'opacity 0.3s';
    setTimeout(() => overlay.remove(), 300);
  });

  document.getElementById('btn-dismiss').addEventListener('click', () => {
    window.location.href = '/logout/';
  });
}

/* ─── INIT ────────────────────────────────────────────────── */
loadStock(SYMBOL, currentTf);

/* ═══════════════════════════════════════════════════════════════
   FORECAST — zastąp cały poprzedni blok forecast w trading_page.js
   ═══════════════════════════════════════════════════════════════ */

/* ─── STATE ───────────────────────────────────────────────── */
let fcChart       = null;
let fcData        = null;
let fcStopLoss    = -0.05;

/* ─── HELPERS ─────────────────────────────────────────────── */
function fmtPct(v) {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
}

function getRisk(stopLoss, d) {
  if      (stopLoss >= d.q03)  return { label: 'HIGH RISK', cls: 'risk-high', range: `above Q(0.30)`         };
  else if (stopLoss >= d.q01)  return { label: 'MONITOR',   cls: 'risk-mid',  range: `Q(0.10) – Q(0.30)`    };
  else if (stopLoss >= d.q005) return { label: 'LOW RISK',  cls: 'risk-low',  range: `Q(0.05) – Q(0.10)`    };
  else                          return { label: 'VERY LOW',  cls: 'risk-vlow', range: `below Q(0.05)`         };
}

/* ─── SLIDER ──────────────────────────────────────────────── */
const slSlider = document.getElementById('sl-slider');
const slValue  = document.getElementById('sl-value');
const slApply  = document.getElementById('sl-apply');

// Init display on load
slValue.textContent = fmtPct(parseFloat(slSlider.value));

slSlider.addEventListener('input', () => {
  const v = parseFloat(slSlider.value);
  slValue.textContent = fmtPct(v);
  slValue.style.color = v > -0.03 ? '#f0a030' : '#e05555';
});

slApply.addEventListener('click', () => {
  fcStopLoss = parseFloat(slSlider.value);
  if (fcData) drawForecast(fcData, fcStopLoss);
});

/* ─── LOAD ────────────────────────────────────────────────── */
async function loadForecast(symbol) {
  const loading = document.getElementById('fc-loading');
  const errBox  = document.getElementById('fc-error');
  const riskSec = document.getElementById('risk-section');

  loading.classList.add('visible');
  errBox.style.display = 'none';
  riskSec.classList.remove('visible');
  if (fcChart) { fcChart.destroy(); fcChart = null; }

  try {
    const resp = await fetch(`/forecast/${symbol}/`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);

    fcData = data;
    drawForecast(data, fcStopLoss);
    riskSec.classList.add('visible');

  } catch(e) {
    errBox.textContent   = '⚠ Could not load forecast: ' + e.message;
    errBox.style.display = 'block';
  } finally {
    loading.classList.remove('visible');
  }
}

/* ─── DRAW ────────────────────────────────────────────────── */
function drawForecast(data, stopLoss) {
  const { history, forecast, last_val } = data;

  const histLabels = history.map(d => d.date);
  const fcLabels   = forecast.map(d => d.date);
  const allLabels  = [...histLabels, ...fcLabels];
  const splitIdx   = histLabels.length;
  const pad        = [...Array(splitIdx - 1).fill(null)];

  const histData   = [...history.map(d => d.value), ...Array(fcLabels.length).fill(null)];
  const medianData = [...pad, last_val, ...forecast.map(d => d.median)];
  const q09Data    = [...pad, last_val, ...forecast.map(d => d.q09)];
  const q01Data    = [...pad, last_val, ...forecast.map(d => d.q01)];
  const q095Data   = [...pad, last_val, ...forecast.map(d => d.q095)];
  const q005Data   = [...pad, last_val, ...forecast.map(d => d.q005)];
  const slData     = allLabels.map(() => stopLoss);

  const histColor = '#808080';
  const fcCtx     = document.getElementById('forecastChart').getContext('2d');
  const histGrad  = fcCtx.createLinearGradient(0, 0, 0, 0);
  histGrad.addColorStop(0, '#4a9e6b20');
  histGrad.addColorStop(1, '#4a9e6b00');

  if (fcChart) fcChart.destroy();

  fcChart = new Chart(fcCtx, {
    type: 'line',
    data: {
      labels: allLabels,
      datasets: [
        // Q 5–95% outer band (orange)
        {
          label: 'Q 5–95%',
          data: q095Data,
          borderColor: 'transparent',
          backgroundColor: 'rgba(240,160,48,0.10)',
          fill: '+1',
          pointRadius: 0,
          tension: 0.35,
          order: 5,
        },
        {
          label: 'Q 5–95% low',
          data: q005Data,
          borderColor: 'transparent',
          borderWidth: 1,
          borderDash: [3, 3],
          fill: false,
          pointRadius: 0,
          tension: 0.35,
          order: 5,
        },
        // Q 10–90% inner band (blue)
        {
          label: 'Q 10–90%',
          data: q09Data,
          borderColor: 'transparent',
          backgroundColor: 'rgba(224,85,85,0.15)',
          fill: '+1',
          pointRadius: 0,
          tension: 0.35,
          order: 4,
        },
        {
          label: 'Q 10–90% low',
          data: q01Data,
          borderColor: 'transparent',
          borderWidth: 1,
          borderDash: [3, 3],
          fill: false,
          pointRadius: 0,
          tension: 0.35,
          order: 4,
        },
        // History
        {
          label: 'History',
          data: histData,
          borderColor: histColor,
          borderWidth: 1.5,
          backgroundColor: histGrad,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: histColor,
          tension: 0.38,
          order: 2,
        },
        // Median
        {
          label: 'Forecast Median',
          data: medianData,
          borderColor: 'rgba(184, 224, 54, 0.6)',
          borderWidth: 1.5,
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#b8e036',
          tension: 0.35,
          order: 1,
        },
        // Return Threshold
        {
          label: 'Return Threshold',
          data: slData,
          borderColor: 'rgba(224,85,85,0.75)',
          borderWidth: 1.2,
          borderDash: [6, 4],
          fill: false,
          pointRadius: 0,
          tension: 0,
          order: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#555',
            font: { family: 'IBM Plex Mono', size: 11 },
            boxWidth: 14,
            padding: 16,
            // Show only the "top" dataset of each band pair, hide the low borders
            filter: item => !item.text.endsWith('low'),
          },
        },
        tooltip: {
          backgroundColor: '#111',
          titleColor: 'rgba(255,255,255,0.45)',
          bodyColor: '#fff',
          borderColor: 'rgba(255,255,255,0.07)',
          borderWidth: 1,
          padding: 12,
          titleFont: { family: 'IBM Plex Sans', size: 11 },
          bodyFont:  { family: 'IBM Plex Mono', size: 13 },
          callbacks: {
            // Only show: Median, Q5-95% top, Q5-95% low, Q10-90% top, Q10-90% low
            // i.e. the 4 quantile lines + median. Hide History, Threshold, fill datasets.
            label: c => {
              const name = c.dataset.label;
              const v    = c.parsed.y;
              if (v === null) return null;

              if (name === 'Median')        return ` Median:    ${fmtPct(v)}`;
              if (name === 'Q 10–90%')      return ` Q(0.90):   ${fmtPct(v)}`;
              if (name === 'Q 10–90% low')  return ` Q(0.10):   ${fmtPct(v)}`;
              if (name === 'Q 5–95%')       return ` Q(0.95):   ${fmtPct(v)}`;
              if (name === 'Q 5–95% low')   return ` Q(0.05):   ${fmtPct(v)}`;
              return null;   // hide History, Return Threshold
            },
            // Custom ordering: Median first, then quantiles
            afterBody: () => null,
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: '#444',
            font: { family: 'IBM Plex Mono', size: 11 },
            maxTicksLimit: 10,
            maxRotation: 0,
          },
        },
        y: {
          position: 'left',
          title: {
            display: true,
            text: 'Return 1 Day',
            color: '#444',
            font: { family: 'IBM Plex Mono', size: 11 },
          },
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: '#444',
            font: { family: 'IBM Plex Mono', size: 11 },
            callback: v => fmtPct(v),
          },
        },
      },
    },
  });

  buildRiskTable(forecast, stopLoss);
}

/* ─── RISK TABLE ──────────────────────────────────────────── */
function buildRiskTable(forecast, stopLoss) {
  const tbody = document.getElementById('risk-tbody');
  tbody.innerHTML = forecast.map(d => {
    const { label, cls, range } = getRisk(stopLoss, d);
    return `<tr>
      <td>${d.date}</td>
      <td>${fmtPct(d.q005)}</td>
      <td>${fmtPct(d.q01)}</td>
      <td>${fmtPct(d.q03)}</td>
      <td>${fmtPct(d.median)}</td>
      <td class="q-range">${range}</td>
      <td class="${cls}">${label}</td>
    </tr>`;
  }).join('');
}

/* ─── INIT ────────────────────────────────────────────────── */
loadForecast(SYMBOL);