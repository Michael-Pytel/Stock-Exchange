/* ─── STATE ───────────────────────────────────────────────── */
let currentTf    = '1M';
let currentMode  = 'buy';
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

/* ═══════════════════════════════════════════════════════════
   LIGHTWEIGHT CHARTS — STOCK CHART
   ═══════════════════════════════════════════════════════════ */

const UP   = '#26a69a';
const DOWN = '#ef5350';
const LINE = '#b8e036';
const BG   = '#080808';

let lwChart     = null;
let volChart    = null;
let rsiChart    = null;
let mainSeries  = null;
let volSeries   = null;
let allBars     = [];
let currentCt   = 'line';

// Indicator series
let indSeries = { sma20: null, sma50: null, ema20: null, bbUpper: null, bbMid: null, bbLower: null };
let rsiSeries = null;

let chartSyncing = false;


let baselinePrice = null;
let isDraggingBL  = false;
let earliestTime  = null;   // UNIX seconds of oldest loaded bar
let isFetchingMore = false; // prevents concurrent fetches
let noMoreHistory  = false; // set true when API returns nothing new

/* ── Market status ────────────────────────────────────────── */
function getETNow() {
  const now  = new Date();
  const year = now.getUTCFullYear();

  // US DST: starts 2nd Sunday of March at 2am, ends 1st Sunday of November at 2am
  const dstStart = new Date(Date.UTC(year, 2, 1));   // March 1 UTC
  dstStart.setUTCDate(1 + (7 - dstStart.getUTCDay()) % 7 + 7); // 2nd Sunday
  dstStart.setUTCHours(7); // 2am ET = 7am UTC (during EST)

  const dstEnd = new Date(Date.UTC(year, 10, 1));    // November 1 UTC
  dstEnd.setUTCDate(1 + (7 - dstEnd.getUTCDay()) % 7); // 1st Sunday
  dstEnd.setUTCHours(6); // 2am ET = 6am UTC (during EDT)

  const isDST   = now >= dstStart && now < dstEnd;
  const etOffsetMs = (isDST ? -4 : -5) * 3600000;
  return new Date(now.getTime() + etOffsetMs);
}

function updateMarketStatus() {
  const et  = getETNow();
  const day  = et.getUTCDay();   // 0=Sun, 6=Sat
  const mins = et.getUTCHours() * 60 + et.getUTCMinutes();

  const dot   = document.getElementById('ms-dot');
  const label = document.getElementById('ms-label');
  if (!dot || !label) return;

  if (day === 0 || day === 6) {
    dot.className = 'ms-dot closed'; label.textContent = 'Market Closed'; return;
  }
  if (mins >= 240 && mins < 570)  { dot.className = 'ms-dot pre';    label.textContent = 'Pre-Market';   return; }
  if (mins >= 570 && mins < 960)  { dot.className = 'ms-dot open';   label.textContent = 'Market Open';  return; }
  if (mins >= 960 && mins < 1200) { dot.className = 'ms-dot after';  label.textContent = 'After-Hours';  return; }
  dot.className = 'ms-dot closed'; label.textContent = 'Market Closed';
}
updateMarketStatus();
setInterval(updateMarketStatus, 60000);

/* ── One-time chart init ──────────────────────────────────── */
function initCharts() {
  const sharedOpts = {
    layout:     { background: { color: BG }, textColor: 'rgba(255,255,255,0.28)' },
    grid:       { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
    crosshair:  {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: 'rgba(255,255,255,0.12)', labelBackgroundColor: '#1a1a1a' },
      horzLine: { color: 'rgba(255,255,255,0.12)', labelBackgroundColor: '#1a1a1a' },
    },
    rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
    timeScale:       { borderColor: 'rgba(255,255,255,0.06)', timeVisible: true, secondsVisible: false },
    handleScroll:    { mouseWheel: true, pressedMouseMove: true },
    handleScale:     { mouseWheel: true, pinch: true },
  };

  lwChart  = LightweightCharts.createChart(document.getElementById('stockChart'),  { ...sharedOpts, height: 400 });
  volChart = LightweightCharts.createChart(document.getElementById('volumeChart'), {
    ...sharedOpts,
    height: 72,
    rightPriceScale: { visible: false },
    leftPriceScale:  { visible: false },
    timeScale:       { visible: false },
    crosshair:       { vertLine: { labelVisible: false }, horzLine: { visible: false } },
  });

  // Sync scroll/zoom between main and volume chart (logical range — same bar count)
  lwChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
    if (chartSyncing || !r) return;
    chartSyncing = true;
    volChart.timeScale().setVisibleLogicalRange(r);
    chartSyncing = false;
    if (r.from < 10) loadMoreBars();
  });
  volChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
    if (chartSyncing || !r) return;
    chartSyncing = true;
    lwChart.timeScale().setVisibleLogicalRange(r);
    chartSyncing = false;
  });

  setupTooltip();
  setupBaselineDrag();
}

/* ── Build / replace series on every data load ────────────── */
function buildSeries(bars, ct) {
  if (!lwChart) return;

  // Reset load-more state whenever we do a full fresh load
  noMoreHistory = false;
  earliestTime  = bars.length ? bars[0].time : null;

  // Remove old main series
  if (mainSeries) {
    try { lwChart.removeSeries(mainSeries); } catch(e) {}
    mainSeries = null;
  }
  // Remove and recreate vol series to avoid stale state
  if (volSeries) {
    try { volChart.removeSeries(volSeries); } catch(e) {}
    volSeries = null;
  }

  baselinePrice = null;
  document.getElementById('baseline-hint').style.display = 'none';

  const isUp = bars.length > 1 && bars[bars.length - 1].close >= bars[0].close;

  /* — Main series — */
  if (ct === 'candle') {
    mainSeries = lwChart.addCandlestickSeries({
      upColor: UP, downColor: DOWN,
      borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN,
    });
    mainSeries.setData(bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

  } else if (ct === 'mountain') {
    const col = isUp ? LINE : DOWN;
    mainSeries = lwChart.addAreaSeries({ lineColor: col, topColor: col + '30', bottomColor: col + '00', lineWidth: 2 });
    mainSeries.setData(bars.map(b => ({ time: b.time, value: b.close })));

  } else if (ct === 'baseline') {
    baselinePrice = bars[Math.floor(bars.length / 2)]?.close || bars[0]?.close;
    mainSeries = lwChart.addBaselineSeries({
      baseValue:       { type: 'price', price: baselinePrice },
      topLineColor:    UP,   topFillColor1: UP   + '28', topFillColor2: UP   + '05',
      bottomLineColor: DOWN, bottomFillColor1: DOWN + '05', bottomFillColor2: DOWN + '28',
      lineWidth: 2,
    });
    mainSeries.setData(bars.map(b => ({ time: b.time, value: b.close })));
    baselineGuide = null;
    setBaselineAt(baselinePrice);
    document.getElementById('baseline-hint').style.display = 'block';

  } else {
    const col = isUp ? LINE : DOWN;
    mainSeries = lwChart.addLineSeries({ color: col, lineWidth: 2, crosshairMarkerBackgroundColor: col });
    mainSeries.setData(bars.map(b => ({ time: b.time, value: b.close })));
  }

  /* — Volume series (recreated fresh each time) — */
  volSeries = volChart.addHistogramSeries({
    priceFormat:  { type: 'volume' },
    scaleMargins: { top: 0.1, bottom: 0 },
    lastValueVisible: false,
    priceLineVisible: false,
  });
  volSeries.setData(bars.map(b => ({
    time:  b.time,
    value: b.volume,
    color: b.close >= b.open ? UP + '60' : DOWN + '60',
  })));

  lwChart.timeScale().fitContent();
  volChart.timeScale().fitContent();
  if (rsiChart) rsiChart.timeScale().fitContent();
}

/* ── Lightweight update of series data (no series recreation) */
function setSeriesData(bars) {
  if (!mainSeries || !volSeries) return;
  const ct = currentCt;
  if (ct === 'candle') {
    mainSeries.setData(bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
  } else {
    mainSeries.setData(bars.map(b => ({ time: b.time, value: b.close })));
  }
  volSeries.setData(bars.map(b => ({
    time:  b.time,
    value: b.volume,
    color: b.close >= b.open ? UP + '60' : DOWN + '60',
  })));
}

/* ── Load older bars when user scrolls to the left edge ───── */
async function loadMoreBars() {
  if (isFetchingMore || noMoreHistory || !earliestTime) return;
  isFetchingMore = true;

  // Convert earliestTime (UNIX s) to ISO for the before= param
  const beforeISO = new Date(earliestTime * 1000).toISOString().replace('.000Z', 'Z');

  try {
    const resp = await fetch(`/api/stock/${SYMBOL}/?tf=${currentTf}&before=${beforeISO}`);
    const data = await resp.json();
    if (data.error || !data.bars?.length) { noMoreHistory = true; return; }

    // Parse bars same way as loadStock
    const newBars = data.bars.map(b => ({
      time:   Math.floor(new Date(b.t).getTime() / 1000),
      open:   b.o  ?? b.open  ?? b.c ?? b.close,
      high:   b.h  ?? b.high  ?? b.c ?? b.close,
      low:    b.l  ?? b.low   ?? b.c ?? b.close,
      close:  b.c  ?? b.close,
      volume: b.v  ?? b.volume ?? 0,
    }))
    .filter(b => b.time < earliestTime)  // only bars older than what we have
    .sort((a, b) => a.time - b.time);

    if (!newBars.length) { noMoreHistory = true; return; }

    // Remember how many new bars we're prepending so we can shift the viewport
    const addedCount = newBars.length;

    // Save current visible logical range
    const prevRange = lwChart.timeScale().getVisibleLogicalRange();

    // Merge and sort
    allBars = [...newBars, ...allBars];
    earliestTime = allBars[0].time;

    if (!data.has_more) noMoreHistory = true;

    // Push data to series without recreating them
    setSeriesData(allBars);
    renderIndicators(allBars);

    // Restore the viewport shifted right by the number of prepended bars
    // so the user's current view position doesn't jump
    if (prevRange) {
      lwChart.timeScale().setVisibleLogicalRange({
        from: prevRange.from + addedCount,
        to:   prevRange.to  + addedCount,
      });
      volChart.timeScale().setVisibleLogicalRange({
        from: prevRange.from + addedCount,
        to:   prevRange.to  + addedCount,
      });
      // RSI syncs via time range subscriber automatically
    }

  } catch(e) {
    console.error('loadMoreBars error:', e);
  } finally {
    isFetchingMore = false;
  }
}

/* ── Move baseline fill + dashed line to a new price ─────── */
function setBaselineAt(price) {
  if (!mainSeries) return;
  // Update the fill split
  mainSeries.applyOptions({ baseValue: { type: 'price', price } });
  // Remove old guide line and create a new one at the new price
  if (baselineGuide) {
    try { mainSeries.removePriceLine(baselineGuide); } catch(e) {}
  }
  baselineGuide = mainSeries.createPriceLine({
    price,
    color: 'rgba(255,255,255,0.4)',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
    title: 'baseline',
  });
  baselinePrice = price;
}

/* ── Baseline drag via mouse events ──────────────────────── */
function setupBaselineDrag() {
  const el = document.getElementById('stockChart');

  el.addEventListener('mousedown', e => {
    if (currentCt !== 'baseline' || !mainSeries || baselinePrice === null) return;
    const rect   = el.getBoundingClientRect();
    const mouseY = e.clientY - rect.top;
    const blY    = mainSeries.priceToCoordinate(baselinePrice);
    if (blY === null) return;
    if (Math.abs(mouseY - blY) < 12) {
      isDraggingBL = true;
      lwChart.applyOptions({ handleScroll: false, handleScale: false });
      el.style.cursor = 'ns-resize';
      e.preventDefault();
    }
  });

  window.addEventListener('mousemove', e => {
    if (!isDraggingBL || !mainSeries) return;
    const rect   = document.getElementById('stockChart').getBoundingClientRect();
    const mouseY = e.clientY - rect.top;
    const newPrice = mainSeries.coordinateToPrice(mouseY);
    if (newPrice === null) return;
    setBaselineAt(newPrice);
  });

  window.addEventListener('mouseup', () => {
    if (!isDraggingBL) return;
    isDraggingBL = false;
    lwChart.applyOptions({ handleScroll: true, handleScale: true });
    document.getElementById('stockChart').style.cursor = 'default';
  });

  // Cursor hint when hovering near baseline
  el.addEventListener('mousemove', e => {
    if (currentCt !== 'baseline' || !mainSeries || baselinePrice === null || isDraggingBL) return;
    const rect   = el.getBoundingClientRect();
    const mouseY = e.clientY - rect.top;
    const blY    = mainSeries.priceToCoordinate(baselinePrice);
    if (blY !== null && Math.abs(mouseY - blY) < 12) {
      el.style.cursor = 'ns-resize';
    } else {
      el.style.cursor = 'default';
    }
  });
}

/* ── OHLCV Tooltip ────────────────────────────────────────── */
function setupTooltip() {
  const tt = document.getElementById('chart-tooltip');

  lwChart.subscribeCrosshairMove(param => {
    if (!param.time || !param.seriesData?.size) { tt.style.display = 'none'; return; }

    let bar = null;
    for (const [, v] of param.seriesData) { bar = v; break; }
    if (!bar) { tt.style.display = 'none'; return; }

    // Find full OHLCV from our allBars cache
    const full = allBars.find(b => b.time === param.time) || bar;
    const isUp = (full.close ?? full.value) >= (full.open ?? full.value);
    const close = full.close ?? full.value;
    const open  = full.open  ?? close;
    const high  = full.high  ?? close;
    const low   = full.low   ?? close;
    const vol   = full.volume ?? 0;

    document.getElementById('ct-date').textContent = new Date(param.time * 1000)
      .toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    document.getElementById('ct-o').textContent = '$' + open.toFixed(2);
    document.getElementById('ct-h').textContent = '$' + high.toFixed(2);
    document.getElementById('ct-l').textContent = '$' + low.toFixed(2);
    document.getElementById('ct-c').textContent = '$' + close.toFixed(2);
    document.getElementById('ct-c').style.color  = isUp ? UP : DOWN;
    document.getElementById('ct-v').textContent = fmtVol(vol);
    tt.style.display = 'block';
  });
}

function fmtVol(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return String(v);
}

/* ── Chart type switcher ──────────────────────────────────── */
document.getElementById('chart-type-bar').addEventListener('click', e => {
  const btn = e.target.closest('.ct-btn');
  if (!btn) return;
  document.querySelectorAll('.ct-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentCt = btn.dataset.ct;
  if (allBars.length) {
    buildSeries(allBars, currentCt);
    renderIndicators(allBars);
  }
});

/* ── renderChart called from loadStock ────────────────────── */
function renderChart(bars) {
  allBars = bars;
  if (!lwChart) initCharts();
  buildSeries(bars, currentCt);
  renderIndicators(bars);
}

/* ─── LOAD STOCK DATA ─────────────────────────────────────── */
async function loadStock(symbol, tf) {
  const loading = document.getElementById('chart-loading');
  loading.classList.add('visible');
  // Reset infinite scroll state for fresh load
  isFetchingMore = false;
  noMoreHistory  = false;

  try {
    const resp = await fetch(`/api/stock/${symbol}/?tf=${tf}`);
    const data = await resp.json();
    if (data.error || !data.bars?.length) throw new Error(data.error || 'No data');

    const bars = data.bars;

    // Build full OHLCV objects; Alpaca may use b.o/b.h/b.l/b.c/b.v or b.open/b.high etc.
    const lwBars = bars.map(b => ({
      time:   Math.floor(new Date(b.t).getTime() / 1000),
      open:   b.o  ?? b.open  ?? b.c ?? b.close,
      high:   b.h  ?? b.high  ?? b.c ?? b.close,
      low:    b.l  ?? b.low   ?? b.c ?? b.close,
      close:  b.c  ?? b.close,
      volume: b.v  ?? b.volume ?? 0,
    })).sort((a, b) => a.time - b.time);

    latestPrice = lwBars[lwBars.length - 1].close;
    const prev  = lwBars[0].close;
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

    renderChart(lwBars);
    updateEstimate();
    updatePositionBox();

  } catch(e) {
    document.getElementById('chart-price').textContent  = 'Unavailable';
    document.getElementById('chart-change').textContent = 'Could not load data';
    console.error('loadStock error:', e);
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

/* ═══════════════════════════════════════════════════════════
   TECHNICAL INDICATORS
   ═══════════════════════════════════════════════════════════ */

/* ── Compute helpers ──────────────────────────────────────── */
function calcSMA(bars, period) {
  return bars.map((b, i) => {
    if (i < period - 1) return null;
    const sum = bars.slice(i - period + 1, i + 1).reduce((a, x) => a + x.close, 0);
    return { time: b.time, value: sum / period };
  }).filter(Boolean);
}

function calcEMA(bars, period) {
  const k = 2 / (period + 1);
  const result = [];
  let ema = null;
  for (const b of bars) {
    if (ema === null) { ema = b.close; }
    else              { ema = b.close * k + ema * (1 - k); }
    result.push({ time: b.time, value: ema });
  }
  // Skip the warmup period to avoid noisy start
  return result.slice(period);
}

function calcBB(bars, period = 20, mult = 2) {
  const upper = [], mid = [], lower = [];
  for (let i = period - 1; i < bars.length; i++) {
    const slice = bars.slice(i - period + 1, i + 1).map(b => b.close);
    const mean  = slice.reduce((a, v) => a + v, 0) / period;
    const std   = Math.sqrt(slice.reduce((a, v) => a + (v - mean) ** 2, 0) / period);
    upper.push({ time: bars[i].time, value: mean + mult * std });
    mid.push(  { time: bars[i].time, value: mean });
    lower.push({ time: bars[i].time, value: mean - mult * std });
  }
  return { upper, mid, lower };
}

function calcRSI(bars, period = 14) {
  const result = [];
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d > 0) avgGain += d; else avgLoss += -d;
  }
  avgGain /= period; avgLoss /= period;
  for (let i = period; i < bars.length; i++) {
    if (i > period) {
      const d = bars[i].close - bars[i - 1].close;
      avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
      avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    }
    const rs  = avgLoss === 0 ? 100 : avgGain / avgLoss;
    const rsi = 100 - 100 / (1 + rs);
    result.push({ time: bars[i].time, value: rsi });
  }
  // Pad the front with the earliest valid value so bar count matches main chart
  // This lets logical-range sync work perfectly (same indices as main + vol)
  while (result.length < bars.length) {
    result.unshift({ time: bars[result.length > 0 ? bars.length - result.length - 1 : 0].time, value: result[0]?.value ?? 50 });
  }
  return result;
}

/* ── Remove all indicator series ─────────────────────────── */
function clearIndicators() {
  for (const key of Object.keys(indSeries)) {
    if (indSeries[key]) {
      try { lwChart.removeSeries(indSeries[key]); } catch(e) {}
      indSeries[key] = null;
    }
  }
  if (rsiSeries && rsiChart) {
    try { rsiChart.removeSeries(rsiSeries); } catch(e) {}
    rsiSeries = null;
  }
}

/* ── Render indicators based on checkbox state ────────────── */
function renderIndicators(bars) {
  if (!lwChart || !bars.length) return;
  clearIndicators();

  const sma20On = document.getElementById('ind-sma20')?.checked;
  const sma50On = document.getElementById('ind-sma50')?.checked;
  const ema20On = document.getElementById('ind-ema20')?.checked;
  const bbOn    = document.getElementById('ind-bb')?.checked;
  const rsiOn   = document.getElementById('ind-rsi')?.checked;

  if (sma20On) {
    indSeries.sma20 = lwChart.addLineSeries({
      color: '#f59e0b', lineWidth: 1, crosshairMarkerVisible: false,
      lastValueVisible: true, priceLineVisible: false,
      title: 'SMA20',
    });
    indSeries.sma20.setData(calcSMA(bars, 20));
  }

  if (sma50On) {
    indSeries.sma50 = lwChart.addLineSeries({
      color: '#a78bfa', lineWidth: 1, crosshairMarkerVisible: false,
      lastValueVisible: true, priceLineVisible: false,
      title: 'SMA50',
    });
    indSeries.sma50.setData(calcSMA(bars, 50));
  }

  if (ema20On) {
    indSeries.ema20 = lwChart.addLineSeries({
      color: '#38bdf8', lineWidth: 1, crosshairMarkerVisible: false,
      lastValueVisible: true, priceLineVisible: false,
      title: 'EMA20',
    });
    indSeries.ema20.setData(calcEMA(bars, 20));
  }

  if (bbOn) {
    const { upper, mid, lower } = calcBB(bars);
    const bbColor = 'rgba(232, 121, 249, 0.85)';
    indSeries.bbUpper = lwChart.addLineSeries({
      color: bbColor, lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,
      crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
      title: 'BB+',
    });
    indSeries.bbMid = lwChart.addLineSeries({
      color: 'rgba(232, 121, 249, 0.3)', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted,
      crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
      title: 'BBmid',
    });
    indSeries.bbLower = lwChart.addLineSeries({
      color: bbColor, lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,
      crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
      title: 'BB−',
    });
    indSeries.bbUpper.setData(upper);
    indSeries.bbMid.setData(mid);
    indSeries.bbLower.setData(lower);
  }

  // RSI in its own pane — synced via logical range same as volChart
  const rsiEl = document.getElementById('rsiChart');
  if (rsiOn) {
    rsiEl.style.display = 'block';
    if (!rsiChart) {
      rsiChart = LightweightCharts.createChart(rsiEl, {
        layout:     { background: { color: BG }, textColor: 'rgba(255,255,255,0.28)' },
        grid:       { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
        crosshair:  { vertLine: { labelVisible: false }, horzLine: { visible: false } },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)', scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale:  { visible: false },
        handleScroll: { mouseWheel: false, pressedMouseMove: false },
        handleScale:  { mouseWheel: false, pinch: false },
      });
      rsiChart.resize(rsiEl.clientWidth, 100);

      // Mirror volChart exactly — logical range
      lwChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
        if (chartSyncing || !r || !rsiChart) return;
        rsiChart.timeScale().setVisibleLogicalRange(r);
      });
    }

    rsiSeries = rsiChart.addLineSeries({
      color: '#f97316', lineWidth: 1.5,
      crosshairMarkerVisible: false,
      lastValueVisible: true,
      priceLineVisible: false,
      autoscaleInfoProvider: (original) => {
        const res = original();
        const minV = Math.min(res?.priceRange?.minValue ?? 30, 20);
        const maxV = Math.max(res?.priceRange?.maxValue ?? 70, 80);
        return { priceRange: { minValue: minV, maxValue: maxV } };
      },
      title: 'RSI14',
    });

    rsiSeries.createPriceLine({ price: 70, color: 'rgba(239,83,80,0.55)',  lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true,  title: '70' });
    rsiSeries.createPriceLine({ price: 30, color: 'rgba(38,166,154,0.55)', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true,  title: '30' });
    rsiSeries.createPriceLine({ price: 50, color: 'rgba(255,255,255,0.1)', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });

    rsiSeries.setData(calcRSI(bars));

  } else {
    rsiEl.style.display = 'none';
    if (rsiChart) { rsiChart.remove(); rsiChart = null; }
  }
}

/* ── Wire up checkboxes ───────────────────────────────────── */
['ind-sma20','ind-sma50','ind-ema20','ind-bb','ind-rsi'].forEach(id => {
  document.getElementById(id)?.addEventListener('change', () => {
    if (allBars.length) renderIndicators(allBars);
  });
});

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