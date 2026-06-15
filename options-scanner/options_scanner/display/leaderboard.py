"""Cross-ticker IV+pp leaderboard for the Portfolio tab.

Aggregates the top-N picks from every scanned ticker into one ranked
table — "across the whole basket, which contracts have the richest
IV+pp right now?" Shown for both the brokerage-CSV and watchlist input
sources, above the per-ticker expanders.

Ranking reuses the same convention as the per-position tables and the
IV chart (`compute.top_ranks`): sort by `signal_score` (descending in
sell mode), `open_interest` as the tiebreaker — so a contract's place
here is consistent with its rank everywhere else.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from options_scanner import iv_scores
from options_scanner.format import EARNINGS_WARN_LEGEND, fmt_strike
from options_scanner.display.scan_stamp import stamp_caption


@st.cache_data(ttl=60, show_spinner=False)
def _account_capacity(app_key: str, app_secret: str, callback_url: str,
                      token_file: str) -> dict | None:
    """Cached (60s) read-only Schwab capacity. Returns dict or None.

    Keyed on the credentials so a re-auth (new token file) busts it via the
    same path the rest of the app uses. Read-only — no order entry.
    """
    from stocks_shared.schwab_live import get_client
    from options_scanner import trade_actions
    try:
        client = get_client(app_key, app_secret, callback_url, token_file)
    except Exception:
        return None
    cap = trade_actions.fetch_account_capacity(client)
    if cap is None:
        return None
    return {"cash": cap.cash_available, "bp": cap.buying_power,
            "amount": cap.amount}


@st.dialog("🔍 Investigate put-sell", width="large")
def _investigate_put_dialog(c: dict, ticker_df: "pd.DataFrame | None" = None,
                            min_oi: int = 25, top_n: int = 5,
                            min_vol: int = 0, provider: str = "schwab") -> None:
    """Assisted put-selling dialog (Schwab, watchlist leaderboard).

    Shows the contract snapshot and a 2-D IV chart (where this put sits vs
    the chain), judges whether it looks executable (fill-quality heuristic in
    ``trade_actions``), suggests an editable limit price, then a contracts-to-
    sell input sized against the account's buying capacity, and a validated
    **order preview**. Order *placement* is intentionally NOT wired — the
    Place Trade button stays disabled. See
    ``options-scanner/assisted-put-selling-implementation-plan.md``.
    """
    from options_scanner import trade_actions

    exp = datetime.strptime(c["expiration"], "%Y-%m-%d").strftime("%b %d '%y")
    st.markdown(
        f"### {c['ticker']} &nbsp; ${c['strike']:g} PUT"
        f" &nbsp;·&nbsp; {exp} ({c['dte']} DTE)"
    )

    def _money(v):
        return f"${v:.2f}" if v is not None else "—"

    iv_txt = f"{c['iv'] * 100:.1f}%" if c.get("iv") is not None else "—"
    snap = pd.DataFrame({
        "Field": ["Bid", "Ask", "Mid", "Last", "IV", "Volume", "Open Interest"],
        "Value": [
            _money(c.get("bid")), _money(c.get("ask")), _money(c.get("mid")),
            _money(c.get("last")), iv_txt,
            f"{c['volume']:,d}", f"{c['open_interest']:,d}",
        ],
    })
    st.dataframe(snap, hide_index=True, width="stretch")

    # 2-D IV chart — how rich this put is vs the rest of the chain.
    if ticker_df is not None and not ticker_df.empty and c.get("spot"):
        try:
            from options_scanner.display.iv_chart import show_iv_chart
            show_iv_chart(
                ticker_df, float(c["spot"]), "put", int(min_oi), int(top_n),
                buy=False, ticker=c["ticker"],
                key_prefix=f"inv_{c['ticker']}_{c['strike']:g}_{c['expiration']}",
                min_vol=int(min_vol), provider=provider,
            )
        except Exception:
            st.caption("IV chart unavailable for this contract.")

    assessment = trade_actions.assess_fill(
        bid=c.get("bid"), ask=c.get("ask"), mid=c.get("mid"),
        volume=c.get("volume"), open_interest=c.get("open_interest", 0),
    )
    for note in assessment.notes:
        st.caption(f"⚠ {note}")

    st.caption(
        "Guardrails: sells puts only · never fires without your click · "
        "Schwab only (read-only quotes can't place orders)."
    )
    st.markdown("---")

    # Decision zone — a default limit + editable override. Liquid → anchor on
    # the mid. Illiquid → warn, but still offer an IV-aligned model price so
    # the user can place their own limit anyway.
    if assessment.liquid:
        default_limit = assessment.suggested_limit
        st.markdown("**Suggested limit price** — the mid, rounded to the "
                    "tick. Edit to override.")
    else:
        st.warning(
            "**Not liquid enough for a confident fill:** "
            + "; ".join(assessment.reasons)
            + ". You can still set your own limit and place the trade."
        )
        model = trade_actions.model_limit(
            spot=c.get("spot"), strike=c["strike"], dte=c["dte"],
            iv=c.get("iv"),
        )
        default_limit = model or assessment.suggested_limit or c.get("mid") or 0.05
        if model is not None:
            st.markdown(
                f"**IV+pp-aligned limit: ${model:.2f}** — priced from the "
                "contract's own IV (the surface edge), so it reflects the "
                "rich premium even though a fill here is unlikely in a "
                "wide/thin market. Edit to override."
            )
        else:
            st.markdown("**Set your limit price** — couldn't model an "
                        "IV-aligned price for this contract, so start from "
                        "the market and adjust.")

    limit = st.number_input(
        "Limit price (credit per share)",
        min_value=0.01, value=float(default_limit),
        step=float(trade_actions.tick_for(default_limit)), format="%.2f",
        key=f"investigate_limit_{c['ticker']}_{c['strike']:g}_{c['expiration']}",
    )

    # Sizing — contracts to sell, capped by the account's put-selling capacity.
    scfg = st.session_state.get("schwab_config") or {}
    cap = (_account_capacity(scfg.get("app_key", ""), scfg.get("app_secret", ""),
                             scfg.get("callback_url", ""),
                             scfg.get("token_file", ""))
           if scfg.get("app_key") else None)
    cap_amt = cap.get("amount") if cap else None
    affordable = trade_actions.puts_affordable(cap_amt, c["strike"])

    qc1, qc2 = st.columns([1, 1])
    with qc1:
        qty = st.number_input(
            "Contracts to sell", min_value=1, value=1, step=1,
            max_value=(affordable if affordable and affordable >= 1 else None),
            key=f"investigate_qty_{c['ticker']}_{c['strike']:g}_{c['expiration']}",
        )
    with qc2:
        if cap_amt is not None:
            st.metric("Buying capacity", f"${cap_amt:,.0f}",
                      help="Available cash / buying power from Schwab.")
        else:
            st.caption("Buying capacity unavailable (Schwab not reachable).")

    if affordable is not None:
        st.caption(f"You could sell up to **{affordable}** of this put "
                   f"(${c['strike'] * 100:,.0f} collateral each).")

    # Order preview — validation only; nothing is placed.
    try:
        order = trade_actions.build_put_sell_order(
            ticker=c["ticker"], strike=c["strike"], expiration=c["expiration"],
            limit=float(limit), quantity=int(qty), capacity=cap_amt,
        )
        st.success(
            f"**Order preview:** {order.describe()} — credit "
            f"**${order.credit:,.0f}**, collateral **${order.collateral:,.0f}**."
        )
    except ValueError as exc:
        st.error(f"Can't build this order: {exc}")

    st.button(
        "Place Trade", disabled=True,
        help="Order placement isn't wired up yet — coming in a future update.",
    )
    st.caption("Placement is disabled — this previews the order only. "
               "Always verify at your broker.")


def build_leaderboard(results: list[dict], side: str, min_oi: int,
                      top_n: int, min_vol: int = 0,
                      delta_range: tuple[float, float] | None = None,
                      buy: bool = False,
                      ) -> pd.DataFrame:
    """Collect a "best per ticker, then fill" leaderboard for one side.

    `side` is "call" or "put". Selection:

      1. Each ticker's single best contract (its #1) is guaranteed a slot,
         so every scanned ticker that has any qualifying option is
         represented.
      2. Remaining slots are filled with the next-best leftovers globally
         (each ticker contributes at most `top_n`).
      3. Total rows = 2× the number of tickers that have ≥1 qualifying
         option, then everything is sorted by IV+pp so the richest float
         to the top even when several come from the same ticker.

    Returns a DataFrame with a `ticker` column, the chain columns, and a
    boolean `_is_ticker_top` flag (True for each ticker's #1 pick — used
    to shade those rows). Empty frame when nothing qualifies.
    """
    sort_col_for = lambda f: ("signal_score" if "signal_score" in f.columns
                              else "iv_excess")

    per_ticker = []  # each ticker's top-N rows, #1 first
    for res in results:
        if res.get("error"):
            continue
        df = res.get("df")
        if df is None or df.empty:
            continue
        sub = df[(df["type"] == side)
                 & (df["open_interest"] >= min_oi)
                 & (df["volume"] >= min_vol)]
        if delta_range is not None:
            lo, hi = delta_range
            sub = sub[sub["delta"].abs().between(lo, hi)]
        if sub.empty:
            continue
        sub = (sub.sort_values([sort_col_for(sub), "open_interest"],
                               ascending=[buy, False])
               .head(top_n).copy())
        sub["ticker"] = res["position"]["ticker"]
        sub["_is_ticker_top"] = [True] + [False] * (len(sub) - 1)
        per_ticker.append(sub.reset_index(drop=True))

    if not per_ticker:
        return pd.DataFrame()

    n_tickers = len(per_ticker)
    target = 2 * n_tickers

    # 1. Guarantee every ticker's #1 pick.
    guaranteed = pd.concat([t.iloc[[0]] for t in per_ticker], ignore_index=True)

    # 2. Fill remaining slots from the next-best leftovers globally.
    leftovers = [t.iloc[1:] for t in per_ticker if len(t) > 1]
    if leftovers:
        pool = pd.concat(leftovers, ignore_index=True)
        sc = sort_col_for(pool)
        pool = pool.sort_values([sc, "open_interest"], ascending=[buy, False])
        fill = pool.head(max(0, target - len(guaranteed)))
        combined = pd.concat([guaranteed, fill], ignore_index=True)
    else:
        combined = guaranteed

    # 3. Final display sort by signal (richest first when selling, cheapest
    #    first when buying).
    sc = sort_col_for(combined)
    combined = (combined.sort_values([sc, "open_interest"],
                                     ascending=[buy, False])
                .head(target).reset_index(drop=True))
    return combined


def render_leaderboard(results: list[dict], mode: str, min_oi: int,
                       top_n: int, min_vol: int = 0,
                       delta_range: tuple[float, float] | None = None,
                       buy: bool = False,
                       allow_investigate: bool = False,
                       provider: str = "yahoo") -> None:
    """Render the cross-ticker leaderboard table(s).

    `mode` is "call", "put", or "both" (both renders a Calls and a Puts
    leaderboard). `buy` flips the ranking so IV-cheap contracts float to
    the top. Shows an explanatory notice when nothing qualifies at all.

    `allow_investigate` turns each Puts-board row into a selectable control
    that opens the assisted put-selling dialog. The caller gates it to
    watchlist + sell + Schwab; here it only ever attaches to the Puts board
    (you can't sell-to-open a put from the Calls board). `provider` and the
    per-ticker chains (looked up from `results`) feed the dialog's IV chart.
    """
    sides = [mode] if mode in ("call", "put") else ["call", "put"]
    headings = {"call": "Calls", "put": "Puts"}
    ticker_dfs = {
        r["position"]["ticker"]: r["df"]
        for r in results
        if r.get("df") is not None and not r["df"].empty
    }

    rendered_any = False
    for side in sides:
        board = build_leaderboard(results, side, min_oi, top_n, min_vol,
                                  delta_range, buy)
        if board.empty:
            continue
        rendered_any = True
        if len(sides) > 1:
            st.markdown(f"**{headings[side]}**")
        _render_table(board, side, min_vol,
                      investigate=(allow_investigate and side == "put"),
                      min_oi=min_oi, top_n=top_n, ticker_dfs=ticker_dfs,
                      provider=provider)

    if not rendered_any:
        st.info(
            f"No contracts passed the leaderboard filters "
            f"(Min OI ≥ {min_oi}, Min Vol ≥ {min_vol}"
            + (f", |delta| {delta_range[0]:.2f}–{delta_range[1]:.2f}"
               if delta_range is not None else "")
            + "). Try loosening Min OI / Min Vol — note Vol is *today's* "
              "volume, which is 0 for every contract before the market has "
              "traded."
        )
        return
    st.caption("Shaded rows are each ticker's top pick; other rows fill in "
               "the next-richest contracts across the basket.")
    stamp_caption()


def _render_table(board: pd.DataFrame, side: str, min_vol: int,
                  investigate: bool = False, min_oi: int = 25, top_n: int = 5,
                  ticker_dfs: dict | None = None,
                  provider: str = "yahoo") -> None:
    """Render one leaderboard table, styled like the scan-results table.

    When `investigate` is True the table becomes single-row-selectable and
    selecting a row opens the assisted put-selling dialog. `min_oi`/`top_n`/
    `ticker_dfs`/`provider` feed that dialog's IV chart.
    """
    kind = iv_scores.active_kind(board)

    # ⚠ in the Expiration cell = short-dated (≤60 DTE) and expiring after the
    # next earnings — its IV+pp carries event premium and it's the slice
    # excluded from the surface fit. Cheaper than a whole column.
    _ec = (board["earnings_count"].fillna(0) if "earnings_count" in board.columns
           else pd.Series(0, index=board.index))

    def _exp_cell(e, d, c):
        base = datetime.strptime(e, "%Y-%m-%d").strftime("%b %d '%y")
        return f"{base} ⚠" if (c >= 1 and d <= 60) else base

    _has_warn = any(c >= 1 and d <= 60
                    for c, d in zip(_ec, board["dte"]))

    cols = {
        "Ticker": board["ticker"],
        "Strike": board["strike"].apply(fmt_strike),
        "Expiration": [_exp_cell(e, d, c) for e, d, c
                       in zip(board["expiration"], board["dte"], _ec)],
        "DTE":   board["dte"].astype(int),
        "Bid":   board["bid"].round(2),
        "Ask":   board["ask"].round(2),
        "Mid":   board["mid"].round(2),
        "Last":  (board["last"].where(board["last"] > 0)
                  if "last" in board.columns
                  else pd.Series([float("nan")] * len(board), index=board.index)),
        "IV+pp": (board["iv_excess"] * 100).round(1),
    }
    if kind != "IV+pp":
        mult, _ = iv_scores.display_for(kind)
        cols[kind] = (board["signal_score"] * mult).round(2)
    cols.update({
        "Delta": board["delta"].round(2),
        "Ann%":  board["ann_yield_pct"].round(1),
        "OI":    board["open_interest"],
        "Vol":   board["volume"],
    })
    disp = pd.DataFrame(cols)

    # Shade each ticker's #1 pick so it stands out from its fill rows.
    top_mask = (board["_is_ticker_top"].tolist()
                if "_is_ticker_top" in board.columns else [False] * len(board))
    _TOP_ROW = "background-color: rgba(53,194,193,0.16)"

    def _shade(_row):
        i = disp.index.get_loc(_row.name)
        return [_TOP_ROW if top_mask[i] else ""] * len(_row)

    styled = disp.style.apply(_shade, axis=1)

    col_cfg = {
        "Ticker":     st.column_config.TextColumn("Ticker", width=70),
        "Strike":     st.column_config.TextColumn("Strike", width=75),
        "Expiration": st.column_config.TextColumn(
            "Expiration", width=125,
            help="⚠ = ≤60 DTE and expiring after the next earnings, so its "
                 "IV+pp includes event premium (and it's excluded from the "
                 "surface fit)."),
        "DTE":   st.column_config.NumberColumn("DTE", format="%d", width=55),
        "Bid":   st.column_config.NumberColumn("Bid", format="$%.2f", width=70),
        "Ask":   st.column_config.NumberColumn("Ask", format="$%.2f", width=70),
        "Mid":   st.column_config.NumberColumn("Mid", format="$%.2f", width=70),
        "Last":  st.column_config.NumberColumn("Last", format="$%.2f", width=70),
        "IV+pp": st.column_config.NumberColumn("IV+pp", format="%+.1f pp",
                                               width=80),
        "Delta": st.column_config.NumberColumn("Delta", format="%.2f",
                                               width=60),
        "Ann%":  st.column_config.NumberColumn("Ann%", format="%.1f%%",
                                               width=65),
        "OI":    st.column_config.NumberColumn("OI", format="%d", width=65),
        "Vol":   st.column_config.NumberColumn("Vol", format="%d", width=65),
    }
    if kind != "IV+pp":
        _, fmt = iv_scores.display_for(kind)
        col_cfg[kind] = st.column_config.NumberColumn(
            kind, format=fmt, width=85,
            help="Active ranking score — the leaderboard is ranked by this "
                 "column. IV+pp shown alongside for context.")

    if not investigate:
        st.dataframe(styled, column_config=col_cfg, hide_index=True,
                     width="stretch")
        if _has_warn:
            st.caption(EARNINGS_WARN_LEGEND)
        return

    # Assisted put-selling (Schwab, watchlist): each row is selectable, and
    # picking one opens the investigate dialog (stub for now).
    st.caption("🔍 **Select a put row** to investigate placing a cash-secured "
               "put sell — Schwab assisted trade (preview).")
    event = st.dataframe(styled, column_config=col_cfg, hide_index=True,
                         width="stretch", on_select="rerun",
                         selection_mode="single-row", key="lb_investigate_put")
    if _has_warn:
        st.caption(EARNINGS_WARN_LEGEND)
    sel = event.selection.rows if hasattr(event, "selection") else []
    if not sel:
        return

    def _num(v):
        try:
            f = float(v)
            return f if f == f else None  # NaN → None
        except (TypeError, ValueError):
            return None

    row = board.iloc[sel[0]]
    contract = {
        "ticker": str(row["ticker"]),
        "strike": float(row["strike"]),
        "expiration": str(row["expiration"]),
        "dte": int(row["dte"]),
        "bid": _num(row.get("bid")),
        "ask": _num(row.get("ask")),
        "mid": _num(row.get("mid")),
        "last": _num(row.get("last")) if "last" in board.columns else None,
        "iv": _num(row.get("iv")) if "iv" in board.columns else None,
        "spot": _num(row.get("spot")) if "spot" in board.columns else None,
        "volume": int(row["volume"]),
        "open_interest": int(row["open_interest"]),
    }
    # Only open the modal on a *new* selection, so dismissing it doesn't
    # immediately reopen on the next rerun while the row stays selected.
    sel_key = f"{contract['ticker']}|{contract['strike']}|{contract['expiration']}"
    if st.session_state.get("_lb_last_investigated") != sel_key:
        st.session_state["_lb_last_investigated"] = sel_key
        _investigate_put_dialog(
            contract,
            ticker_df=(ticker_dfs or {}).get(contract["ticker"]),
            min_oi=min_oi, top_n=top_n, min_vol=min_vol, provider=provider,
        )
