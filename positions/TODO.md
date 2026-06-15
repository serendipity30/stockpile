# Positions tracker — TODO / roadmap

Tracked items to revisit. Not blockers.

## 1. Support short stock positions

- **Where:** `positions/src/setup_tab.py` — `compute_status` (the
  "negative shares → Inconsistent" check) plus the share-count and
  P&L math in `positions/src/layout.py`.
- **What:** the tracker assumes every stock position is long. A running
  share count that goes below zero is treated as a data error and the
  position is flagged **Inconsistent** (see
  `test_sell_before_buy_is_inconsistent`). That's the right call today —
  it catches a missing opening lot or a mis-ordered CSV — but it means a
  genuine short sale (sell-to-open shares, buy-to-cover later) can never
  be represented.
- **Why it's a can of worms:** distinguishing a *legitimate* short from a
  *broken* import is the hard part. A negative count alone can't tell
  them apart. Likely need an explicit signal — e.g. a "Sell Short" /
  "Buy to Cover" action from the brokerage CSV (Schwab uses these), or a
  per-ticker opt-in — before relaxing the negative-shares guard.
- **Knock-on work:** cost-basis / P&L for shorts is inverted (proceeds
  first, cost to cover later), borrow fees and dividend-in-lieu may
  appear as separate CSV rows, and the Summary tabs assume long-side
  market value. All of that needs handling, not just the status check.
- **Surfaced:** 2026-06-15, while diagnosing an SPCX same-day round trip
  that tripped the negative-shares guard (the ordering half of that was
  fixed in `shared/stocks_shared/parsers/schwab.py`; this is the
  remaining, deliberately deferred half).
