"""Fetch upcoming earnings dates and annotate the option chain."""

import logging
from datetime import date

import pandas as pd

from stocks_shared.yahoo import normalize_ticker

log = logging.getLogger(__name__)


def _nearest_future(dates) -> list:
    """Return [nearest upcoming date] from an iterable, or [] if none.

    We keep only the next event: data sources return several future
    quarters, but only the nearest is company-confirmed — the rest are
    estimated from the historical cadence, so treating them as real
    conveys false precision.
    """
    today = date.today()
    future = []
    for d in dates:
        try:
            d2 = d.date() if hasattr(d, "date") else d
            if d2 >= today:
                future.append(d2)
        except Exception:
            pass
    return [min(future)] if future else []


def fetch_earnings_dates(ticker: str) -> list:
    """Return the next upcoming earnings date as a 0- or 1-element list.

    Deliberately just the *nearest* event (see `_nearest_future`) — the
    whole pipeline treats earnings as a single upcoming event, never a
    count of how many fall before an expiration.
    """
    try:
        import yfinance as yf
        ticker = normalize_ticker(ticker)
        t = yf.Ticker(ticker)

        # Approach 1: get_earnings_dates() — most reliable in recent yfinance
        try:
            ed = t.get_earnings_dates(limit=8)
            if ed is not None and not ed.empty:
                out = _nearest_future(ed.index)
                if out:
                    return out
        except Exception:
            pass

        # Approach 2: calendar dict/DataFrame
        try:
            cal = t.calendar
            if cal is not None:
                raw = None
                if isinstance(cal, dict):
                    raw = cal.get("Earnings Date")
                elif hasattr(cal, "index") and "Earnings Date" in cal.index:
                    raw = cal.loc["Earnings Date"]
                if raw is not None:
                    dates = (list(raw) if hasattr(raw, "__iter__")
                             and not isinstance(raw, str) else [raw])
                    out = _nearest_future(dates)
                    if out:
                        return out
        except Exception:
            pass

        # Approach 3: earnings_dates property fallback
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                out = _nearest_future(ed.index)
                if out:
                    return out
        except Exception:
            pass

    except Exception as exc:
        log.warning("Could not fetch earnings dates: %s", exc)

    return []


def annotate_earnings(df: pd.DataFrame, earnings_dates: list) -> pd.DataFrame:
    """Add earnings_count: 1 if the next earnings falls before an expiration,
    else 0.

    `earnings_dates` holds only the nearest event, so this is a 0/1 flag, not
    a tally — the column name is kept for back-compat with the surface-fit
    filter and the result tables that read it.
    """
    if df.empty:
        return df

    today = date.today()

    def _spans(exp_str: str) -> int:
        exp = date.fromisoformat(exp_str)
        return int(any(today < d <= exp for d in earnings_dates))

    df = df.copy()
    df["earnings_count"] = df["expiration"].apply(_spans)
    return df
