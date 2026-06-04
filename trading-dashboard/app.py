import time, hashlib, tomllib
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from data_source import fetch_ohlcv, fetch_schwab_live_price, _DATASOURCE_REGISTRY
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5000", "http://127.0.0.1:5000"]}})
_CACHE = {}
_CACHE_TTL = {"1m":20,"3m":30,"5m":45,"15m":90,"30m":150,"1h":300,"4h":600,"1d":900,"1w":1800,"1M":3600}
_PRICE_TTL = 300

def _key(source,symbol,interval,limit): return hashlib.md5(f"{source}:{symbol}:{interval}:{limit}".encode()).hexdigest()

# ── Startup layout (config.toml) ──────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"
_VALID_SOURCES = {"yfinance", "schwab", "hyperliquid"}
_VALID_TFS = {"1m","3m","5m","15m","30m","1h","4h","1d","1w","1M"}
_VALID_COUNTS = {1, 2, 4, 6, 8}
_DEFAULT_LAYOUT = {"default_source": "yfinance", "chart_count": 1, "panes": []}

def _load_layout():
    """Read the startup pane layout from config.toml, falling back to a
    safe default when the file is missing or malformed. Read per request
    so edits apply on a browser refresh without a server restart."""
    layout = dict(_DEFAULT_LAYOUT)
    if not _CONFIG_PATH.exists():
        return layout
    try:
        with open(_CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        app.logger.exception("Could not read config.toml; using default layout")
        return layout
    ds = str(cfg.get("default_source", layout["default_source"])).lower()
    if ds in _VALID_SOURCES:
        layout["default_source"] = ds
    cc = cfg.get("chart_count", layout["chart_count"])
    if cc in _VALID_COUNTS:
        layout["chart_count"] = cc
    panes = []
    for p in (cfg.get("pane") or [])[:8]:
        src = str(p.get("source", layout["default_source"])).lower()
        if src not in _VALID_SOURCES:
            src = layout["default_source"]
        tf = str(p.get("timeframe", "1d"))
        if tf not in _VALID_TFS:
            tf = "1d"
        panes.append({"source": src,
                      "symbol": str(p.get("symbol", "")).strip().upper(),
                      "timeframe": tf})
    layout["panes"] = panes
    return layout

def _get(key,ttl):
    e = _CACHE.get(key)
    return e["data"] if e and time.time() - e["ts"] < ttl else None
def _put(key,data): _CACHE[key] = {"ts":time.time(),"data":data}

@app.route('/api/health')
def health(): return jsonify({"status":"ok","sources":list(_DATASOURCE_REGISTRY.keys())})

@app.route('/api/ohlcv')
def ohlcv():
    source = request.args.get('source','yfinance'); symbol = request.args.get('symbol','AVGO'); interval = request.args.get('interval','1d'); limit = int(request.args.get('limit',200))
    ckey = _key(source,symbol,interval,limit); ttl = _CACHE_TTL.get(interval,300); cached = _get(ckey,ttl)
    if cached is not None: return jsonify({"ok":True,"data":cached,"cached":True})
    try:
        candles = fetch_ohlcv(source,symbol,interval,limit); _put(ckey,candles); return jsonify({"ok":True,"data":candles,"cached":False})
    except Exception:
        # Log the real reason server-side; return a curated message that does
        # NOT echo the exception text, so internal details (file paths, SDK
        # errors) never reach the client — CWE-209 / "info exposure". The
        # message is built only from request args + a fixed hint.
        app.logger.exception("ohlcv fetch failed (source=%s symbol=%s interval=%s)", source, symbol, interval)
        msg = f"Could not fetch data for '{symbol}' from '{source}'."
        if source == "schwab":
            msg += " If Schwab isn't set up, see options-scanner/SCHWAB_DATA_SOURCE.md."
        return jsonify({"ok":False,"error":msg}), 400

@app.route('/api/price')
def price():
    source = request.args.get('source','yfinance'); symbol = request.args.get('symbol','AVGO'); ckey = _key(source,symbol,'1d',2); candles = _get(ckey,_PRICE_TTL)
    if candles is None:
        try:
            candles = fetch_ohlcv(source,symbol,'1d',2); _put(ckey,candles)
        except Exception:
            app.logger.exception("price fetch failed (source=%s symbol=%s)", source, symbol)
            return jsonify({"ok":False,"error":f"Could not fetch price for '{symbol}' from '{source}'"}), 400
    if len(candles) >= 2:
        prev, last = candles[-2]['close'], candles[-1]['close']
    elif candles:
        prev = last = candles[0]['close']
    else:
        return jsonify({"ok":False,"error":f"No data for '{symbol}'"}), 404
    # Schwab: overlay the real-time mark so the live number isn't a stale daily close.
    if source == 'schwab':
        try:
            mark = fetch_schwab_live_price(symbol)
            if mark: last = mark
        except Exception:
            app.logger.warning("schwab live price failed (symbol=%s); using daily close", symbol)
    chg = last - prev; chgp = (chg/prev*100) if prev else 0
    return jsonify({"ok":True,"symbol":symbol,"price":last,"change":round(chg,4),"change_pct":round(chgp,2)})

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/sources')
def sources():
    layout = _load_layout()
    return jsonify(
        status='ok',
        symbols={
            'hyperliquid': ['ETH'],
            'yfinance': ['AVGO'],
            'schwab': ['AAPL'],
        },
        default_source=layout['default_source'],
        chart_count=layout['chart_count'],
        panes=layout['panes'],
    )

if __name__ == '__main__': app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
