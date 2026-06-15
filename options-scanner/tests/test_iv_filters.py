"""Tests for the surface-fit filter registry.

Focused on the exclude_earnings filter (the LGbengs critique #2
addition); the older filters are exercised indirectly through the
surface-fit and chain tests.
"""

import pandas as pd

from options_scanner import iv_filters


def _df():
    return pd.DataFrame({
        "type": ["call", "call", "put", "put"],
        "strike": [105.0, 110.0, 95.0, 90.0],
        "spot": [100.0] * 4,
        "bid": [1.0, 1.0, 1.0, 1.0],
        "ask": [1.05, 1.05, 1.05, 1.05],
        "delta": [0.4, 0.3, -0.4, -0.3],
        "open_interest": [500, 500, 500, 500],
        "iv": [0.30, 0.30, 0.30, 0.30],
        "earnings_count": [0, 2, 0, 1],
    })


def test_exclude_earnings_drops_earnings_spanning_rows():
    out = iv_filters.apply(_df(), (("exclude_earnings", frozenset()),))
    assert list(out["earnings_count"]) == [0, 0]
    assert len(out) == 2


def test_exclude_earnings_noop_without_column():
    df = _df().drop(columns=["earnings_count"])
    out = iv_filters.apply(df, (("exclude_earnings", frozenset()),))
    assert len(out) == len(df)


def test_exclude_earnings_registered_and_labeled():
    assert "exclude_earnings" in iv_filters.REGISTRY
    assert iv_filters.REGISTRY["exclude_earnings"]["label"]


def test_empty_config_is_identity():
    df = _df()
    assert len(iv_filters.apply(df, ())) == len(df)


def test_default_config_includes_exclude_earnings():
    """exclude_earnings joined the default filter set 2026-06-10 (DTE-gated
    2026-06-15)."""
    names = [n for n, _ in iv_filters.DEFAULT_CONFIG]
    assert "exclude_earnings" in names


def test_exclude_earnings_dte_gate_keeps_long_dated():
    """Only short-dated earnings-spanners are dropped; long-dated stay in."""
    import pandas as pd
    df = pd.DataFrame({
        "earnings_count": [1, 1, 0],
        "dte": [30, 200, 200],   # short spanner, long spanner, long clean
    })
    out = iv_filters.apply(
        df, (("exclude_earnings", frozenset({("max_dte", 60)})),))
    # The 30-DTE spanner is dropped; both 200-DTE rows survive.
    assert sorted(out["dte"].tolist()) == [200, 200]


def test_exclude_earnings_guard_never_empties_fit():
    """If every row is a short earnings-spanner, keep them rather than wipe."""
    import pandas as pd
    df = pd.DataFrame({"earnings_count": [1, 2], "dte": [20, 40]})
    out = iv_filters.apply(
        df, (("exclude_earnings", frozenset({("max_dte", 60)})),))
    assert len(out) == 2  # guard returned the input rather than empty


# ── sanity + with_sanity ─────────────────────────────────────────────────────

def test_sanity_drops_junk_iv_and_expired_rows():
    df = _df().assign(iv=[0.30, 0.005, 6.0, 0.30], dte=[30, 30, 30, 0])
    out = iv_filters.apply(df, (("sanity", frozenset()),))
    assert list(out.index) == [0]


def test_with_sanity_prepends_once():
    config = (("otm_only", frozenset()),)
    once = iv_filters.with_sanity(config)
    assert once[0][0] == "sanity" and len(once) == 2
    assert iv_filters.with_sanity(once) == once


# ── fresh_quotes ─────────────────────────────────────────────────────────────

def test_fresh_quotes_drops_only_known_stale_rows():
    df = _df().assign(
        last_trade_days=[0.5, 10.0, 10.0, float("nan")],
        volume=[0, 0, 25, 0],
    )
    out = iv_filters.apply(df, (("fresh_quotes", frozenset()),))
    # Kept: traded recently / traded today / unknown age. Dropped: row 1.
    assert list(out.index) == [0, 2, 3]


def test_fresh_quotes_noop_without_column():
    df = _df()
    out = iv_filters.apply(df, (("fresh_quotes", frozenset()),))
    assert len(out) == len(df)


# ── funnel ────────────────────────────────────────────────────────────────────

def test_funnel_final_remaining_matches_apply():
    df = _df()
    config = (("otm_only", frozenset()),
              ("delta_range", frozenset({("lo", 0.0), ("hi", 0.35)})))
    stages = iv_filters.funnel(df, config)
    assert stages[-1][1] == len(iv_filters.apply(df, config))


def test_funnel_labels_from_registry():
    stages = iv_filters.funnel(_df(), (("otm_only", frozenset()),))
    assert stages[0][0] == iv_filters.REGISTRY["otm_only"]["label"]


def test_funnel_remaining_and_dropped_reconcile():
    df = _df()
    config = (("otm_only", frozenset()),
              ("spread_pct", frozenset({("max_pct", 0.50)})),
              ("delta_range", frozenset({("lo", 0.0), ("hi", 0.35)})))
    prev = len(df)
    for _label, remaining, dropped in iv_filters.funnel(df, config):
        assert remaining + dropped == prev
        prev = remaining


def test_funnel_skips_unknown_filter():
    stages = iv_filters.funnel(
        _df(), (("nope", frozenset()), ("otm_only", frozenset())))
    assert len(stages) == 1
    assert stages[0][0] == iv_filters.REGISTRY["otm_only"]["label"]


def test_funnel_empty_config_has_no_stages():
    assert iv_filters.funnel(_df(), ()) == []
