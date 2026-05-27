"""Compute running FIFO cost basis per share over time from a transaction list."""

from collections import deque
from datetime import datetime


def _parse_date(date_str):
    return datetime.strptime(date_str, "%m/%d/%Y").date()


def _remove_open_option(open_options, opt_type, strike, expiration, qty):
    remaining = qty
    new_open = []
    for opt in open_options:
        if (opt["opt_type"] == opt_type and opt["strike"] == strike
                and opt["expiration"] == expiration and remaining > 0):
            if opt["qty"] <= remaining:
                remaining -= opt["qty"]
            else:
                new_open.append({**opt, "qty": opt["qty"] - remaining})
                remaining = 0
        else:
            new_open.append(opt)
    open_options[:] = new_open


def _merge_rolls(series):
    """Merge same-date BTC+STO pairs into a single Roll annotation.

    A roll is a BTC and STO on the same date. The merged entry keeps the
    final state (after both legs) but replaces both labels with a single
    'Roll: credit/debit ±$X.XX/shr' label so the chart shows one marker
    and makes the direction of cost-basis movement obvious.
    """
    if not series:
        return series
    result = []
    i = 0
    while i < len(series):
        cur = series[i]
        nxt = series[i + 1] if i + 1 < len(series) else None
        cur_label = cur.get("label") or ""
        nxt_label = (nxt.get("label") or "") if nxt else ""
        is_btc = lambda lbl: lbl.startswith("BTC")
        is_sto = lambda lbl: lbl.startswith("STO")
        if (nxt is not None
                and cur["date"] == nxt["date"]
                and cur["affects"] == "adjusted"
                and nxt["affects"] == "adjusted"
                and (is_btc(cur_label) or is_sto(cur_label))
                and (is_btc(nxt_label) or is_sto(nxt_label))
                and is_btc(cur_label) != is_btc(nxt_label)):
            pre_adj = result[-1]["adjusted_cost"] if result else cur["adjusted_cost"]
            post_adj = nxt["adjusted_cost"]
            delta = post_adj - pre_adj  # negative = credit, positive = debit
            if delta <= 0:
                roll_label = f"Roll: credit +${abs(delta):.2f}/shr"
            else:
                roll_label = f"Roll: debit −${delta:.2f}/shr"
            result.append({**nxt, "label": roll_label})
            i += 2
        else:
            result.append(cur)
            i += 1
    return result


def compute_cost_basis_series(transactions):
    """Compute running cost basis per share over time.

    Returns (series, open_options):
      series: list of dicts, one entry per transaction that changes shares or cost basis
      open_options: list of currently open short option positions

    Transaction row format (11 elements):
      [date, action, opt_type, symbol, strike, expiration, qty, price, fees, amount, notes]
    """
    lots = deque()       # [(date, qty_remaining, cost_per_share), ...]
    fifo_total = 0.0     # sum of remaining lot costs: qty * cost_per_share
    shares_held = 0.0    # float to capture dividend-reinvest fractions
    adjustment = 0.0     # cumulative net premiums + dividends (positive = lowers cost)
    total_income = 0.0   # same cash flows as adjustment but never scaled on sells

    series = []
    open_options = []    # [{opt_type, strike, expiration, qty}, ...]

    for row in transactions:
        date_str, action, opt_type, symbol, strike, expiration, qty, price, fees, amount, _ = row

        if not date_str or not action:
            continue
        try:
            txn_date = _parse_date(date_str)
        except (ValueError, TypeError):
            continue

        qty_f = float(qty) if qty not in ("", None) else 0.0
        qty_i = int(qty_f)   # integer contract count for option display/matching
        price_f = float(price) if price not in ("", None) else 0.0
        amount_f = float(amount) if amount not in ("", None) else 0.0

        label = None
        affects = None

        if opt_type == "Stock":
            if action in ("Buy", "Reinvest Shares"):
                fifo_total += qty_f * price_f
                shares_held += qty_f
                lots.append((txn_date, qty_f, price_f))
                if action == "Reinvest Shares":
                    label = f"Reinvest {qty_f:.4f} @ ${price_f:.2f}"
                else:
                    label = f"Buy {qty_f:g} @ ${price_f:.2f}"
                affects = "fifo"

            elif action == "Transfer In":
                # Authoritative balance snapshot from broker migration (e.g.
                # TDA->Schwab). Reconcile our running count to the broker's
                # authoritative quantity by either adding a synthetic lot
                # (pre-CSV history) or trimming FIFO lots (CSV anomaly inflated
                # the count, e.g. an unmatched Sell+Buy pair).
                diff = qty_f - shares_held
                if diff > 0.001:
                    fifo_total += diff * price_f  # price_f usually 0
                    shares_held += diff
                    lots.append((txn_date, diff, price_f))
                    label = f"Transfer In {diff:g} shrs (pre-CSV)"
                    affects = "fifo"
                elif diff < -0.001:
                    excess = -diff
                    while excess > 0.001 and lots:
                        lot_date, lot_qty, lot_price = lots[0]
                        if lot_qty <= excess + 1e-9:
                            fifo_total -= lot_qty * lot_price
                            shares_held -= lot_qty
                            excess -= lot_qty
                            lots.popleft()
                        else:
                            fifo_total -= excess * lot_price
                            shares_held -= excess
                            lots[0] = (lot_date, lot_qty - excess, lot_price)
                            excess = 0
                    label = f"Transfer In reconcile to {qty_f:g} shrs"
                    affects = "fifo"

            elif action == "Sell" and shares_held > 0.001:
                old_shares = shares_held
                remaining = qty_f
                while remaining > 0.001 and lots:
                    lot_date, lot_qty, lot_price = lots[0]
                    if lot_qty <= remaining + 1e-9:
                        fifo_total -= lot_qty * lot_price
                        shares_held -= lot_qty
                        remaining -= lot_qty
                        lots.popleft()
                    else:
                        fifo_total -= remaining * lot_price
                        shares_held -= remaining
                        lots[0] = (lot_date, lot_qty - remaining, lot_price)
                        remaining = 0
                # Adjustment is tied to shares — scale it down proportionally
                if old_shares > 0:
                    adjustment *= shares_held / old_shares
                label = f"Sell {qty_f:g} @ ${price_f:.2f}"
                affects = "fifo"

        elif opt_type in ("Call", "Put"):
            if action == "Sell to Open":
                adjustment += amount_f
                total_income += amount_f
                open_options.append({
                    "opt_type": opt_type, "strike": strike,
                    "expiration": expiration, "qty": abs(qty_i),
                    "open_date": txn_date,
                })
                label = f"STO {abs(qty_i)} {opt_type} (+${amount_f:.0f})"
                affects = "adjusted"
            elif action == "Buy to Close":
                adjustment += amount_f
                total_income += amount_f
                _remove_open_option(open_options, opt_type, strike, expiration, abs(qty_i))
                label = f"BTC {abs(qty_i)} {opt_type} (${amount_f:.0f})"
                affects = "adjusted"
            elif action in ("Expired", "Assigned", "Exercise"):
                _remove_open_option(open_options, opt_type, strike, expiration, abs(qty_i))

        elif opt_type == "Dividend":
            adjustment += amount_f
            total_income += amount_f
            label = f"Dividend +${amount_f:.2f}"
            affects = "adjusted"

        if shares_held > 0.001:
            fifo_cost = fifo_total / shares_held
            adjusted_cost = (fifo_total - adjustment) / shares_held
            series.append({
                "date": txn_date,
                "shares": shares_held,
                "fifo_cost": round(fifo_cost, 4),
                "adjusted_cost": round(adjusted_cost, 4),
                "total_income": round(total_income, 2),
                "label": label,
                "affects": affects,
            })

    return _merge_rolls(series), open_options
