// dashboard.js — state management, pane rendering, live data, bootstrap
// Depends on: indicators.js, indicators-render.js, LightweightCharts global

const STORAGE_KEY = 'td-v12';
const MAX_PANES = 8;
const TFS = ['1m','3m','5m','15m','30m','1h','4h','1d','1w','1M'];
const SRC_LABELS = { hyperliquid: 'Hyperliquid (Crypto)', yfinance: 'Yahoo Finance', schwab: 'Schwab' };
const SOURCES = Object.keys(SRC_LABELS);

let CATALOG = { hyperliquid: ['ETH'], yfinance: ['AVGO'], schwab: ['AAPL'] };

// Source new panes start on. User-overridable via the "New panes:" dropdown
// and persisted; panes whose source/symbol the user has set are left alone.
const DEFAULT_SOURCE = 'yfinance';

const IND_SECTIONS = [
  { title: 'Moving Averages', items: [
    { id: 'sma20', label: 'SMA (20)', overlay: true },
    { id: 'sma50', label: 'SMA (50)', overlay: true },
    { id: 'sma200', label: 'SMA (200)', overlay: true },
    { id: 'ema20', label: 'EMA (20)', overlay: true },
    { id: 'ema50', label: 'EMA (50)', overlay: true },
    { id: 'ema200', label: 'EMA (200)', overlay: true },
    { id: 'vwap', label: 'VWAP', overlay: true },
  ]},
  { title: 'Bands & Channels', items: [
    { id: 'bb', label: 'Bollinger (20,2)', overlay: true },
    { id: 'donchian', label: 'Donchian (20)', overlay: true },
    { id: 'keltner', label: 'Keltner (20,1.5)', overlay: true },
  ]},
  { title: 'Trend', items: [
    { id: 'psar', label: 'Parabolic SAR', overlay: true },
    { id: 'supertrend', label: 'Supertrend (10,3)', overlay: true },
    { id: 'ichimoku', label: 'Ichimoku Cloud', overlay: true },
    { id: 'pivot', label: 'Pivot Points', overlay: true },
  ]},
  { title: 'Price Action', items: [
    { id: 'fvg', label: 'Fair Value Gaps', overlay: true, canvas: true },
    { id: 'vpvr', label: 'Volume Profile (POC/VA)', overlay: true, canvas: true },
    { id: 'frvp', label: 'Fixed Range Vol Profile', overlay: true, canvas: true },
  ]},
  { title: 'Volume', items: [
    { id: 'volume', label: 'Volume', overlay: false },
    { id: 'obv', label: 'OBV', overlay: false },
    { id: 'mfi', label: 'MFI (14)', overlay: false },
  ]},
  { title: 'Oscillators', items: [
    { id: 'rsi', label: 'RSI (14)', overlay: false },
    { id: 'macd', label: 'MACD (12,26,9)', overlay: false },
    { id: 'stoch', label: 'Stochastic (14,3,3)', overlay: false },
    { id: 'cci', label: 'CCI (20)', overlay: false },
    { id: 'williams', label: 'Williams %R (14)', overlay: false },
    { id: 'atr', label: 'ATR (14)', overlay: false },
    { id: 'adx', label: 'ADX (14)', overlay: false },
  ]},
];

// ── State ─────────────────────────────────────────────────────────────────────

function defaultPanes(src = DEFAULT_SOURCE) {
  const cat = CATALOG[src] || [''];
  return Array.from({ length: MAX_PANES }, (_, i) => ({
    id: i,
    source: src,
    symbol: cat[i % cat.length] || '',
    timeframe: '1d',
    indicators: {},
    frvpRange: null,
    customized: false,
  }));
}

let _initDebounceTimers = {};
const state = {
  chartCount: 1, defaultSource: DEFAULT_SOURCE, panes: defaultPanes(),
  charts: new Map(), sockets: new Map(), pollers: new Map(), ros: new Map(),
};

function loadState() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch {}
  state.defaultSource = (saved && saved.defaultSource) || DEFAULT_SOURCE;
  const panes = defaultPanes(state.defaultSource);
  if (saved && Array.isArray(saved.panes)) {
    saved.panes.forEach(sp => {
      if (sp && typeof sp.id === 'number' && panes[sp.id]) {
        panes[sp.id] = {
          ...panes[sp.id],
          source: sp.source || panes[sp.id].source,
          symbol: sp.symbol || panes[sp.id].symbol,
          timeframe: sp.timeframe || panes[sp.id].timeframe,
          indicators: sp.indicators || {},
          frvpRange: sp.frvpRange || null,
          customized: !!sp.customized,
        };
      }
    });
  }
  state.panes = panes;
  state.chartCount = (saved && saved.chartCount) || 1;
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    chartCount: state.chartCount,
    defaultSource: state.defaultSource,
    panes: state.panes.map(({ id, source, symbol, timeframe, indicators, frvpRange, customized }) =>
      ({ id, source, symbol, timeframe, indicators, frvpRange: frvpRange || null, customized: !!customized })),
  }));
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const fmt = n => !Number.isFinite(n) ? '--' : n >= 1000
  ? n.toLocaleString(undefined, { maximumFractionDigits: 2 })
  : n.toLocaleString(undefined, { maximumFractionDigits: 4 });

const tfSec = tf => ({ '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800, '1M': 2592000 }[tf] || 900);

function mkSel(opts, val, isSource = false) {
  const s = document.createElement('select');
  opts.forEach(o => {
    const e = document.createElement('option');
    e.value = o; e.textContent = isSource ? (SRC_LABELS[o] || o) : o;
    if (o === val) e.selected = true;
    s.appendChild(e);
  });
  return s;
}

function lwcOpts() {
  return {
    layout: { background: { type: 'solid', color: '#12192a' }, textColor: '#9aa8c7' },
    grid: { vertLines: { color: 'rgba(255,255,255,.03)' }, horzLines: { color: 'rgba(255,255,255,.04)' } },
    rightPriceScale: { borderColor: '#283348' },
    timeScale: { borderColor: '#283348', timeVisible: true, secondsVisible: false },
    crosshair: { mode: 1 },
    watermark: { visible: false },
  };
}

// ── Pane Lifecycle ────────────────────────────────────────────────────────────

function destroyPane(id) {
  const ws = state.sockets.get(id);
  if (ws) { try { ws.close(); } catch {} state.sockets.delete(id); }
  const p = state.pollers.get(id);
  if (p) { clearInterval(p); state.pollers.delete(id); }
  const ro = state.ros.get(id);
  if (ro) { try { ro.disconnect(); } catch {} state.ros.delete(id); }
  const inst = state.charts.get(id);
  if (inst) {
    if (inst.syncFns) {
      inst.syncFns.forEach(({ chart: sc, rangeFn, crossFn }) => {
        try { inst.chart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeFn); } catch {}
        try { inst.chart.unsubscribeCrosshairMove(crossFn); } catch {}
        try { sc.remove(); } catch {}
      });
    }
    try { inst.chart.remove(); } catch {}
    state.charts.delete(id);
  }
}

function updateTicker(id, symbol, price, changePct, dir) {
  const pane = document.querySelector(`.pane[data-id="${id}"]`);
  if (!pane) return;
  pane.querySelector('.chip').textContent = symbol;
  pane.querySelector('.price').textContent = fmt(price);
  const d = pane.querySelector('.delta');
  const sign = changePct >= 0 ? '+' : '';
  d.textContent = Number.isFinite(changePct) ? `${sign}${changePct.toFixed(2)}%` : '--';
  d.className = `delta ${dir > 0 ? 'up' : dir < 0 ? 'down' : 'flat'}`;
  const t = pane.querySelector('.ticker-inline');
  t.classList.remove('flash-up', 'flash-down');
  void t.offsetWidth;
  if (dir > 0) t.classList.add('flash-up');
  if (dir < 0) t.classList.add('flash-down');
}

// ── Dashboard Rendering ───────────────────────────────────────────────────────

function renderDashboard() {
  const dash = document.getElementById('dashboard');
  dash.className = `grid layout-${state.chartCount}`;
  dash.innerHTML = '';
  for (let i = 0; i < state.chartCount; i++) {
    const ps = state.panes[i];
    const pane = document.createElement('section');
    pane.className = 'pane loading';
    pane.dataset.id = ps.id;

    // Header controls
    const srcSel = mkSel(SOURCES, ps.source, true);
    try { srcSel.value = ps.source; } catch {}
    const custIn = document.createElement('input');
    custIn.type = 'text'; custIn.className = 'csym';
    custIn.placeholder = 'Symbol'; custIn.value = ps.symbol;
    const tfSel = mkSel(TFS, ps.timeframe);
    const indBtn = document.createElement('button');
    indBtn.className = 'ind-btn'; indBtn.textContent = '⚙ Indicators';
    const tickerInline = document.createElement('div');
    tickerInline.className = 'ticker-inline';
    const _chip = document.createElement('span'); _chip.className = 'chip'; _chip.textContent = ps.symbol;
    const _price = document.createElement('span'); _price.className = 'price'; _price.textContent = '--';
    const _delta = document.createElement('span'); _delta.className = 'delta flat'; _delta.textContent = '--%';
    tickerInline.append(_chip, _price, _delta);

    const controls = document.createElement('div');
    controls.className = 'controls';
    controls.append(srcSel, custIn, tfSel, indBtn, tickerInline);
    const paneNum = document.createElement('div');
    paneNum.className = 'pane-num'; paneNum.textContent = `Pane ${i + 1}`;
    const hdr = document.createElement('div');
    hdr.className = 'pane-hdr';
    hdr.append(controls, paneNum);

    // Body
    const drawer = document.createElement('div'); drawer.className = 'drawer';
    const chartWrap = document.createElement('div'); chartWrap.className = 'chart-wrap';
    const loader = document.createElement('div'); loader.className = 'loader';
    loader.innerHTML = '<div class="spinner"></div><span>Loading…</span>';
    const chartEl = document.createElement('div'); chartEl.className = 'chart-el';
    chartWrap.append(loader, chartEl);
    const subPanels = document.createElement('div'); subPanels.className = 'sub-panels';
    const chartCol = document.createElement('div'); chartCol.className = 'chart-col';
    chartCol.append(chartWrap, subPanels);
    const body = document.createElement('div'); body.className = 'pane-body';
    body.append(drawer, chartCol);

    pane.append(hdr, body);
    dash.appendChild(pane);

    // Events
    srcSel.addEventListener('change', () => {
      const prevSource = ps.source;
      ps.source = srcSel.value;
      // Keep the current symbol when switching between equity sources
      // (Yahoo <-> Schwab share tickers). Only fall back to the catalog
      // default across the crypto/stock boundary, where symbols differ,
      // or when no symbol is set yet.
      const crossesCrypto =
        (prevSource === 'hyperliquid') !== (ps.source === 'hyperliquid');
      if (crossesCrypto || !ps.symbol) {
        ps.symbol = (CATALOG[ps.source] || [])[0] || '';
      }
      ps.customized = true;
      saveState(); renderDashboard(); initAll();
    });
    const applyCustom = () => {
      const v = custIn.value.trim().toUpperCase();
      if (!v || v === ps.symbol) return;
      ps.symbol = v; ps.customized = true; saveState(); debouncedInitPane(ps.id);
    };
    custIn.addEventListener('change', applyCustom);
    custIn.addEventListener('keydown', e => { if (e.key === 'Enter') applyCustom(); });
    tfSel.addEventListener('change', () => { ps.timeframe = tfSel.value; saveState(); debouncedInitPane(ps.id); });
    indBtn.addEventListener('click', e => { e.stopPropagation(); renderDrawer(ps.id, ps); drawer.classList.toggle('open'); });
    chartCol.addEventListener('click', () => drawer.classList.remove('open'));
  }
}

// ── Pane Init ─────────────────────────────────────────────────────────────────

async function initPane(paneId) {
  const ps = state.panes.find(p => p.id === paneId);
  const pane = document.querySelector(`.pane[data-id="${paneId}"]`);
  if (!ps || !pane) return;
  destroyPane(paneId);
  pane.classList.add('loading');
  const loaderEl = pane.querySelector('.loader');
  loaderEl.innerHTML = '<div class="spinner"></div><span>Loading…</span>';
  const chartEl = pane.querySelector('.chart-el');
  const chartWrap = pane.querySelector('.chart-wrap');
  let chart, series;
  try {
    if (!window.LightweightCharts) throw new Error('Chart library not loaded');
    const w = Math.max(320, chartWrap.clientWidth || 400);
    const h = Math.max(280, chartWrap.clientHeight || 300);
    chart = LightweightCharts.createChart(chartEl, { ...lwcOpts(), width: w, height: h });
    series = chart.addCandlestickSeries({
      upColor: '#16c784', downColor: '#ea3943',
      borderUpColor: '#16c784', borderDownColor: '#ea3943',
      wickUpColor: '#16c784', wickDownColor: '#ea3943',
    });
    const ro = new ResizeObserver(() => {
      try { chart.resize(Math.max(320, chartWrap.clientWidth || 400), Math.max(280, chartWrap.clientHeight || 300)); } catch {}
    });
    ro.observe(chartWrap);
    state.ros.set(paneId, ro);

    const url = `/api/ohlcv?source=${encodeURIComponent(ps.source)}&symbol=${encodeURIComponent(ps.symbol)}&interval=${encodeURIComponent(ps.timeframe)}&limit=300`;
    const res = await fetch(url, { cache: 'no-store' });
    const body = await res.json();
    if (!body.ok) throw new Error(body.error || 'API error');
    if (!body.data || !body.data.length) throw new Error(`No data for ${ps.symbol}`);
    const candles = body.data
      .filter(b => b && isFinite(b.time) && isFinite(b.open) && isFinite(b.high) && isFinite(b.low) && isFinite(b.close))
      .map(b => ({ time: Number(b.time), open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close), volume: Number(b.volume || 0) }));
    if (!candles.length) throw new Error(`No valid candles for ${ps.symbol}`);
    series.setData(candles);
    chart.timeScale().fitContent();
    const last = candles[candles.length - 1], prev = candles[candles.length - 2] || last;
    const dir = Math.sign(last.close - prev.close);
    const chp = prev.close ? ((last.close - prev.close) / prev.close) * 100 : 0;
    updateTicker(paneId, ps.symbol, last.close, chp, dir);
    state.charts.set(paneId, { chart, series, candles, lastBar: last, lastPrice: last.close, prevClose: prev.close, indSeries: [] });
    renderIndicators(paneId);
    wireLive(paneId);
  } catch (err) {
    console.error(`[Pane ${paneId}]`, err);
    const _err = document.createElement('span');
    _err.style.color = 'var(--red)';
    _err.textContent = `⚠ ${err.message}`;
    loaderEl.replaceChildren(_err);
    const d = pane.querySelector('.delta');
    if (d) { d.textContent = 'Error'; d.className = 'delta down'; }
  } finally {
    pane.classList.remove('loading');
  }
}

// ── Live Data ─────────────────────────────────────────────────────────────────

function wireLive(paneId) {
  const ps = state.panes.find(p => p.id === paneId);
  const inst = state.charts.get(paneId);
  if (!ps || !inst) return;

  if (ps.source === 'hyperliquid') {
    const coin = ps.symbol.toUpperCase().replace('-PERP', '').replace('/USDT', '').replace('USDT', '').trim();
    const ws = new WebSocket('wss://api.hyperliquid.xyz/ws');
    ws.onopen = () => ws.send(JSON.stringify({ method: 'subscribe', subscription: { type: 'trades', coin } }));
    ws.onmessage = evt => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg?.channel !== 'trades' || !msg.data?.length) return;
        const price = Number(msg.data[msg.data.length - 1].px);
        if (!Number.isFinite(price)) return;
        const now = Math.floor(Date.now() / 1000);
        const bucket = Math.floor(now / tfSec(ps.timeframe)) * tfSec(ps.timeframe);
        let lb = inst.lastBar;
        if (!lb || bucket > lb.time) lb = { time: bucket, open: inst.lastPrice ?? price, high: price, low: price, close: price, volume: 0 };
        else lb = { ...lb, high: Math.max(lb.high, price), low: Math.min(lb.low, price), close: price };
        inst.lastBar = lb;
        try { inst.series.update(lb); } catch {}
        const dir = Math.sign(price - (inst.lastPrice ?? inst.prevClose ?? price));
        const chp = inst.prevClose ? ((price - inst.prevClose) / inst.prevClose) * 100 : 0;
        inst.lastPrice = price;
        updateTicker(paneId, ps.symbol, price, chp, dir);
      } catch {}
    };
    ws.onerror = e => console.warn('[WS]', paneId, e);
    state.sockets.set(paneId, ws);
  } else {
    const pollIntervals = { '1m': 15000, '3m': 15000, '5m': 30000, '15m': 60000, '30m': 120000, '1h': 180000, '4h': 240000, '1d': 300000, '1w': 600000, '1M': 600000 };
    const poll = async () => {
      try {
        const res = await fetch(`/api/price?source=${encodeURIComponent(ps.source)}&symbol=${encodeURIComponent(ps.symbol)}`, { cache: 'no-store' });
        const body = await res.json();
        if (!body.ok) return;
        const price = Number(body.price);
        if (!Number.isFinite(price)) return;
        const dir = Math.sign(price - (inst.lastPrice ?? price));
        inst.lastPrice = price;
        updateTicker(paneId, ps.symbol, price, Number(body.change_pct ?? 0), dir);
      } catch {}
    };
    poll();
    state.pollers.set(paneId, setInterval(poll, pollIntervals[ps.timeframe] || 300000));
  }
}

// ── Orchestration ─────────────────────────────────────────────────────────────

function debouncedInitPane(paneId, delay = 1000) {
  clearTimeout(_initDebounceTimers[paneId]);
  _initDebounceTimers[paneId] = setTimeout(() => initPane(paneId), delay);
}

function initAll() {
  for (let i = 0; i < state.chartCount; i++) initPane(state.panes[i].id);
  for (let i = state.chartCount; i < MAX_PANES; i++) destroyPane(state.panes[i].id);
}

function resetAll() {
  for (let i = 0; i < MAX_PANES; i++) destroyPane(i);
  state.chartCount = 1;
  state.panes = defaultPanes(state.defaultSource);
  document.getElementById('chartCount').value = '1';
  saveState(); renderDashboard(); initAll();
}

function populateDefaultSourceSelect() {
  const sel = document.getElementById('defaultSource');
  if (!sel) return;
  sel.innerHTML = '';
  SOURCES.forEach(o => {
    const e = document.createElement('option');
    e.value = o; e.textContent = SRC_LABELS[o] || o;
    if (o === state.defaultSource) e.selected = true;
    sel.appendChild(e);
  });
}

function applyDefaultSource(src) {
  state.defaultSource = src;
  // Re-seed only panes the user hasn't explicitly set (source/symbol untouched).
  const cat = CATALOG[src] || [''];
  state.panes.forEach((ps, i) => {
    if (!ps.customized) {
      ps.source = src;
      ps.symbol = cat[i % cat.length] || '';
    }
  });
  saveState(); renderDashboard(); initAll();
}

async function bootstrap() {
  try {
    const res = await fetch('/api/sources');
    const body = await res.json();
    if (body?.symbols) {
      if (body.symbols.yfinance) CATALOG.yfinance = body.symbols.yfinance;
      if (body.symbols.hyperliquid) CATALOG.hyperliquid = body.symbols.hyperliquid;
      if (body.symbols.schwab) CATALOG.schwab = body.symbols.schwab;
    }
  } catch {}
  loadState();
  populateDefaultSourceSelect();
  document.getElementById('chartCount').value = String(state.chartCount);
  renderDashboard();
  initAll();
}

// ── Event Listeners ───────────────────────────────────────────────────────────

document.getElementById('chartCount').addEventListener('change', e => {
  state.chartCount = Number(e.target.value);
  saveState(); renderDashboard(); initAll();
});
document.getElementById('defaultSource').addEventListener('change', e => applyDefaultSource(e.target.value));
document.getElementById('resetBtn').addEventListener('click', resetAll);
window.addEventListener('beforeunload', () => { for (let i = 0; i < MAX_PANES; i++) destroyPane(i); });

bootstrap();
