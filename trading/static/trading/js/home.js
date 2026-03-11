/* ─── STATE ───────────────────────────────────────────────── */
let currentSymbol = 'AAPL';
let currentTf     = '1M';

/* ─── COMPANY NAMES ───────────────────────────────────────── */
const companies = {
  AAPL:  'Apple Inc.',
  AMZN:  'Amazon.com Inc.',
  GOOGL: 'Alphabet Inc.',
  JPM:   'JPMorgan Chase & Co.',
  META:  'Meta Platforms Inc.',
  MSFT:  'Microsoft Corporation',
  NVDA:  'NVIDIA Corporation',
  TSLA:  'Tesla Inc.',
  V:     'Visa Inc.',
};

/* ─── CHART SETUP ─────────────────────────────────────────── */
const ctx = document.getElementById('stockChart').getContext('2d');
let chart = null;

function buildGradient(color) {
  const g = ctx.createLinearGradient(0, 0, 0, 340);
  g.addColorStop(0, color + '38');
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
        borderWidth: 2,
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
          titleColor: 'rgba(255,255,255,0.5)',
          bodyColor: '#fff',
          borderColor: 'rgba(255,255,255,0.07)',
          borderWidth: 1,
          padding: 12,
          titleFont: { family: 'IBM Plex Sans', size: 11 },
          bodyFont:  { family: 'IBM Plex Mono', size: 15 },
          callbacks: { label: c => ' $' + c.parsed.y.toFixed(2) },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: '#444',
            font: { family: 'IBM Plex Mono', size: 11 },
            maxTicksLimit: 7,
            maxRotation: 0,
          },
        },
        y: {
          position: 'right',
          grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks: {
            color: '#444',
            font: { family: 'IBM Plex Mono', size: 11 },
            callback: v => '$' + v.toFixed(0),
          },
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

    if (data.error || !data.bars || !data.bars.length) {
      throw new Error(data.error || 'No data');
    }

    const bars   = data.bars;
    const labels = bars.map(b => b.t);
    const prices = bars.map(b => b.c);
    const latest = prices[prices.length - 1];
    const prev   = prices[0];
    const change = latest - prev;
    const pct    = (change / prev) * 100;
    const isUp   = change >= 0;

    document.getElementById('chart-symbol').textContent  = symbol;
    document.getElementById('chart-company').textContent = companies[symbol] || symbol;
    document.getElementById('chart-price').textContent   = '$' + latest.toFixed(2);

    const ce = document.getElementById('chart-change');
    ce.textContent = `${isUp ? '+' : ''}${change.toFixed(2)}  (${isUp ? '+' : ''}${pct.toFixed(2)}%)`;
    ce.className   = 'chart-price-change ' + (isUp ? 'pos' : 'neg');

    renderChart(labels, prices);

  } catch {
    document.getElementById('chart-price').textContent  = 'Unavailable';
    document.getElementById('chart-change').textContent = 'Could not retrieve data';
  } finally {
    loading.classList.remove('visible');
  }
}

/* ─── STOCK SELECTOR ──────────────────────────────────────── */
document.getElementById('stock-selector').addEventListener('click', e => {
  const pill = e.target.closest('.stock-pill');
  if (!pill) return;
  document.querySelectorAll('.stock-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
  currentSymbol = pill.dataset.symbol;
  loadStock(currentSymbol, currentTf);
});

/* ─── TIMEFRAME SELECTOR ──────────────────────────────────── */
document.getElementById('tf-selector').addEventListener('click', e => {
  const btn = e.target.closest('.tf-btn');
  if (!btn) return;
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentTf = btn.dataset.tf;
  loadStock(currentSymbol, currentTf);
});

/* ─── INIT ────────────────────────────────────────────────── */
loadStock(currentSymbol, currentTf);