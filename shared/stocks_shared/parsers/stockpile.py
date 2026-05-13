"""Parser for the stockpile manual-entry CSV format."""

import csv
import io
from collections import defaultdict

_ACTION_MAP = {
    "BUY":         "Buy",
    "SELL":        "Sell",
    "DIVIDEND":    "Dividend",
    "SPLIT":       "Buy",         # split = extra shares at $0
    "TRANSFER_IN": "Transfer In",
    "STO":         "Sell to Open",
    "BTO":         "Buy to Open",
    "STC":         "Sell to Close",
    "BTC":         "Buy to Close",
    "EXPIRED":     "Expired",
    "ASSIGNED":    "Assigned",
    "EXERCISED":   "Exercised",
}

_OPTION_ACTIONS = frozenset({"STO", "BTO", "STC", "BTC", "EXPIRED", "ASSIGNED", "EXERCISED"})
_CREDIT_ACTIONS = frozenset({"STO", "STC", "SELL"})   # money received
_DEBIT_ACTIONS  = frozenset({"BTO", "BTC", "BUY"})    # money paid


def _iso_to_mmddyyyy(s: str) -> str:
    """Convert YYYY-MM-DD to MM/DD/YYYY (internal date format)."""
    y, m, d = s.split("-")
    return f"{int(m):02d}/{int(d):02d}/{y}"


def _parse_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_qty(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    try:
        return abs(int(float(s)))
    except ValueError:
        return None


def _build_opt_symbol(ticker: str, exp_mmddyyyy: str, strike: float,
                      opt_type_upper: str) -> str:
    """Build internal option symbol: 'AAPL 06/20/2025 190.00 C'."""
    c_or_p = "C" if opt_type_upper == "CALL" else "P"
    return f"{ticker} {exp_mmddyyyy} {strike:.2f} {c_or_p}"


def _compute_amount(action_upper: str, price: float | None, qty: int | None,
                    fees: float | None) -> float:
    """Net cash when amount column is blank (positive = received, negative = paid)."""
    p = price or 0.0
    q = qty or 0
    f = fees or 0.0
    mult = 100 if action_upper in _OPTION_ACTIONS else 1
    if action_upper in _CREDIT_ACTIONS:
        return round(p * q * mult - f, 6)
    if action_upper in _DEBIT_ACTIONS:
        return round(-(p * q * mult) - f, 6)
    return 0.0  # EXPIRED, ASSIGNED, EXERCISED, DIVIDEND, SPLIT, TRANSFER_IN


def _strip_comments(content: str) -> str:
    """Remove # comment lines and blank lines; return cleaned CSV text."""
    lines = [
        line for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "\n".join(lines)


def _parse_rows_to_transactions(rows: list[dict]) -> list[list]:
    """Convert stockpile CSV row dicts to internal 11-field transaction lists.

    Internal format (matches all other parsers):
    [date MM/DD/YYYY, action, opt_type, symbol, strike, expiration MM/DD/YYYY,
     qty, price, fees, amount, ""]
    """
    transactions = []
    for row in rows:
        def f(name: str) -> str:
            return (row.get(name) or "").strip()

        date_str      = f("date")
        action_raw    = f("action").upper()
        symbol        = f("symbol").upper()
        qty_str       = f("quantity")
        opt_type_raw  = f("option_type").upper()
        strike_str    = f("strike")
        exp_str       = f("expiration")
        price_str     = f("price")
        fees_str      = f("fees")
        amount_str    = f("amount")

        if not date_str or not action_raw or not symbol:
            continue
        if action_raw not in _ACTION_MAP:
            continue

        try:
            date_internal = _iso_to_mmddyyyy(date_str)
        except (ValueError, AttributeError):
            continue

        action = _ACTION_MAP[action_raw]
        qty    = _parse_qty(qty_str)
        price  = _parse_float(price_str)
        fees   = _parse_float(fees_str)
        amount = (_parse_float(amount_str)
                  if amount_str
                  else _compute_amount(action_raw, price, qty, fees))

        def _v(x):
            return "" if x is None else x

        if action_raw in _OPTION_ACTIONS:
            try:
                strike        = float(strike_str)
                exp_internal  = _iso_to_mmddyyyy(exp_str)
            except (ValueError, AttributeError):
                continue
            opt_type   = "Call" if opt_type_raw == "CALL" else "Put"
            opt_symbol = _build_opt_symbol(symbol, exp_internal, strike, opt_type_raw)
            transactions.append([
                date_internal, action, opt_type, opt_symbol,
                strike, exp_internal,
                _v(qty), _v(price), _v(fees), _v(amount), "",
            ])

        elif action_raw == "DIVIDEND":
            # Dividends: no qty/price in internal format; amount is total received
            if not amount_str and price and qty:
                amount = round(price * qty, 6)
            transactions.append([
                date_internal, "Dividend", "Dividend", symbol,
                "", "", "", "", "", _v(amount), "",
            ])

        else:
            # Stock: BUY, SELL, SPLIT (→ Buy at $0), TRANSFER_IN
            price_out = price if action_raw != "SPLIT" else 0.0
            transactions.append([
                date_internal, action, "Stock", symbol,
                "", "",
                _v(qty), _v(price_out), _v(fees), _v(amount), "",
            ])

    transactions.sort(key=lambda r: (r[0][6:], r[0][:2], r[0][3:5]))
    return transactions


def parse_all_transactions(filepath: str) -> tuple[dict, list]:
    """Parse a stockpile manual-entry CSV.

    Returns (ticker_transactions, other_rows):
    - ticker_transactions: {ticker: [transaction rows]}
    - other_rows: always [] (stockpile has no ambiguous rows)
    """
    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        content = fh.read()

    clean = _strip_comments(content)
    reader = csv.DictReader(io.StringIO(clean))

    ticker_raw: dict[str, list] = defaultdict(list)
    for row in reader:
        symbol = (row.get("symbol") or "").strip().upper()
        action = (row.get("action") or "").strip().upper()
        if not symbol or action not in _ACTION_MAP:
            continue
        ticker_raw[symbol].append(row)

    ticker_transactions = {
        ticker: _parse_rows_to_transactions(rows)
        for ticker, rows in ticker_raw.items()
    }
    return ticker_transactions, []
