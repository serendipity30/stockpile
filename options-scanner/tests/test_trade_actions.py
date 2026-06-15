"""Tests for the assisted put-selling logic (pure functions)."""

import pytest

from options_scanner import trade_actions as ta


# ── tick rounding ────────────────────────────────────────────────────────────

def test_tick_for_split_at_three_dollars():
    assert ta.tick_for(2.99) == 0.01
    assert ta.tick_for(3.00) == 0.05
    assert ta.tick_for(7.5) == 0.05


def test_round_to_tick():
    assert ta.round_to_tick(2.453) == 2.45   # penny tick below $3
    assert ta.round_to_tick(5.27) == 5.25    # nickel tick at/above $3
    assert ta.round_to_tick(5.28) == 5.30


# ── fill-quality assessment ──────────────────────────────────────────────────

def test_assess_fill_liquid_uses_mid():
    a = ta.assess_fill(bid=2.40, ask=2.50, mid=2.45, volume=300,
                       open_interest=1800)
    assert a.liquid is True
    assert a.reasons == []
    assert a.suggested_limit == 2.45


def test_assess_fill_wide_and_thin_flags_both():
    a = ta.assess_fill(bid=1.00, ask=1.80, mid=1.40, volume=0, open_interest=12)
    assert a.liquid is False
    assert any("spread" in r for r in a.reasons)
    assert any("open interest" in r for r in a.reasons)
    # mid-anchored suggestion is still computed (illiquid path layers a model)
    assert a.suggested_limit == 1.40


def test_assess_fill_cheap_contract_rescued_by_absolute_spread():
    # 8c spread on a 14c mid is 57% but tiny in dollars → still liquid.
    a = ta.assess_fill(bid=0.10, ask=0.18, mid=0.14, volume=5, open_interest=900)
    assert a.liquid is True
    assert any("low volume" in n for n in a.notes)


def test_assess_fill_one_sided_market():
    a = ta.assess_fill(bid=0.0, ask=2.0, mid=None, volume=10, open_interest=500)
    assert a.liquid is False
    assert a.suggested_limit is None


# ── IV-aligned model limit ───────────────────────────────────────────────────

def test_model_limit_prices_a_put():
    # Near-ATM put with high IV → a clearly positive premium.
    m = ta.model_limit(spot=95.0, strike=90.0, dte=45, iv=0.55)
    assert m is not None and m > 0


def test_model_limit_missing_inputs():
    assert ta.model_limit(spot=None, strike=90, dte=45, iv=0.5) is None
    assert ta.model_limit(spot=95, strike=90, dte=0, iv=0.5) is None


# ── capacity / affordability ─────────────────────────────────────────────────

def test_puts_affordable():
    assert ta.puts_affordable(50_000, 90) == 5      # 90*100 = 9000 → 5
    assert ta.puts_affordable(8_000, 90) == 0
    assert ta.puts_affordable(None, 90) is None
    assert ta.puts_affordable(50_000, 0) is None


# ── order builder + validation ───────────────────────────────────────────────

def test_build_put_sell_order_ok():
    o = ta.build_put_sell_order(ticker="AAPL", strike=180, expiration="2026-01-16",
                                limit=2.35, quantity=2)
    assert o.credit == 470.0           # 2.35 * 100 * 2
    assert o.collateral == 36_000.0    # 180 * 100 * 2
    assert "SELL 2 AAPL" in o.describe()
    assert "$180 PUT" in o.describe()


def test_build_put_sell_order_rejects_bad_inputs():
    with pytest.raises(ValueError):
        ta.build_put_sell_order(ticker="X", strike=10, expiration="2026-01-16",
                                limit=1.0, quantity=0)
    with pytest.raises(ValueError):
        ta.build_put_sell_order(ticker="X", strike=10, expiration="2026-01-16",
                                limit=0.0, quantity=1)


def test_build_put_sell_order_capacity_guard():
    # 2 contracts × $180 × 100 = $36,000 collateral, only $20k available.
    with pytest.raises(ValueError):
        ta.build_put_sell_order(ticker="AAPL", strike=180,
                                expiration="2026-01-16", limit=2.0, quantity=2,
                                capacity=20_000)
