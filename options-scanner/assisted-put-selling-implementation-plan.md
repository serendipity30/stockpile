# Assisted put-selling — implementation plan

Feature behind the ep9 episode ("the scanner can place a trade"). This
doc is the build/design plan; the YouTube concept lives in the sibling
private repo at
`../stockpile-private/options-scanner/youtube/ep9-place-put-trades/script.md`.

## Hard guardrails (enforce in code, not just UI)

1. **Sell puts only.** Single-leg, sell-to-open, cash-secured puts. No
   buys, no calls, no multi-leg — reject anything else before it can
   reach the order builder, even if the Schwab API would accept it.
2. **Human approval always.** The scanner recommends; it never fires.
   Every order stops at a "Place Trade" button the user clicks.
3. **Schwab only.** Placing orders needs Schwab trading scope beyond the
   read-only quotes Yahoo/Schwab give us today. The whole flow is
   Schwab-gated.

## Scope today (what's built — DONE)

- Per-row **investigate** control on the watchlist **Puts leaderboard**,
  gated to watchlist + Sell + Schwab (`allow_investigate` in
  `tabs/portfolio.py` → `display/leaderboard.py`).
  - Implemented as single-row selection on the existing `st.dataframe`
    (mirrors the spreads-tab pattern), so the per-row control reuses the
    styled table rather than rebuilding it.
- Selecting a put row opens `_investigate_put_dialog` (`@st.dialog`):
  shows the contract snapshot (bid/ask/mid/last, IV, volume, open
  interest).
- **Fill-quality + limit price (`trade_actions`).** `assess_fill` judges
  executability from spread (% of mid OR small absolute) + open-interest
  floor, volume as a soft note. Liquid → an **editable limit** (mid
  rounded to tick) above the Place Trade button with credit/collateral.
  Illiquid → **warn why**, but still offer an editable limit defaulted to
  an **IV-aligned model price** (`model_limit` = Black-Scholes put at the
  contract's own IV, carrying the IV+pp edge) so the user can place their
  own limit anyway. `Place Trade` stays disabled (placement not built).
- **2D IV chart in the dialog** — embeds `show_iv_chart` for the
  ticker's puts so you can see how rich this one is vs the chain.
- **Sizing** — Schwab buying capacity (`fetch_account_capacity`, cached
  60s, read-only) + a **contracts-to-sell** input capped at
  `puts_affordable`, and a validated **order preview**
  (`build_put_sell_order`) showing the exact order, credit, collateral.
- **Trades tab + store** (`tabs/trades.py`, `trades_store.py`) — lists
  recorded put-sells with live **cost-to-close** + **unrealized P/L**
  (Schwab re-quote) and a **closing-order preview**.

The ONE thing deliberately left off: **actual order submission**. No
`client.place_order` call exists anywhere; the Place Trade and Place
Closing Trade buttons are disabled. Everything else is built around that
gate. Live re-quote runs in the Trades tab; the dialog still assesses the
scan snapshot. The Trades tab stays empty until placement is enabled.

## Phase 1 — Fill-quality check (read-only, no order)

The "is this *executable* well right now?" judgment — distinct from the
IV+pp ranking, which already answers "is this a good trade?".

- **DONE — module** `options_scanner/trade_actions.py`:
  - `assess_fill(...) -> FillAssessment` from bid, ask, mid, volume, OI.
  - Signals: bid/ask spread (% of mid **or** small absolute), OI floor;
    volume is a soft note (it's 0 for everything while the market is
    closed, so it can't gate). Output: `liquid` + `reasons` +
    `suggested_limit` + `notes`. Still TODO: last-vs-mid sanity.
  - Limit-price policy: liquid → **mid**, rounded to tick
    (`round_to_tick`); illiquid → **IV-aligned** BS price (`model_limit`)
    at the contract's own IV. TODO: one-tick-inside / "aggressive vs.
    patient" choice (open question); authoritative tick rules from Schwab.
- **DONE — dialog.** Editable limit `st.number_input` (override) with
  credit/collateral, directly above Place Trade. Liquid anchors on the
  mid; illiquid warns but still defaults the input to the IV-aligned
  model price so a trade can be priced and placed regardless.
- **DONE — 2D IV chart in the dialog.** Embeds `show_iv_chart` for the
  ticker's puts (full chain threaded from `results` through
  `render_leaderboard` → `_render_table`), so the user sees how IV-rich
  this put is vs the chain. TODO: highlight the selected strike (the
  chart shows all puts; the selected one isn't called out yet).
- **DONE — `requote_put`** (read-only, reuses
  `schwab_live.fetch_option_chain_schwab`). Used for cost-to-close in the
  Trades tab. TODO: also re-quote inside the dialog before assessing and
  show a fetch time (dialog still uses the scan snapshot).
- **DONE — tests** (`tests/test_trade_actions.py`): tick rounding,
  assess_fill (liquid/wide+thin/cheap-rescue/one-sided), model_limit,
  puts_affordable, build_put_sell_order + validation/capacity guard.

## Phase 2 — Place the order (the gate)

- **Schwab trading scope.** Confirm what the Schwab API requires to
  place an options order vs. read quotes: OAuth scope, account
  trading-enabled, the order-entry endpoint. Builds on the existing
  `schwab_auth.py` flow (7-day token TTL). Document the re-auth /
  permission steps the way ep2 did for quotes.
- **DONE (config) — paper flag.** `get_schwab_config` exposes
  `paper` (default **True**) so live orders are an explicit opt-in. TODO:
  confirm Schwab's paper/sandbox order path exists; add a paper-mode
  badge once placement is wired.
- **DONE — put-selling capacity.** `fetch_account_capacity` reads
  available cash / buying power (read-only, `get_account_numbers` +
  `get_account`), cached 60s in the dialog. `puts_affordable` =
  capacity ÷ (strike × 100) caps the quantity input.
- **DONE — order builder (validation only).** `build_put_sell_order`
  returns a `PutSellOrder` (credit/collateral/describe) and enforces
  guardrail #1 (qty ≥ 1, limit > 0, strike > 0, collateral ≤ capacity).
  TODO: map it to schwab-py `option_sell_to_open_limit` +
  `client.place_order` — **intentionally not wired** ("don't allow
  trades"). The dialog shows the order preview; Place Trade is disabled.
- **DONE — approval-gate UI (minus the gate).** Contracts-to-sell input
  (capped by capacity), capacity metric, and a live order preview
  (order string + credit + collateral) in the dialog. TODO: enable Place
  Trade after a "go" + a final confirm step + paper/live badge + record
  to the store.
- **Schwab trading scope** (still TODO) — confirm OAuth scope / account
  trading-enabled / order-entry endpoint before wiring `place_order`.

## Phase 3 — Trade tracker tab (P/L + closing)

**DONE (scaffold).** New top-level "Trades" tab (`tabs/trades.py`, wired
into `run_app.py` after Watchlist). Empty until placement is enabled.

- **DONE — store** (`trades_store.py`): single gitignored JSON
  (`options-scanner/trades/`) with `load/add/update/remove`; records
  ticker, strike, expiration, qty, credit, status, paper, order_id,
  opened_at, close_cost, closed_at. TODO: optional reconcile against a
  live Schwab positions/orders pull.
- **DONE — per-position view:** live **cost-to-close** (`requote_put`
  mid, cached 30s) and **unrealized P/L** (credit − close cost) × 100 ×
  qty, plus status. TODO: DTE + LT-cap-gains qualifying date.
- **DONE — closing flow UI (disabled):** suggested close limit
  (re-quote mid → tick), editable, with a disabled **Place Closing
  Trade** button. TODO: `build_put_close_order` (BUY_TO_CLOSE PUT, LIMIT)
  → `place_order`, same guardrails + confirm; flip status to closed in
  the store.
- **DONE — verify-at-broker caveat** shown throughout.

## Schwab API specifics to confirm

- Exact OAuth scope / account flag for order entry.
- Order-entry endpoint + payload schema for single-leg options.
- Paper/sandbox availability and how to target it.
- Account hash retrieval (already used for quotes? confirm).
- Account balances endpoint — available cash and margin available — to
  compute how much we can sell (capacity = cash / margin ÷ collateral)
  and to validate qty before sending.
- Tick-size / price-increment rules for the limit price.

## Open questions (from the concept)

- Recommendation surface — dialog (current stub) vs. inline expander vs.
  side panel. Stub uses a dialog; revisit if it feels cramped.
- Tracker persistence — local JSON, read-back from Schwab, or hybrid.
- Investigate per-row-on-click (current) vs. bulk auto-run across the
  whole leaderboard. Per-row keeps it deliberate.
- Limit-price opinionation — single suggested price vs. an
  aggressive/patient range.

## Touch points (current code)

- `options_scanner/display/leaderboard.py` — investigate control +
  dialog stub (Phase 1 UI grows here / into `trade_actions.py`).
- `options_scanner/tabs/portfolio.py` — `allow_investigate` gating
  (`_render_scan_tab`, watchlist branch).
- `stocks_shared/schwab_live.py` — Schwab client, quotes, chain fetch
  (extend for order entry / single-contract re-quote).
- `options_scanner/config.py` — `[schwab]` config (add paper flag).
- `run_app.py` — add the "Trades" tab (Phase 3, confirm first).
