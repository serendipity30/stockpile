"""Surface fit filter registry for iv_surface.compute_iv_excess.

Each filter narrows the set of options used in the least-squares
regression. All options in the chain still receive iv_fitted and
iv_excess values (extrapolated from the cleaner fit); only the
regression itself is filtered.

SurfaceFilterConfig is a tuple of (name, frozenset-of-kwargs) pairs.
The frozenset makes it hashable for Streamlit's st.cache_data.
Order is preserved so filters apply in the sequence specified.

Adding a new filter
-------------------
1. Write a function (df: pd.DataFrame, **kwargs) -> pd.DataFrame
2. Add an entry to REGISTRY with fn, defaults, and label
3. It appears automatically in the UI expander
"""

from __future__ import annotations

import pandas as pd

# Hashable filter config: tuple of (filter_name, frozenset({(kwarg, val), ...}))
SurfaceFilterConfig = tuple[tuple[str, frozenset], ...]


# ── Filter functions ──────────────────────────────────────────────────────────

def _sanity(df: pd.DataFrame, iv_floor: float = 0.02,
            iv_ceiling: float = 5.0) -> pd.DataFrame:
    """Baseline validity: IV above the noise floor and below an
    absurdity ceiling (yfinance occasionally emits 500%+ junk), DTE > 0.

    Always prepended to the surface pipeline via `with_sanity` — it
    lives in the registry (rather than hard-coded in iv_surface) so
    the diagnostics funnel reports its drop count like any other stage.
    """
    return df[(df["iv"] > iv_floor) & (df["iv"] < iv_ceiling)
              & (df["dte"] > 0)]


def _fresh_quotes(df: pd.DataFrame, max_age_days: float = 3.0) -> pd.DataFrame:
    """Drop rows whose last trade is older than max_age_days and that
    show no volume today — their broker IV is likely stale.

    Rows with unknown age (Schwab/moomoo don't populate
    last_trade_days) pass through: only known-stale quotes are dropped.
    """
    if "last_trade_days" not in df.columns:
        return df
    age = df["last_trade_days"]
    traded_today = df["volume"] > 0 if "volume" in df.columns else False
    return df[age.isna() | (age <= max_age_days) | traded_today]


def _otm_only(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only OTM options: calls where K > spot, puts where K < spot."""
    calls = (df["type"] == "call") & (df["strike"] > df["spot"])
    puts  = (df["type"] == "put")  & (df["strike"] < df["spot"])
    return df[calls | puts]


def _spread_pct(df: pd.DataFrame, max_pct: float = 0.50) -> pd.DataFrame:
    """Remove options where (ask - bid) / mid > max_pct."""
    mid    = (df["bid"] + df["ask"]) / 2
    spread = (df["ask"] - df["bid"]) / mid.replace(0, float("nan"))
    return df[spread.fillna(float("inf")) <= max_pct]


def _delta_range(df: pd.DataFrame, lo: float = 0.10, hi: float = 0.95) -> pd.DataFrame:
    """Keep options with |delta| in [lo, hi]."""
    if "delta" not in df.columns:
        return df
    return df[df["delta"].abs().between(lo, hi)]


def _min_oi(df: pd.DataFrame, min_oi: int = 1) -> pd.DataFrame:
    """Require minimum open interest."""
    return df[df["open_interest"] >= min_oi]


def _exclude_earnings(df: pd.DataFrame, max_dte: int = 60) -> pd.DataFrame:
    """Drop only *short-dated* options that span an upcoming earnings event.

    Earnings inject a roughly fixed jump variance. For a short-dated option
    spanning the next print, that jump is a large share of its total
    variance, so its IV is genuinely inflated and would pull the fitted
    surface up — keep it out of the regression. For longer-dated options the
    same jump is a tiny share of variance, so it barely moves their IV;
    excluding them (the old "earnings_count > 0" rule, regardless of DTE)
    needlessly thinned — and at long DTE *emptied* — the fit, collapsing
    IV+pp to ≈ 0. So we only exclude when DTE <= `max_dte`.

    Excluded rows still receive iv_fitted/iv_excess from the cleaner fit
    (their earnings premium shows up as positive excess), and the UI marks
    earnings-spanning contracts so nothing is hidden.

    Guard: never let this filter empty the fit subset — if every remaining
    row is a short earnings-spanner, keep them rather than collapse the fit.
    """
    if "earnings_count" not in df.columns:
        return df
    spans = df["earnings_count"].fillna(0) >= 1
    short = df["dte"] <= max_dte if "dte" in df.columns else True
    kept = df[~(spans & short)]
    return kept if not kept.empty else df


# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, dict] = {
    "sanity": {
        "fn":       _sanity,
        "defaults": {"iv_floor": 0.02, "iv_ceiling": 5.0},
        "label":    "IV in (2%, 500%) and DTE > 0",
    },
    "fresh_quotes": {
        "fn":       _fresh_quotes,
        "defaults": {"max_age_days": 3.0},
        "label":    "Fresh quotes — traded recently",
    },
    "otm_only": {
        "fn":       _otm_only,
        "defaults": {},
        "label":    "OTM only — calls K > S, puts K < S",
    },
    "spread_pct": {
        "fn":       _spread_pct,
        "defaults": {"max_pct": 0.50},
        "label":    "Spread ≤ % of mid",
    },
    "delta_range": {
        "fn":       _delta_range,
        "defaults": {"lo": 0.10, "hi": 0.95},
        "label":    "Delta range",
    },
    "min_oi": {
        "fn":       _min_oi,
        "defaults": {"min_oi": 1},
        "label":    "Min OI for fit",
    },
    "exclude_earnings": {
        "fn":       _exclude_earnings,
        "defaults": {"max_dte": 60},
        "label":    "Exclude short-dated earnings-spanning options (≤ max DTE)",
    },
}

# Default: OTM-only + spread ≤ 50% + delta 0.10–0.95 + earnings
# excluded. The 0.10 floor drops far-OTM wings (penny premium, wide
# spreads, unreliable broker IV) that otherwise dominate the surface
# curvature; 0.95 is a guard for the non-default case where OTM-only
# is off (it never binds while OTM-only caps |delta| near 0.5).
# exclude_earnings joined the defaults 2026-06-10: short-dated
# earnings-spanning contracts carry jump premium that pulls the surface up
# and distorts every other contract's excess (they still receive
# iv_fitted/iv_excess from the cleaner fit). It is DTE-gated (≤ 60d) as of
# 2026-06-15 so long-dated contracts — where one earnings is a negligible
# share of variance — stay in the fit instead of emptying it.
DEFAULT_CONFIG: SurfaceFilterConfig = (
    ("otm_only",         frozenset()),
    ("spread_pct",       frozenset({("max_pct", 0.50)})),
    ("delta_range",      frozenset({("lo", 0.10), ("hi", 0.95)})),
    ("exclude_earnings", frozenset({("max_dte", 60)})),
)


def with_sanity(config: SurfaceFilterConfig) -> SurfaceFilterConfig:
    """Prepend the always-on sanity filter unless already present.

    The surface pipeline (and its diagnostics funnel) route every
    config through this, so the baseline-validity stage is applied —
    and reported — exactly once, however the config was built.
    """
    if any(name == "sanity" for name, _ in config):
        return config
    return (("sanity", frozenset()),) + tuple(config)


# ── Apply ─────────────────────────────────────────────────────────────────────

def apply(df: pd.DataFrame, config: SurfaceFilterConfig) -> pd.DataFrame:
    """Apply filters in order. Returns the subset to use for regression."""
    result = df
    for name, kwargs_fs in config:
        if name not in REGISTRY:
            continue
        entry  = REGISTRY[name]
        kwargs = {**entry["defaults"], **dict(kwargs_fs)}
        result = entry["fn"](result, **kwargs)
    return result


def funnel(df: pd.DataFrame,
           config: SurfaceFilterConfig) -> list[tuple[str, int, int]]:
    """Replay the filter chain, recording (label, remaining, dropped) per stage.

    Mirrors `apply` step-for-step — same loop body, same skip rule — so
    the reported counts can never drift from the real fit subset. `label`
    is the registry label; `remaining` is the row count after that stage
    and `dropped` is how many that stage removed. Unknown filter names are
    skipped (as in `apply`) and produce no row.
    """
    result = df
    stages: list[tuple[str, int, int]] = []
    for name, kwargs_fs in config:
        if name not in REGISTRY:
            continue
        entry  = REGISTRY[name]
        kwargs = {**entry["defaults"], **dict(kwargs_fs)}
        before = len(result)
        result = entry["fn"](result, **kwargs)
        stages.append((entry["label"], len(result), before - len(result)))
    return stages
