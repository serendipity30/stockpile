"""Assisted put-selling logic — fill-quality assessment + limit pricing.

Pure helpers behind the watchlist "investigate put-sell" dialog (see
``options-scanner/assisted-put-selling-implementation-plan.md``). Order
*placement* is NOT here yet — these only judge whether a cash-secured put
looks executable at favorable terms and suggest a limit price. Kept free of
Streamlit so they're unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Liquidity thresholds — a deliberately conservative first guess at "would a
# limit order here have a good chance of filling at favorable terms?". These
# are about *executability*, distinct from the IV+pp ranking (which already
# judged whether it's a good trade). Tune as real fills come in.
MIN_OI = 50            # open-interest floor
MAX_SPREAD_PCT = 0.15  # bid/ask spread as a fraction of mid
MAX_SPREAD_ABS = 0.10  # absolute spread tolerance (rescues cheap contracts
                       # whose % spread is high but whose dollar spread is tiny)

# Matches options_scanner.chain._RISK_FREE_RATE so the model limit is priced
# on the same footing as the greeks the scan already showed.
RISK_FREE_RATE = 0.045


@dataclass
class FillAssessment:
    """Verdict on one contract's executability.

    `suggested_limit` is the mid rounded to tick — set whenever there's a
    two-sided market, None only when bid/ask are missing. `liquid` says
    whether to *trust* a fill there; `reasons` says why not when False.
    `notes` are soft caveats shown either way (e.g. zero volume).
    """

    liquid: bool
    suggested_limit: float | None
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def tick_for(price: float) -> float:
    """Conventional option price increment: $0.05 at/above $3, else $0.01."""
    return 0.05 if price >= 3.0 else 0.01


def round_to_tick(price: float) -> float:
    """Round to the conventional option tick (a suggestion only).

    The authoritative increment rules come from Schwab when order placement
    is built; this is the penny-pilot split good enough to propose a limit.
    """
    tick = tick_for(price)
    return round(round(price / tick) * tick, 2)


def assess_fill(*, bid, ask, mid=None, volume=None, open_interest=0,
                min_oi: int = MIN_OI, max_spread_pct: float = MAX_SPREAD_PCT,
                max_spread_abs: float = MAX_SPREAD_ABS) -> FillAssessment:
    """Judge whether a put looks executable and suggest a limit (credit/share).

    Liquid requires a two-sided market, open interest >= `min_oi`, and a
    spread that's either <= `max_spread_pct` of mid OR <= `max_spread_abs` in
    dollars. The suggested limit is the mid rounded to the tick. Volume is a
    soft note only — it's 0 for every contract while the market is closed, so
    it can't be a hard gate.
    """
    reasons: list[str] = []
    notes: list[str] = []

    b = float(bid or 0.0)
    a = float(ask or 0.0)
    if b <= 0 or a <= 0:
        reasons.append("no two-sided market (missing bid or ask)")
        return FillAssessment(False, None, reasons, notes)

    mid_val = float(mid) if (mid and mid > 0) else (b + a) / 2
    spread = a - b
    spread_pct = spread / mid_val if mid_val > 0 else float("inf")

    if spread_pct > max_spread_pct and spread > max_spread_abs:
        reasons.append(
            f"wide bid/ask spread (${spread:.2f}, {spread_pct * 100:.0f}% of mid)"
        )
    if open_interest < min_oi:
        reasons.append(f"thin open interest ({open_interest} < {min_oi})")

    if volume is not None:
        if volume == 0:
            notes.append("no volume today (0) — normal while the market is closed")
        elif volume < 10:
            notes.append(f"low volume today ({volume})")

    liquid = not reasons
    # Always suggest a mid-anchored limit; `liquid` tells the caller whether
    # to trust a fill there. The illiquid path layers an IV-aligned model
    # price on top (see model_limit) so a trade can still be priced.
    suggested = round_to_tick(mid_val)
    return FillAssessment(liquid, suggested, reasons, notes)


def model_limit(*, spot, strike, dte, iv) -> float | None:
    """IV-aligned limit — the Black-Scholes put price at the contract's own IV.

    Anchors the limit to the option's implied vol (which carries the IV+pp
    edge) rather than a wide/thin market mid that may not be a meaningful
    number. Used on the illiquid path to still propose a price, even though a
    fill there is unlikely. Returns None when inputs are missing/degenerate.
    """
    if spot is None or iv is None or not dte:
        return None
    if spot <= 0 or strike <= 0 or iv <= 0:
        return None
    T = dte / 365.0
    if T <= 0:
        return None
    from stocks_shared.black_scholes import bs_price
    price = bs_price(spot, strike, T, RISK_FREE_RATE, iv, "put")
    return round_to_tick(price) if price > 0 else None


# ── Account capacity (read-only) ─────────────────────────────────────────────

@dataclass
class AccountCapacity:
    """How much the account can put up to secure cash-secured puts."""

    cash_available: float | None = None
    buying_power: float | None = None

    @property
    def amount(self) -> float | None:
        """Cash to secure puts, falling back to buying power."""
        return self.cash_available if self.cash_available is not None \
            else self.buying_power


def fetch_account_capacity(client) -> AccountCapacity | None:
    """Read available cash / buying power from the first Schwab account.

    Read-only — no order entry. Returns None on any failure so the UI
    degrades gracefully (capacity is informational, never a hard dependency).
    """
    try:
        nums = client.get_account_numbers().json()
        account_hash = nums[0]["hashValue"]
        acct = client.get_account(account_hash).json()
        bal = acct.get("securitiesAccount", {}).get("currentBalances", {})
        cash = bal.get("cashAvailableForTrading")
        bp = bal.get("buyingPower", bal.get("optionBuyingPower"))
        return AccountCapacity(
            cash_available=float(cash) if cash is not None else None,
            buying_power=float(bp) if bp is not None else None,
        )
    except Exception:
        return None


def puts_affordable(capacity: float | None, strike: float | None) -> int | None:
    """How many cash-secured puts `capacity` covers at `strike`.

    capacity ÷ (strike × 100), floored. None when inputs are missing.
    """
    if capacity is None or strike is None or strike <= 0:
        return None
    return int(capacity // (strike * 100))


# ── Order building (validation only — placement is a later, separate step) ───

@dataclass
class PutSellOrder:
    """A single-leg, sell-to-open, cash-secured short put.

    Describes exactly what would be sent; it does NOT place anything. The
    placement step (schwab-py ``option_sell_to_open_limit`` →
    ``client.place_order``) is intentionally not wired yet.
    """

    ticker: str
    strike: float
    expiration: str  # YYYY-MM-DD
    limit: float     # credit per share
    quantity: int

    @property
    def credit(self) -> float:
        """Total premium received if filled at the limit."""
        return round(self.limit * 100 * self.quantity, 2)

    @property
    def collateral(self) -> float:
        """Cash required to secure the put(s)."""
        return round(self.strike * 100 * self.quantity, 2)

    def describe(self) -> str:
        exp = datetime.strptime(self.expiration, "%Y-%m-%d").strftime("%b %d '%y")
        return (f"SELL {self.quantity} {self.ticker} {exp} ${self.strike:g} "
                f"PUT @ ${self.limit:.2f} limit")


def build_put_sell_order(*, ticker: str, strike: float, expiration: str,
                         limit: float, quantity: int,
                         capacity: float | None = None) -> PutSellOrder:
    """Validate and return a cash-secured short-put order (no placement).

    Enforces guardrail #1 in code (single-leg, sell-to-open, qty >= 1,
    limit > 0) and, when `capacity` is given, that the collateral fits.
    Raises ValueError on any violation.
    """
    if int(quantity) < 1:
        raise ValueError("quantity must be at least 1 contract")
    if float(limit) <= 0:
        raise ValueError("limit price must be positive")
    if float(strike) <= 0:
        raise ValueError("strike must be positive")
    order = PutSellOrder(
        ticker=str(ticker), strike=float(strike), expiration=str(expiration),
        limit=float(limit), quantity=int(quantity),
    )
    if capacity is not None and order.collateral > capacity + 1e-6:
        raise ValueError(
            f"collateral ${order.collateral:,.0f} exceeds available "
            f"${capacity:,.0f}"
        )
    return order


# ── Live re-quote (read-only) ────────────────────────────────────────────────

def requote_put(client, ticker: str, expiration: str,
                strike: float) -> dict | None:
    """Fresh bid/ask/mid/last for one put via the existing chain fetch.

    Read-only; reuses ``schwab_live.fetch_option_chain_schwab``. Returns
    {bid, ask, mid, last} or None when unavailable.
    """
    from stocks_shared.schwab_live import fetch_option_chain_schwab
    try:
        chain = fetch_option_chain_schwab(client, ticker, expiration)
    except Exception:
        return None
    if chain is None or chain.puts.empty:
        return None
    row = chain.puts[chain.puts["strike"] == float(strike)]
    if row.empty:
        return None
    r = row.iloc[0]
    bid = float(r.get("bid", 0) or 0)
    ask = float(r.get("ask", 0) or 0)
    last = float(r.get("lastPrice", 0) or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
    return {"bid": bid, "ask": ask, "mid": mid, "last": last}
