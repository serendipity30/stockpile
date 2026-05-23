"""Fit a 2-D IV surface and compute per-option IV excess.

Surface model: IV ≈ a + b·m + c·m² + d·√T + e·m·√T
where m = log(K/S) and T = DTE/365.

The regression is run only on options that pass the surface filter
pipeline (see iv_filters.py). By default this is OTM-only + spread
≤ 50% + |delta| 0.05–0.95, which excludes deep-ITM/OTM options whose
IVs are distorted by put-call parity and low liquidity. All options
still receive iv_fitted and iv_excess; only the fit itself is filtered.

Options sitting above the surface are priced rich — good candidates
to sell.
"""

import numpy as np
import pandas as pd

from options_scanner.iv_filters import (
    DEFAULT_CONFIG, SurfaceFilterConfig, apply as _apply_filters,
)


def compute_iv_excess(
    df: pd.DataFrame,
    surface_filters: SurfaceFilterConfig | None = None,
) -> pd.DataFrame:
    """Add iv_fitted and iv_excess columns to the chain DataFrame.

    surface_filters selects which rows participate in the regression.
    All rows still receive iv_fitted / iv_excess values. Defaults to
    iv_filters.DEFAULT_CONFIG when None.
    """
    if surface_filters is None:
        surface_filters = DEFAULT_CONFIG

    df = df.copy()

    valid = df[(df["iv"] > 0.02) & (df["dte"] > 0)]
    valid = _apply_filters(valid, surface_filters)
    if len(valid) < 5:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m = valid["log_moneyness"].values
    sqrt_T = np.sqrt(valid["dte"].values / 365.0)
    iv = valid["iv"].values

    X = np.column_stack([
        np.ones_like(m),
        m,
        m ** 2,
        sqrt_T,
        m * sqrt_T,
    ])

    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, iv, rcond=None)
    except np.linalg.LinAlgError:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m_all = df["log_moneyness"].values
    sqrt_T_all = np.sqrt(df["dte"].values / 365.0)
    X_all = np.column_stack([
        np.ones_like(m_all),
        m_all,
        m_all ** 2,
        sqrt_T_all,
        m_all * sqrt_T_all,
    ])

    df["iv_fitted"] = X_all @ coeffs
    df["iv_excess"] = df["iv"] - df["iv_fitted"]
    return df
