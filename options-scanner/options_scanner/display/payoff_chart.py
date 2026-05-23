"""Interactive Plotly payoff diagram for a selected spread row.

Renders the at-expiration P&L curve (intrinsic value) plus a Current P&L
curve (Black-Scholes mark-to-model) that responds to two user controls:

- **IV adjustment slider** scales every leg's IV. Useful for sanity-checking
  an IV-expansion or IV-crush scenario.
- **Days forward slider** moves the valuation date forward. As days pass
  the Current line collapses toward the At Expiration line.

Visual furniture:
- Color-coded leg badges (green "Buy" / red "Sell") at each strike
- Vertical dashed lines at each strike, spot, and breakevens
- 1σ/2σ probability cone at expiration (lightly shaded vertical bands)
- Stats footer below the chart with POP / Max P&L / BE / Greeks

Called from `options_scanner.tabs.spreads._render_spreads_view` when the
user clicks a row in the ranked spread table. The caller passes
`key_prefix` to scope each tab's slider state so adjusting IV in the
Spreads tab doesn't reset sliders in Neutral.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

# ── Public helpers ───────────────────────────────────────────────────────────


def safe_be(val) -> float | None:
    """Coerce to a positive finite float, or None if not numeric/finite."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


_GREEK_HELP = {
    "Δ": "Net delta — directional exposure. Near 0 = delta-neutral.",
    "θ": "Net daily theta — premium earned (positive) or paid (negative) per day.",
    "ν": "Net vega — P&L per 1-point rise in IV. Positive = benefits from IV expansion.",
}


# ── Plotly figure builder ────────────────────────────────────────────────────


def _build_payoff_figure(
    row: pd.Series,
    data: pd.DataFrame,
    legs: list[dict],
    spot: float,
    dte: int,
    days_fwd: int,
    iv_mult: float,
):
    """Build the Plotly Figure: fills, prob cone, lines, leg/spot/BE markers."""
    import plotly.graph_objects as go

    fig = go.Figure()

    # ── 1. Green/red background fills on the Expiration curve ──────────────
    fig.add_trace(go.Scatter(
        x=data["price"], y=data["pl_expiry"].clip(lower=0),
        mode="lines", line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(34,197,94,0.18)",
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=data["price"], y=data["pl_expiry"].clip(upper=0),
        mode="lines", line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(239,68,68,0.18)",
        showlegend=False, hoverinfo="skip",
    ))

    # ── 2. Probability cone (1σ + 2σ bands at expiration) ──────────────────
    T_to_expiry = max(dte, 1) / 365.0
    iv_avg = float(np.mean([leg["iv"] for leg in legs])) if legs else 0.0
    if iv_avg > 0:
        sigma_T = iv_avg * math.sqrt(T_to_expiry)
        one_lo = spot * math.exp(-sigma_T)
        one_hi = spot * math.exp(+sigma_T)
        two_lo = spot * math.exp(-2 * sigma_T)
        two_hi = spot * math.exp(+2 * sigma_T)
        # Outer 2σ band (lighter)
        fig.add_shape(type="rect", xref="x", yref="paper",
                      x0=two_lo, x1=one_lo, y0=0, y1=1,
                      fillcolor="rgba(99,102,241,0.07)",
                      line=dict(width=0), layer="below")
        fig.add_shape(type="rect", xref="x", yref="paper",
                      x0=one_hi, x1=two_hi, y0=0, y1=1,
                      fillcolor="rgba(99,102,241,0.07)",
                      line=dict(width=0), layer="below")
        # Inner 1σ band (slightly darker)
        fig.add_shape(type="rect", xref="x", yref="paper",
                      x0=one_lo, x1=one_hi, y0=0, y1=1,
                      fillcolor="rgba(99,102,241,0.10)",
                      line=dict(width=0), layer="below")

    # ── 3. Zero P/L line ───────────────────────────────────────────────────
    fig.add_hline(y=0, line=dict(color="#475569", dash="dot", width=1))

    # ── 4. Expiration P/L (solid dark) ─────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=data["price"], y=data["pl_expiry"],
        mode="lines", name="At Expiration",
        line=dict(color="#0f172a", width=2.5),
        hovertemplate="Price $%{x:.2f}<br>Expiry P/L $%{y:+.2f}<extra></extra>",
    ))

    # ── 5. Current P/L (dashed gray, IV/days-adjusted) ─────────────────────
    current_label = f"Current (+{days_fwd}d, {iv_mult:.2f}× IV)"
    fig.add_trace(go.Scatter(
        x=data["price"], y=data["pl_current"],
        mode="lines", name=current_label,
        line=dict(color="#64748b", width=2, dash="dash"),
        hovertemplate="Price $%{x:.2f}<br>Current P/L $%{y:+.2f}<extra></extra>",
    ))

    # ── 6. Spot marker ─────────────────────────────────────────────────────
    fig.add_vline(x=spot, line=dict(color="#0f172a", dash="dash", width=1.5))
    fig.add_annotation(
        x=spot, y=1.02, yref="paper", xref="x",
        text=f"<b>Spot ${spot:.2f}</b>", showarrow=False,
        font=dict(size=11, color="#0f172a"),
        bgcolor="rgba(255,255,255,0.85)", borderpad=3,
    )

    # ── 7. Per-leg strike markers (Buy/Sell badges) ────────────────────────
    y_max = float(max(data["pl_expiry"].max(), data["pl_current"].max()))
    y_min = float(min(data["pl_expiry"].min(), data["pl_current"].min()))
    y_span = max(y_max - y_min, 1.0)
    for i, leg in enumerate(legs):
        qty = leg["qty"]
        K = leg["strike"]
        ot = leg["type"]
        label_text = ("Buy" if qty > 0 else "Sell") + f" {K:g}{ot[0].upper()}"
        color = "#16a34a" if qty > 0 else "#dc2626"
        fig.add_vline(x=K, line=dict(color=color, dash="dot", width=1))
        # Stagger badges: longs high, shorts low; rotate per-leg index
        if qty > 0:
            y_anno = y_max - y_span * 0.05 - (i % 2) * y_span * 0.08
        else:
            y_anno = y_min + y_span * 0.10 + (i % 2) * y_span * 0.08
        fig.add_annotation(
            x=K, y=y_anno, xref="x", yref="y",
            text=f"<b>{label_text}</b>", showarrow=False,
            font=dict(size=10, color="white"),
            bgcolor=color, borderpad=4, bordercolor=color,
        )

    # ── 8. Breakeven lines ─────────────────────────────────────────────────
    for be_col in ("breakeven1", "breakeven2"):
        be_f = safe_be(row.get(be_col))
        if be_f is None:
            continue
        fig.add_vline(
            x=be_f, line=dict(color="#f97316", dash="dash", width=1.5),
            annotation_text=f"BE ${be_f:.2f}",
            annotation_position="bottom right",
            annotation_font=dict(size=10, color="#f97316"),
        )

    # ── 9. Layout ──────────────────────────────────────────────────────────
    strategy = row.get("strategy", "Spread")
    exp = row.get("expiration", "")
    title_text = f"<b>{strategy}</b> — {exp} — POP {float(row.get('pop', 0)):.0%}"
    fig.update_layout(
        title=dict(text=title_text, font=dict(size=14, color="#0f172a"),
                   x=0, xanchor="left"),
        height=440,
        hovermode="x unified",
        xaxis=dict(
            title="Stock Price", tickprefix="$", tickformat=",.0f",
            showgrid=True, gridcolor="rgba(148,163,184,0.25)",
        ),
        yaxis=dict(
            title="P/L per share ($)", tickprefix="$", tickformat="+.2f",
            showgrid=True, gridcolor="rgba(148,163,184,0.25)",
            zeroline=False,
        ),
        plot_bgcolor="rgba(255,255,255,0)",
        paper_bgcolor="rgba(255,255,255,0)",
        legend=dict(orientation="h", yanchor="top", y=1.12,
                    xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=60, r=20, t=80, b=50),
    )
    return fig


# ── Stats footer ─────────────────────────────────────────────────────────────


def _show_payoff_footer(row: pd.Series, dte: int) -> None:
    """Render compact stats below the payoff chart."""
    cols = st.columns(8)
    pop = float(row.get("pop", 0))
    cols[0].metric("POP", f"{pop * 100:.1f}%")
    cols[1].metric("Max Profit", f"${float(row['max_profit']):+.2f}")
    cols[2].metric("Max Loss", f"${-float(row['max_loss']):+.2f}")
    be1 = safe_be(row.get("breakeven1"))
    cols[3].metric("BE₁", f"${be1:.2f}" if be1 is not None else "—")
    cols[4].metric("Δ", f"{float(row['net_delta']):+.3f}",
                   help=_GREEK_HELP["Δ"])
    cols[5].metric("θ", f"{float(row['net_theta']):+.4f}",
                   help=_GREEK_HELP["θ"])
    cols[6].metric("γ", f"{float(row['net_gamma']):.4f}",
                   help="Net gamma — rate of change of net delta as spot moves.")
    cols[7].metric("ν", f"{float(row['net_vega']):+.3f}",
                   help=_GREEK_HELP["ν"])

    extras = [f"DTE: {dte}"]
    be2 = safe_be(row.get("breakeven2"))
    if be2 is not None:
        extras.insert(0, f"BE₂: ${be2:.2f}")
    extras.append(f"EV: ${float(row.get('expected_value', 0)):+.2f}")
    extras.append(f"Ann%: {float(row.get('ann_yield_pct', 0)):.1f}%")
    st.caption("    ".join(extras))


# ── Public entrypoint ────────────────────────────────────────────────────────


def show_payoff_chart(
    row: pd.Series,
    spot: float,
    key_prefix: str = "po",
) -> None:
    """Render the interactive Plotly P&L curve for a selected spread row.

    Args:
        row: One row from the ranked spreads DataFrame; must carry
            strategy/expiration/dte/pop/breakeven*/net_* fields.
        spot: Current underlying spot, drawn as a dashed vertical
            reference.
        key_prefix: Unique session-state prefix so each tab/strategy
            owns its own slider state (e.g. "sp_Bull_Put_Spread").
    """
    # spreads.* live below run_app.py's sys.path entry — inline import
    # keeps cold-start cheap and avoids a top-level cycle while display/
    # is being assembled.
    from options_scanner.spreads import build_legs_from_row, spread_payoff_data

    legs = build_legs_from_row(row)
    if not legs:
        return
    dte = max(int(row["dte"]), 1)

    # ── Sliders ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 0.5])
    with c1:
        iv_mult = st.slider(
            "IV adjustment", 0.50, 2.00, 1.00, 0.05,
            key=f"{key_prefix}_iv_mult",
            help="Scale all leg IVs by this factor for the Current P/L curve. "
                 "1.00 = current IV; >1 simulates an IV expansion; <1 a crush.",
        )
    with c2:
        days_fwd = st.slider(
            "Days forward (time decay)", 0, max(dte - 1, 0), 0, 1,
            key=f"{key_prefix}_days_fwd",
            help="Move the valuation date forward. As days pass the Current "
                 "P/L curve collapses toward the At Expiration curve.",
        )
    with c3:
        st.write("")  # vertical spacer to align the button
        if st.button("Reset", key=f"{key_prefix}_reset",
                     use_container_width=True):
            for k in (f"{key_prefix}_iv_mult", f"{key_prefix}_days_fwd"):
                st.session_state.pop(k, None)
            st.rerun()

    T_sim = max(dte - days_fwd, 1) / 365.0
    data = spread_payoff_data(legs, spot, T_sim, iv_multiplier=iv_mult)

    fig = _build_payoff_figure(row, data, legs, spot, dte, days_fwd, iv_mult)
    st.plotly_chart(fig, use_container_width=True, theme=None,
                    key=f"{key_prefix}_fig")

    _show_payoff_footer(row, dte)
