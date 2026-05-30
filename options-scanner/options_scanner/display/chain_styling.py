"""Chain-table cell styling, row-highlight masks, and tooltip text.

Shared by the per-expiration chain view (`show_chain_table`) and the
ranked scan-results table (`show_df`). Three coupled concerns live
here:

1. The yellow warning highlight (`CELL_WARN`) used to flag wide
   spreads, low OI, and low daily volume rows.
2. Mask helpers (`wide_spread_mask`, `last_outside_mask`,
   `low_oi_mask`, `low_vol_mask`) that decide *which* rows in a chain
   get the warning highlight.
3. The hover-help tooltips for the Spread, Last, OI, Vol, and IV+pp
   column headers. `ivpp_help_for` is a small factory because the
   sign convention flips for buyers vs sellers — surfacing that in
   the tooltip itself saves users from having to remember it.
"""

from __future__ import annotations

import pandas as pd


CELL_WARN = "background-color: rgba(234,179,8,0.45)"

SPREAD_HELP = ("Spread = Ask − Bid. Yellow: spread is wider than 1.5× the"
               " median for this table — higher execution cost.")

LAST_HELP = ("Last traded price. Yellow: the last trade printed outside the"
             " current bid-ask range — likely stale or off-market, so treat"
             " it with caution.")

OI_HELP = ("Yellow: OI is below 2× the min OI filter"
           " — limited liquidity, harder to fill at a good price.")

def vol_help_for(min_vol: int) -> str:
    thresh = max(min_vol * 2, 4)
    return (f"Yellow: fewer than {thresh} contracts traded today"
            f" — very thin activity.")


def wide_spread_mask(bid: pd.Series, ask: pd.Series,
                     mid: pd.Series) -> list[bool]:
    """Flag rows whose bid/ask spread is wider than 1.5× the table median.

    Computed per-table so the threshold scales with liquidity — wide is
    relative to the rest of the rows the user is currently looking at,
    not an absolute spread floor.
    """
    ratios = ((ask - bid) / mid.clip(lower=0.01)).tolist()
    vals = sorted(ratios)
    median = vals[len(vals) // 2] if vals else 0.0
    thresh = max(median * 1.5, 0.15)
    return [r > thresh for r in ratios]


def last_outside_mask(last: pd.Series, bid: pd.Series,
                      ask: pd.Series) -> list[bool]:
    """Flag rows whose last trade printed outside the live bid-ask range.

    Only flags when there is a real last price and a two-sided quote
    (last, bid, ask all > 0); a last below the bid or above the ask means
    the print is stale or off-market relative to the current quote, so the
    Last value shouldn't be trusted as a fill reference.
    """
    return [
        (l > 0 and b > 0 and a > 0 and (l < b or l > a))
        for l, b, a in zip(last.tolist(), bid.tolist(), ask.tolist())
    ]


def low_oi_mask(oi: pd.Series, min_oi: int) -> list[bool]:
    """Flag rows whose open interest is below 2× the min OI filter.

    A row already passed the min OI filter to land in the table — this
    flags ones that are *barely* above the floor, signaling thinner
    liquidity than the rest of the displayed set.
    """
    thresh = max(min_oi * 2, 10)
    return [v < thresh for v in oi.tolist()]


def low_vol_mask(vol: pd.Series, min_vol: int) -> list[bool]:
    """Flag rows with sub-4-contract daily volume (or below 2× min_vol).

    Today's volume is the freshest liquidity signal; OI is cumulative
    and includes stale interest. A row with high OI but near-zero
    today-volume is often a strike no one trades anymore.
    """
    thresh = max(min_vol * 2, 4)
    return [v < thresh for v in vol.tolist()]


def ivpp_help_for(buy: bool, opt_type: str = "option") -> str:
    """Tooltip text for the IV+pp column, tailored to the user's scan.

    The number's sign is interpreted opposite for sellers vs buyers —
    a +5 pp call is great if you're SELLING it (rich premium
    collected) and bad if you're BUYING it (paying above the surface).
    The tooltip switches accordingly so the user doesn't have to
    remember the convention.
    """
    plural = {"call": "calls", "put": "puts", "both": "options"}.get(
        opt_type.lower(), "options"
    )
    if buy:
        # Buyer wants cheap → negative IV+pp.
        return (
            f"Percentage points the option's IV sits ABOVE (+) or BELOW (−)"
            f" the fitted volatility surface. You're BUYING {plural} — you want"
            f" NEGATIVE values (the option is cheap relative to its peers, so"
            f" you pay less than the surface implies). Look for −3 pp or lower;"
            f" near 0 sits on the surface; positive means you're paying above it."
        )
    # Seller wants rich → positive IV+pp.
    return (
        f"Percentage points the option's IV sits ABOVE (+) or BELOW (−)"
        f" the fitted volatility surface. You're SELLING {plural} — you want"
        f" POSITIVE values (the option is rich relative to its peers, so you"
        f" collect more than fair). Look for +5 pp or higher; under +3 pp is"
        f" noise; negative means the chain isn't paying a premium."
    )
