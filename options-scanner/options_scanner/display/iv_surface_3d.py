"""Interactive 3D volatility surface for the Single Ticker tab.

The third "View" option on the Volatility surface chart (alongside
"Single expiration" and "All expirations"). Renders the whole chain as
a 3D shape — strike (x) × days-to-expiration (y) × IV % (z) — with:

- a translucent fitted-IV mesh (`go.Surface`) over a strike × DTE grid,
  clipped to the fit-supported strike range so we don't draw the
  spurious far-OTM/ITM extrapolation humps; and
- the raw per-contract IV as dots (`go.Scatter3d`) floating above/below
  the mesh, colored by IV+pp on the same red→gray→green diverging scale
  the 2D chart uses (green = IV-rich, red = IV-cheap in sell mode).

Drag-to-rotate / zoom / pan are built into Plotly. Mirrors the 2D
chart's "dots vs. fitted line" language in three dimensions.

`frame` must already carry the `_prep` display columns (FittedIV%, IV%,
IV+pp) plus strike / expiration / dte — i.e. the same frame the "All
expirations" branch builds in `iv_chart.show_iv_chart`.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Dark scene theme. Spot plane is fuchsia so it can't be mistaken for the
# Viridis surface (purple→teal→yellow) or the red↔green IV+pp dots.
_BG        = "#0b1220"   # paper + scene void
_WALL      = "#0f1a2e"   # axis backing panes
_GRID      = "#2b3a52"   # gridlines
_AXIS_FONT = "#cbd5e1"   # tick labels + axis titles
_TITLE     = "#e2e8f0"   # chart title + default font
_LABEL     = "#f8fafc"   # rank numbers floating above dots
_SPOT      = "#d946ef"   # spot plane (fuchsia)
_SPOT_TXT  = "#f0abfc"   # spot label text (light fuchsia)


def render_iv_surface_3d(frame: pd.DataFrame, spot: float, ticker: str,
                         mode: str, buy: bool = False,
                         fit_range: tuple[float, float] | None = None,
                         delta_range: tuple[float, float] | None = None,
                         min_oi: int = 0, min_vol: int = 0,
                         top_n: int = 0) -> None:
    """Render the 3D IV surface. No-op when there's no data to show.

    When `delta_range` is given and the frame has a `delta` column, an
    in-chart button group (next to the title) toggles between the delta
    band (default) and the full fitted chain — client-side, no rerun.

    `min_oi` / `min_vol` / `top_n` are display-only here — surfaced as a
    filter summary under the title so a screenshot is self-explanatory.
    """
    frame = frame.dropna(subset=["IV%", "strike", "dte"]).copy()
    if frame.empty:
        st.info("No chain data to render in 3D for this scan.")
        return
    frame = frame.sort_values(["expiration", "strike"])

    # Taller inline view for a closer look. Also makes Streamlit's native
    # fullscreen (the ⤢ icon at the chart's top-right on hover) actually
    # fill the window instead of showing a 560px chart in a big empty frame.
    expanded = st.toggle(
        "⤢ Expand", value=False, key=f"iv3d_expand_{ticker}",
        help="Render the surface taller. For true fullscreen, hover the "
             "chart and click the ⤢ icon at its top-right corner.",
    )

    # Diverging IV+pp color scale, matching the 2D chart (sell: green rich /
    # red cheap; buy flips). Saturation (cmax) is computed once below from the
    # in-fit contracts, so it's identical across both views.
    if buy:
        ivpp_scale = [[0.0, "#22c55e"], [0.5, "#cbd5e1"], [1.0, "#ef4444"]]
    else:
        ivpp_scale = [[0.0, "#ef4444"], [0.5, "#cbd5e1"], [1.0, "#22c55e"]]

    # Robust IV (z) band: clamp to ~p1–p99 so a couple of extreme-wing
    # contracts don't squash the surface into a thin flat sheet. Computed
    # per visible set, so the delta band gets a tighter vertical range than
    # the full chain — the axis retracks when the in-chart toggle flips.
    def _zrange(iv: pd.Series, min_span: float = 0.0) -> list[float]:
        iv = iv.dropna()
        if iv.empty:
            return [0.0, 1.0]
        lo = float(np.nanpercentile(iv, 1))
        hi = float(np.nanpercentile(iv, 99))
        if hi <= lo:
            lo, hi = float(iv.min()), float(iv.max())
        pad = max((hi - lo) * 0.08, 0.5)
        lo, hi = lo - pad, hi + pad
        # Don't let a tight band collapse the vertical so far that the fitted
        # surface reads as a steep ramp — floor the span at min_span, keeping
        # it centered on the band's data.
        if (hi - lo) < min_span:
            mid = (lo + hi) / 2.0
            lo, hi = mid - min_span / 2.0, mid + min_span / 2.0
        return [lo, hi]

    zr_full = _zrange(frame["IV%"])
    _full_span = zr_full[1] - zr_full[0]

    has_delta = (delta_range is not None and "delta" in frame.columns)
    if has_delta:
        _dlo, _dhi = delta_range
        filtered = frame[frame["delta"].abs().between(_dlo, _dhi)]
        if filtered.empty:        # band excludes everything → no toggle
            has_delta = False

    # Band view is the default; its tighter range is what the chart opens
    # with. zr_full drives the full-chain view and the spot plane extent.
    zr_band = (_zrange(filtered["IV%"], min_span=_full_span * 0.5)
               if has_delta else zr_full)

    # Color saturation from the well-behaved in-fit contracts — computed once
    # and shared by the surface and both views, so the central region reads
    # identically in the band and full-chain views. The deep-wing extrapolation
    # (|IV+pp| can hit ±60 on garbage ITM/OTM IV) no longer drives the scale.
    if "in_fit" in frame.columns and bool(frame["in_fit"].any()):
        _pp = frame.loc[frame["in_fit"], "IV+pp"].abs()
    else:
        _pp = frame["IV+pp"].abs()
    cmax = max(float(np.nanpercentile(_pp, 90)) if len(_pp) else 1.0, 1.0)

    hover = (
        "Strike $%{x:,.2~f}<br>DTE %{y}d<br>%{customdata[1]}"
        "<br>IV %{z:.1f}%  ·  IV+pp %{customdata[0]:+.1f}"
        "<br>Delta %{customdata[2]:.2f}"
        "<br>Bid $%{customdata[3]:.2f}  Ask $%{customdata[4]:.2f}"
        "<br>Mid $%{customdata[5]:.2f}  Last %{customdata[6]}"
        "<br>OI %{customdata[7]:,}  Vol %{customdata[8]:,}<extra></extra>"
    )

    def _chain_traces(sub: pd.DataFrame, visible: bool):
        """Build (mesh? + dots) traces for one frame; returns (list, mesh_ok)."""
        traces = []
        # `cmax` (the IV+pp color saturation) is computed once in the enclosing
        # scope from the in-fit contracts, so the scale is identical in both
        # views and on the surface.
        n_exp = sub["expiration"].nunique()
        n_strk = sub["strike"].nunique()
        mesh_ok = n_exp >= 2 and n_strk >= 3 and "FittedIV%" in sub.columns
        if mesh_ok:
            # Fitted surface from the in-fit anchors of the full frame — so it's
            # identical in the band and full-chain views and its gap-fill only
            # ever sees trustworthy contracts (no wing smear). Height = fitted
            # (expected) IV; color = IV+pp deviation (green rich, red cheap).
            # Out-of-fit dots simply float above/below it.
            fit_df = (frame[frame["in_fit"]] if "in_fit" in frame.columns
                      else frame).dropna(subset=["FittedIV%"])
            if fit_df.empty:
                fit_df = sub.dropna(subset=["FittedIV%"])

            def _grid(df, value):
                return df.pivot_table(index="dte", columns="strike",
                                      values=value, aggfunc="mean")

            def _fill(g):
                g = g.interpolate(axis=1).interpolate(axis=0)
                return (g.ffill(axis=1).bfill(axis=1)
                         .ffill(axis=0).bfill(axis=0))

            grid = _grid(fit_df, "FittedIV%")
            if grid.shape[0] >= 2 and grid.shape[1] >= 3:
                grid = _fill(grid)
                cgrid = _fill(
                    _grid(fit_df, "IV+pp").reindex(index=grid.index,
                                                   columns=grid.columns)
                ).clip(-cmax, cmax)
                traces.append(go.Surface(
                    x=grid.columns.values.astype(float),
                    y=grid.index.values, z=grid.values,
                    surfacecolor=cgrid.values, colorscale=ivpp_scale,
                    cmin=-cmax, cmax=cmax, opacity=0.9, showscale=False,
                    hoverinfo="skip", name="Fitted surface", visible=visible,
                    lighting=dict(ambient=0.6, diffuse=0.8, specular=0.12,
                                  roughness=0.6, fresnel=0.1),
                    lightposition=dict(x=10000, y=10000, z=8000),
                ))
            else:
                mesh_ok = False

        # Dots colored by IV+pp on the shared scale; Top-N picks get a bigger
        # marker (mirrors the 2D chart's outlined pick dots).
        def _dots(d: pd.DataFrame, colorscale, colorbar: bool):
            if d.empty:
                return None

            def col(name):
                return (d[name] if name in d.columns
                        else pd.Series([float("nan")] * len(d), index=d.index))

            exp_s = d["expiration"].apply(
                lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%b %d '%y"))
            last_s = col("last").apply(
                lambda v: f"${v:.2f}" if pd.notna(v) and v > 0 else "—")
            tops = (d["is_top"].to_numpy() if "is_top" in d.columns
                    else np.zeros(len(d), dtype=bool))
            mk = dict(
                size=np.where(tops, 9, 4), color=d["IV+pp"],
                colorscale=colorscale, cmin=-cmax, cmax=cmax,
                line=dict(width=0.5, color="#0f172a"),
            )
            if colorbar:
                mk["colorbar"] = dict(
                    title=dict(text="IV+pp", font=dict(color=_AXIS_FONT)),
                    tickfont=dict(color=_AXIS_FONT),
                    thickness=12, len=0.6, outlinecolor=_GRID,
                )
            return go.Scatter3d(
                x=d["strike"], y=d["dte"], z=d["IV%"], mode="markers", marker=mk,
                customdata=np.stack([
                    d["IV+pp"], exp_s, col("delta"), col("bid"), col("ask"),
                    col("mid"), last_s, col("open_interest"), col("volume"),
                ], axis=-1),
                hovertemplate=hover, name="Contracts", visible=visible,
            )

        _t = _dots(sub, ivpp_scale, colorbar=True)
        if _t is not None:
            traces.append(_t)

        is_top = (sub["is_top"].to_numpy() if "is_top" in sub.columns
                  else np.zeros(len(sub), dtype=bool))

        # Rank number floating just above each top pick's dot. Screen-space
        # "top center" keeps the label above the dot through any rotation.
        if is_top.any() and "rank_label" in sub.columns:
            top = sub[is_top]
            traces.append(go.Scatter3d(
                x=top["strike"], y=top["dte"], z=top["IV%"],
                mode="text", text=top["rank_label"].astype(str),
                textposition="top center",
                textfont=dict(color=_LABEL, size=13,
                              family="Arial Black, Arial, sans-serif"),
                hoverinfo="skip", name="Top picks", visible=visible,
            ))
        return traces, mesh_ok

    fig = go.Figure()

    # Build the chain trace set(s). With a delta band, build both (band default
    # visible, full hidden) so the in-chart button can swap them instantly.
    if has_delta:
        band_traces, mesh_ok = _chain_traces(filtered, visible=True)
        full_traces, _ = _chain_traces(frame, visible=False)
        for t in band_traces + full_traces:
            fig.add_trace(t)
        n_band, n_full = len(band_traces), len(full_traces)
    else:
        band_traces, mesh_ok = _chain_traces(frame, visible=True)
        for t in band_traces:
            fig.add_trace(t)
        n_band, n_full = len(band_traces), 0

    # ── Spot reference: a translucent vertical plane at x = spot ──────────────
    # A constant-x surface spanning the DTE (y) and IV (z) extents, with a
    # floating label denoting the spot price on the chart.
    spot_shown = spot and np.isfinite(spot)
    if spot_shown:
        y_lo, y_hi = float(frame["dte"].min()), float(frame["dte"].max())
        # Plane spans the full IV range so it stays tall enough for both
        # views; in the band view it's simply clipped to the tighter axis.
        z_lo, z_hi = zr_full
        yy = np.array([[y_lo, y_lo], [y_hi, y_hi]])
        zz = np.array([[z_lo, z_hi], [z_lo, z_hi]])
        xx = np.full((2, 2), float(spot))
        fig.add_trace(go.Surface(
            x=xx, y=yy, z=zz,
            showscale=False, opacity=0.25,
            colorscale=[[0, _SPOT], [1, _SPOT]],
            hoverinfo="skip", name="Spot",
        ))
        # Label sits at the default (band) view's top edge so it stays on
        # screen when the chart opens; near-strike, near-top of the plane.
        fig.add_trace(go.Scatter3d(
            x=[float(spot)], y=[y_hi], z=[zr_band[1]],
            mode="text", text=[f"Spot ${spot:,.2f}"],
            textposition="top center",
            textfont=dict(color=_SPOT_TXT, size=12),
            hoverinfo="skip", name="Spot label",
        ))

    n_spot = 2 if spot_shown else 0

    # In-chart toggle between the delta band and the full chain. Buttons set
    # the `visible` array across all traces (spot traces stay on for both).
    updatemenus = []
    if has_delta:
        band_vis = [True] * n_band + [False] * n_full + [True] * n_spot
        full_vis = [False] * n_band + [True] * n_full + [True] * n_spot
        updatemenus = [dict(
            type="buttons", direction="right",
            x=0.99, xanchor="right", y=1.0, yanchor="top",
            pad=dict(t=2, r=2), showactive=True,
            # Light buttons + dark text: the active button's highlight is
            # light, so light text on it was unreadable — dark text reads in
            # both the active and inactive states.
            bgcolor="rgba(248,250,252,0.95)", bordercolor="#94a3b8",
            font=dict(size=11, color="#0f172a"),
            buttons=[
                dict(label=f"Δ {_dlo:.2f}–{_dhi:.2f}", method="update",
                     args=[{"visible": band_vis},
                           {"scene.zaxis.range": zr_band}]),
                dict(label="Full chain", method="update",
                     args=[{"visible": full_vis},
                           {"scene.zaxis.range": zr_full}]),
            ],
        )]

    type_word = {"call": "calls", "put": "puts", "both": "options"}[mode]
    subj = f"{ticker} {type_word}" if ticker else type_word

    # One-line filter summary under the title so a screenshot explains the
    # slice of the chain being shown (action, delta band, DTE span, OI/Vol
    # floors, pick count).
    _bits = ["Buying" if buy else "Selling"]
    if delta_range is not None:
        _bits.append(f"Δ {delta_range[0]:.2f}–{delta_range[1]:.2f}")
    if "dte" in frame.columns and not frame["dte"].empty:
        _bits.append(f"DTE {int(frame['dte'].min())}–{int(frame['dte'].max())}")
    if min_oi:
        _bits.append(f"OI≥{min_oi}")
    if min_vol:
        _bits.append(f"Vol≥{min_vol}")
    if top_n:
        _bits.append(f"top {top_n}")
    _filter_summary = "  ·  ".join(_bits)
    # Inline to the right of the title: smaller, lighter span after a gap.
    _title_html = (
        f"{subj} — IV surface (3D)"
        f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='font-size:13px;"
        f"color:{_AXIS_FONT}'>{_filter_summary}</span>"
    )

    # Reusable dark-axis styling for all three scene axes.
    def _axis(title):
        return dict(
            title=dict(text=title, font=dict(color=_AXIS_FONT)),
            backgroundcolor=_WALL, showbackground=True,
            gridcolor=_GRID, zerolinecolor=_GRID,
            tickfont=dict(color=_AXIS_FONT),
        )

    fig.update_layout(
        height=860 if expanded else 560,
        margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor=_BG,
        font=dict(color=_TITLE),
        title=dict(text=_title_html, x=0.01,
                   y=0.98, yanchor="top",
                   font=dict(size=16, color=_TITLE)),
        scene=dict(
            domain=dict(y=[0.0, 1.0]),
            bgcolor=_BG,
            xaxis=_axis("Strike"),
            yaxis=_axis("DTE"),
            zaxis={**_axis("IV (%)"), "range": zr_band},
            # Stretch the vertical relative to the strike×DTE footprint so the
            # surface's curvature is visible instead of pancake-flat.
            aspectmode="manual",
            aspectratio=dict(x=1.5, y=1.4, z=1.0),
            camera=dict(eye=dict(x=1.6, y=-1.6, z=0.8)),
        ),
        showlegend=False,
        updatemenus=updatemenus,
    )
    st.plotly_chart(fig, use_container_width=True)

    note = ("Strike × DTE × IV. Dots are actual contract IV, colored by "
            "IV+pp (green rich, red cheap). ")
    note += ("The surface is the fitted (expected) IV, tinted the same way — "
             "green where actual IV runs above it, red where below. "
             if mesh_ok else
             "The fitted surface is hidden (needs ≥2 expirations and ≥3 "
             "strikes). ")
    if "is_top" in frame.columns and bool(frame["is_top"].any()):
        note += ("Numbered, enlarged dots are the top picks — the number "
                 "matches the table rank (1 = strongest signal). ")
    if spot_shown:
        note += f"Vertical plane = spot (${spot:,.2f}). "
    note += "Drag to rotate, scroll to zoom."
    st.caption(note)
