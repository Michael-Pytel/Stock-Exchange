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