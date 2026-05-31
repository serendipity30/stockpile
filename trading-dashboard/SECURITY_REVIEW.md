# Security review — Trading Dashboard

Reviewed: 2026-05-31. Scope: the "Trading Dashboard" subproject (Flask
backend + vanilla-JS frontend serving public market data from Yahoo
Finance / Hyperliquid).

**Verdict: No HIGH or MEDIUM-confidence exploitable vulnerabilities
found.**

## What was checked and cleared

| Area | Finding |
|------|---------|
| `app.py` debug mode | `app.run(debug=False, …)` — debugger not exposed. ✅ |
| SSRF | No proxy / fetch-by-URL endpoint. `symbol` only flows into a path/query against fixed hosts (Yahoo, `api.hyperliquid.xyz`) — no host/protocol control. ✅ |
| Injection (Python) | No `eval`/`exec`/`pickle`/`yaml.load`/`subprocess`/`os.system`/`render_template_string`. `symbol` goes to `yf.Ticker()` and a JSON POST body, not a shell/SQL. ✅ |
| Secrets | None hardcoded. ✅ |
| DOM XSS | All `innerHTML` sinks in `indicators-render.js` interpolate numeric values (`.toFixed()`) or static strings. ✅ |

## Low-severity / informational (address later, not blocking)

### 1. Unescaped symbol in `innerHTML` — self-XSS only

`dashboard.js:181` and `:276` interpolate `ps.symbol` / `err.message`
(which embeds the symbol) into `innerHTML`. The symbol is the user's own
typed input — there is no attacker delivery path (no URL param, no
server-side persistence, no share/import), and it is `.toUpperCase()`'d
which breaks JS payloads. So it is self-XSS, not a real vuln.

Cheap to harden: build those nodes with `textContent` instead of
`innerHTML`.

### 2. Wildcard CORS

`CORS(app, resources={r"/api/*": {"origins": "*"}})` (`app.py:6`).
Acceptable here: the API is unauthenticated, cookie-less, and read-only
public data, so cross-origin reads expose nothing sensitive. Worth
tightening only if auth or private data is ever added.

## Bottom line

Safe to merge from a security standpoint. The two items above are
optional hardening, not gating issues.
