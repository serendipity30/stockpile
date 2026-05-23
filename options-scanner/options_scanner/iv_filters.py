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


def _delta_range(df: pd.DataFrame, lo: float = 0.05, hi: float = 0.95) -> pd.DataFrame:
    """Keep options with |delta| in [lo, hi]."""
    if "delta" not in df.columns:
        return df
    return df[df["delta"].abs().between(lo, hi)]


def _min_oi(df: pd.DataFrame, min_oi: int = 1) -> pd.DataFrame:
    """Require minimum open interest."""
    return df[df["open_interest"] >= min_oi]


# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, dict] = {
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
        "defaults": {"lo": 0.05, "hi": 0.95},
        "label":    "Delta range",
    },
    "min_oi": {
        "fn":       _min_oi,
        "defaults": {"min_oi": 1},
        "label":    "Min OI for fit",
    },
}

# Default: OTM-only + spread ≤ 50% + delta 0.05–0.95
DEFAULT_CONFIG: SurfaceFilterConfig = (
    ("otm_only",    frozenset()),
    ("spread_pct",  frozenset({("max_pct", 0.50)})),
    ("delta_range", frozenset({("lo", 0.05), ("hi", 0.95)})),
)


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
