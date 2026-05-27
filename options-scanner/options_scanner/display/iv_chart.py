"""Per-expiration volatility-surface chart with top-N pick callouts.

Renders the chain at one chosen expiration as a smile of IV dots with
one reference line, the table's top picks highlighted (large outlined
dots with rank labels), and a spot reference rule.

Reference line (green solid):
  IV surface (IV ≈ a+b·m+c·m²+d·√T+e·m·√T) fitted to all dropdown
  expirations using the configured surface filters (default: OTM-only,
  spread ≤ 50%, Δ 0.05–0.95). Dot colors and IV+pp both measure
  distance from this line, so they are fully consistent.

The pick highlighting and ranking come from compute.top_ranks — the same
function the bottom table uses — so chart and table never disagree.
"""

from __future__ import annotations

from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from options_scanner.compute.top_ranks import compute_top_ranks
from options_scanner.display.scan_stamp import scan_stamp_color, scan_stamp_text


_PROVIDER_LINE = {
    "yahoo":  {"color": "#10b981", "strokeDash": [6, 4]},  # green dashed
    "schwab": {"color": "#3b82f6", "strokeDash": [6, 4]},  # blue dashed
}


def show_iv_chart(df: pd.DataFrame, spot: float, mode: str,
                  min_oi: int, top_n: int, buy: bool,
                  ticker: str = "", key_prefix: str = "s",
                  min_vol: int = 0, provider: str = "yahoo",
                  earnings_dates: list | None = None,
                  surface_filters: tuple | None = None) -> None:
    """Layered chart: per-expiration smile with the table's top-N picks
    highlighted. Faded background dots are the rest of the chain at the
    selected expiration; bright outlined dots are the top picks."""
    if df.empty:
        return

    chart_df = df.copy()
    if mode in ("call", "put"):
        chart_df = chart_df[chart_df["type"] == mode]
    if chart_df.empty:
        return

    top_ranks = compute_top_ranks(chart_df, mode, buy, min_oi, top_n, min_vol)
    chart_df["is_top"] = chart_df.apply(
        lambda r: (r["type"], float(r["strike"]), r["expiration"]) in top_ranks,
        axis=1,
    )
    chart_df["rank_label"] = chart_df.apply(
        lambda r: str(top_ranks.get(
            (r["type"], float(r["strike"]), r["expiration"]), ""
        )),
        axis=1,
    )
    chart_df["IV%"]       = (chart_df["iv"] * 100).round(2)
    chart_df["FittedIV%"] = (chart_df["iv_fitted"] * 100).round(2)
    chart_df["IV+pp"]     = (chart_df["iv_excess"] * 100).round(2)
    chart_df["Ann%"]      = chart_df["ann_yield_pct"].round(2)
    from options_scanner import iv_scores as _iv_scores
    _score_kind = _iv_scores.active_kind(chart_df)
    _show_score = _score_kind != "IV+pp" and "signal_score" in chart_df.columns
    if _show_score:
        _mult, _ = _iv_scores.display_for(_score_kind)
        chart_df[_score_kind] = (chart_df["signal_score"] * _mult).round(2)
    exp_dte = chart_df.groupby("expiration")["dte"].first().to_dict()
    chart_df["ExpLabel"] = chart_df["expiration"].apply(
        lambda d: (f"{datetime.strptime(d, '%Y-%m-%d').strftime('%b %d \'%y')}"
                   f" ({exp_dte.get(d, 0)}d)")
    )

    expirations = sorted(chart_df["expiration"].unique())
    exp_labels = {
        e: (f"{datetime.strptime(e, '%Y-%m-%d').strftime('%b %d \'%y')}"
            f" — {exp_dte.get(e, 0)}d")
        for e in expirations
    }
    pick_counts = {
        e: int(chart_df[(chart_df["expiration"] == e) & chart_df["is_top"]].shape[0])
        for e in expirations
    }
    best_exps = {exp for (_, _, exp), r in top_ranks.items() if r == 1}
    picks_df = chart_df[chart_df["is_top"]]
    if not picks_df.empty:
        extreme_idx = (picks_df["iv_excess"].idxmin() if buy
                       else picks_df["iv_excess"].idxmax())
        default_exp = picks_df.loc[extreme_idx, "expiration"]
        default_idx = expirations.index(default_exp)
    else:
        default_idx = 0

    h1, h2 = st.columns([1, 2], vertical_alignment="bottom")
    with h1:
        st.markdown(
            "<h5 style='margin:0 0 5px 0'>Volatility surface</h5>",
            unsafe_allow_html=True,
        )
    with h2:
        chosen_exp = st.selectbox(
            "Expiration to chart",
            options=expirations,
            index=default_idx,
            format_func=lambda d: (
                f"{'★ ' if d in best_exps else ''}{exp_labels[d]}"
                f"  ({pick_counts[d]} pick"
                f"{'s' if pick_counts[d] != 1 else ''})"
            ),
            key=f"{key_prefix}_chart_exp",
            help=("Each expiration has its own volatility smile. The number "
                  "in parentheses is how many of the table's top picks live "
                  "at that expiration."),
            label_visibility="collapsed",
        )

    sub = chart_df[chart_df["expiration"] == chosen_exp].sort_values(
        ["type", "strike"]
    ).copy()
    if sub.empty:
        return

    # Warn when this expiration's line isn't a fit to its own contracts.
    _fit_method = (str(sub["fit_method"].iloc[0])
                   if "fit_method" in sub.columns else "")
    if _fit_method == "fallback":
        _exp_date = datetime.strptime(chosen_exp, "%Y-%m-%d").date()
        _excl_earn = surface_filters and any(
            n == "exclude_earnings" for n, _ in surface_filters
        )
        _earn_spans = earnings_dates and any(
            date.today() < ed <= _exp_date for ed in earnings_dates
        )
        if _excl_earn and _earn_spans:
            st.warning(
                f"**{exp_labels[chosen_exp]}** has an earnings event before "
                "expiration — the earnings-exclusion filter removed those "
                "contracts from the fit, leaving too few to fit this slice "
                "locally. The line shown is the cross-expiration surface. "
                "Earnings IV premium still shows up as positive IV+pp.",
                icon="⚠️",
            )
        else:
            st.warning(
                f"The per-expiry fit couldn't fit **{exp_labels[chosen_exp]}** "
                "from its own contracts (too few passed the surface-fit "
                "filters), so this line is the cross-expiration surface — it "
                "may not reflect this expiry's own smile. Switch the **Fit:** "
                "toggle to *Global*, or relax the surface-fit filters / widen "
                "the DTE range.",
                icon="⚠️",
            )
    elif _fit_method == "none":
        st.warning(
            "Not enough clean contracts to fit a surface for this scan, so "
            "the line just traces the quotes (IV+pp ≈ 0). Widen the DTE "
            "range or relax the surface-fit filters.",
            icon="⚠️",
        )

    iv_cols = ["IV%", "FittedIV%"]
    y_min = max(0.0, float(sub[iv_cols].values.min()) * 0.92)
    y_max = float(sub[iv_cols].values.max()) * 1.05

    excess_max = max(abs(sub["IV+pp"].min()), abs(sub["IV+pp"].max()), 1.0)
    if buy:
        color_range = ["#22c55e", "#cbd5e1", "#ef4444"]
    else:
        color_range = ["#ef4444", "#cbd5e1", "#22c55e"]
    color_scale = alt.Scale(
        domain=[-excess_max, 0, excess_max], range=color_range)
    shape_scale = alt.Scale(
        domain=["call", "put"], range=["circle", "square"])

    x_min = min(float(sub["strike"].min()), spot) * 0.97
    x_max = max(float(sub["strike"].max()), spot) * 1.03

    base_x = alt.X(
        "strike:Q", title="Strike",
        scale=alt.Scale(domain=[x_min, x_max]),
        axis=alt.Axis(format="$,.0f"),
    )
    y_scale = alt.Scale(domain=[y_min, y_max])
    base_y = alt.Y("IV%:Q", title="Implied Volatility (%)", scale=y_scale)

    # D3 number formats for each score kind (Altair tooltips use D3, not printf).
    _SCORE_D3_FMT = {"IV z": "+.2f", "IV rel": "+.1%", "Score": "+.2f",
                     "VRP": ".2f", "IV %ile": ".0f"}
    _score_d3_fmt = _SCORE_D3_FMT.get(_score_kind, "+.2f")
    tooltip_fields = [
        alt.Tooltip("strike:Q",       title="Strike",          format="$,.0f"),
        alt.Tooltip("type:N",         title="Type"),
        alt.Tooltip("IV%:Q",                                   format=".1f"),
        alt.Tooltip("FittedIV%:Q",    title="Surface IV%",     format=".1f"),
        alt.Tooltip("IV+pp:Q",        title="IV excess (pp)",  format="+.1f"),
        *([alt.Tooltip(f"{_score_kind}:Q", title=_score_kind,
                       format=_score_d3_fmt)]
          if _show_score else []),
        alt.Tooltip("delta:Q",                                 format=".2f"),
        alt.Tooltip("Ann%:Q",         title="Ann%",            format=".1f"),
        alt.Tooltip("volume:Q",       title="Volume",          format=",.0f"),
        alt.Tooltip("open_interest:Q", title="OI"),
        alt.Tooltip("bid:Q",          title="Bid",             format="$.2f"),
        alt.Tooltip("ask:Q",          title="Ask",             format="$.2f"),
    ]

    # Dashed line — color encodes data source (blue=Yahoo, green=Schwab)
    _line_style = _PROVIDER_LINE.get(provider, _PROVIDER_LINE["yahoo"])
    line_surface = alt.Chart(sub).mark_line(
        size=2, **_line_style,
    ).encode(
        x=base_x,
        y=alt.Y("FittedIV%:Q", scale=y_scale),
        detail="type:N",
    )

    background = alt.Chart(sub[~sub["is_top"]]).mark_circle(
        size=60, opacity=1.0,
    ).encode(
        x=base_x,
        y=base_y,
        color=alt.Color("IV+pp:Q", scale=color_scale,
                        legend=alt.Legend(title="IV excess (pp)")),
        shape=alt.Shape("type:N", scale=shape_scale,
                        legend=alt.Legend(title="Type")),
        tooltip=tooltip_fields,
    )

    picks = alt.Chart(sub[sub["is_top"]]).mark_point(
        size=260, opacity=1.0, filled=True,
        stroke="#0f172a", strokeWidth=2,
    ).encode(
        x=base_x,
        y=base_y,
        color=alt.Color("IV+pp:Q", scale=color_scale, legend=None),
        shape=alt.Shape("type:N", scale=shape_scale, legend=None),
        tooltip=tooltip_fields,
    )

    ranks = alt.Chart(sub[sub["is_top"]]).mark_text(
        fontSize=14, dy=-20, fontWeight="bold", color="#0f172a",
    ).encode(
        x=base_x,
        y=base_y,
        text="rank_label:N",
    )

    spot_df = pd.DataFrame({
        "x": [spot], "y": [y_max], "label": [f"Spot ${spot:.2f}"],
    })
    spot_rule = alt.Chart(spot_df).mark_rule(
        color="#0f172a", strokeDash=[3, 3], size=2,
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[x_min, x_max])),
        tooltip=[alt.Tooltip("x:Q", title="Spot", format="$,.2f")],
    )
    spot_label = alt.Chart(spot_df).mark_text(
        align="left", baseline="top", dx=5, dy=2,
        color="#0f172a", fontWeight="bold", fontSize=11,
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[x_min, x_max])),
        y="y:Q",
        text="label:N",
    )

    type_word = {"call": "calls", "put": "puts", "both": "options"}[mode]
    title_text = (f"{ticker} {type_word} — {exp_labels[chosen_exp]}"
                  if ticker else f"{type_word} — {exp_labels[chosen_exp]}")
    chart = (
        line_surface + background + picks + ranks + spot_rule + spot_label
    ).properties(
        height=380,
        title=alt.TitleParams(
            text=title_text,
            subtitle=scan_stamp_text() or None,
            subtitleColor=scan_stamp_color(),
            subtitleFontSize=11,
            fontSize=16, fontWeight="bold", anchor="start",
            color="#0f172a",
        ),
    )
    st.altair_chart(chart, width='stretch')

    st.markdown(
        "<div style='font-size:0.8rem;line-height:1.9;color:var(--osc-ink-3)'>"
        "<span style='color:#10b981'>&#9632;&#9632; &mdash; &mdash;</span>"
        "&nbsp;<b>Green dashed</b> (Yahoo Finance)&nbsp;&nbsp;"
        "<span style='color:#3b82f6'>&#9632;&#9632; &mdash; &mdash;</span>"
        "&nbsp;<b>Blue dashed</b> (Schwab) &mdash;"
        " IV surface fit across all fetched expirations (within your DTE range),"
        " using only clean data (configurable under <i>Surface fit filters</i>)."
        " <b>Dot color and IV+pp both measure distance above/below this line</b>"
        " &mdash; green dot = IV-rich, red = IV-cheap."
        "<br>"
        "<b>Large outlined dot + number</b> = top pick;"
        " number matches rank in table below (1&nbsp;=&nbsp;strongest signal)."
        " Vertical dashed line = current spot price."
        "</div>",
        unsafe_allow_html=True,
    )
