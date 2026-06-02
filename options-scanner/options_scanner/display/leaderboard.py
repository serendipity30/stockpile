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
from options_scanner.display.scan_stamp import stamp_caption


def build_leaderboard(results: list[dict], side: str, min_oi: int,
                      top_n: int, min_vol: int = 0,
                      delta_range: tuple[float, float] | None = None,
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
                               ascending=[False, False])
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
        pool = pool.sort_values([sc, "open_interest"], ascending=[False, False])
        fill = pool.head(max(0, target - len(guaranteed)))
        combined = pd.concat([guaranteed, fill], ignore_index=True)
    else:
        combined = guaranteed

    # 3. Final display sort by IV+pp (richest first).
    sc = sort_col_for(combined)
    combined = (combined.sort_values([sc, "open_interest"],
                                     ascending=[False, False])
                .head(target).reset_index(drop=True))
    return combined


def render_leaderboard(results: list[dict], mode: str, min_oi: int,
                       top_n: int, min_vol: int = 0,
                       delta_range: tuple[float, float] | None = None) -> None:
    """Render the cross-ticker leaderboard table(s).

    `mode` is "call", "put", or "both" (both renders a Calls and a Puts
    leaderboard). No-op when nothing qualifies on a side.
    """
    sides = [mode] if mode in ("call", "put") else ["call", "put"]
    headings = {"call": "Calls", "put": "Puts"}

    rendered_any = False
    for side in sides:
        board = build_leaderboard(results, side, min_oi, top_n, min_vol,
                                  delta_range)
        if board.empty:
            continue
        rendered_any = True
        if len(sides) > 1:
            st.markdown(f"**{headings[side]}**")
        _render_table(board, side, min_vol)

    if not rendered_any:
        return
    st.caption("Shaded rows are each ticker's top pick; other rows fill in "
               "the next-richest contracts across the basket.")
    stamp_caption()


def _render_table(board: pd.DataFrame, side: str, min_vol: int) -> None:
    """Render one leaderboard table, styled like the scan-results table."""
    kind = iv_scores.active_kind(board)

    def _earn_tag(n) -> str:
        try:
            n = int(n)
        except (ValueError, TypeError):
            return ""
        return f" · {n}E" if n > 0 else ""

    cols = {
        "Ticker": board["ticker"],
        "Strike": board["strike"].apply(lambda x: f"${x:.0f}"),
        "Expiration": board.apply(
            lambda r: datetime.strptime(r["expiration"], "%Y-%m-%d")
            .strftime("%b %d '%y") + _earn_tag(r.get("earnings_count")),
            axis=1,
        ),
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
        "Expiration": st.column_config.TextColumn("Expiration", width=115),
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

    st.dataframe(styled, column_config=col_cfg, hide_index=True,
                 width="stretch")
