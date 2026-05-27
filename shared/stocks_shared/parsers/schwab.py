"""Schwab CSV parser."""

import re
import csv
from collections import defaultdict


def parse_dollar(s):
    if not s:
        return None
    s = re.sub(r"[$,\s]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw):
    m = re.search(r"as of (\d{2}/\d{2}/\d{4})", raw)
    return m.group(1) if m else raw.strip()


def _parse_rows_to_transactions(rows):
    """Convert raw Schwab CSV DictReader rows to transaction list format."""
    transactions = []
    for row in rows:
        action = row.get("Action", "").strip()
        raw_date = row.get("Date", "").strip()
        if not action or not raw_date:
            continue
        if not re.search(r"\d{2}/\d{2}/\d{4}", raw_date):
            continue
        if action in ("Current Price", "Calls Current Market Value", "Puts Current Market Value"):
            continue

        date_str = parse_date(raw_date)
        symbol = row.get("Symbol", "").strip()
        qty_s = row.get("Quantity", "").strip()
        price_s = row.get("Price", "").strip()
        fees_s = row.get("Fees & Comm", "").strip()
        amount_s = row.get("Amount", "").strip()

        if "Dividend" in action:
            amount = parse_dollar(amount_s)
            transactions.append([
                date_str, action, "Dividend", symbol, "", "", "", "", "",
                "" if amount is None else amount, ""
            ])
            continue

        # Internal Transfer: shares arriving from a TDA→Schwab account migration.
        # Record as "Transfer In" so compute_status can flag the position as
        # Inconsistent until the original buy transactions are located.
        if action == "Internal Transfer":
            qty = abs(float(qty_s.replace(",", ""))) if qty_s and re.search(r"\d", qty_s) else ""
            if qty == "" or qty <= 0:
                continue
            transactions.append([
                date_str, "Transfer In", "Stock", symbol,
                "", "", qty, "", "", "", ""
            ])
            continue

        # "Journaled Shares" with an option symbol and "EXPIRATION" in the description
        # is the TDA way of recording an option expiration (pre-Schwab migration rows).
        description = row.get("Description", "").strip()
        if action == "Journaled Shares" and "EXPIRATION" in description.upper():
            action = "Expired"

        opt = re.match(r"\S+\s+(\d{2}/\d{2}/\d{4})\s+([\d.]+)\s+([CP])\b", symbol)
        if opt:
            expiration = opt.group(1)
            strike = float(opt.group(2))
            opt_type = "Call" if opt.group(3) == "C" else "Put"
        else:
            expiration = ""
            strike = ""
            opt_type = "Stock"

        qty = abs(float(qty_s.replace(",", ""))) if qty_s and re.search(r"\d", qty_s) else ""
        price = parse_dollar(price_s)
        fees = parse_dollar(fees_s)
        amount = parse_dollar(amount_s)

        transactions.append([
            date_str, action, opt_type, symbol,
            strike if strike != "" else "",
            expiration,
            qty,
            "" if price is None else price,
            "" if fees is None else fees,
            "" if amount is None else amount,
            "",
        ])

    transactions.sort(key=lambda r: (r[0][6:], r[0][:2], r[0][3:5]))
    return transactions


def parse_all_transactions(filepath):
    """Parse a Schwab all-transactions CSV.

    Returns (ticker_transactions, other_rows):
    - ticker_transactions: dict {ticker: [transaction rows]}
    - other_rows: list of raw CSV dicts that don't belong to any position
    """
    OPTION_ACTIONS = {"Sell to Open", "Buy to Open", "Buy to Close", "Sell to Close",
                      "Expired", "Assigned"}
    STOCK_ACTIONS = {"Buy", "Sell"}
    TRANSFER_IN_ACTION = "Internal Transfer"
    TICKER_RE = re.compile(r"^[A-Z]{1,6}(\.[A-Z]{1,2})?$")

    raw_rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_rows.append(row)

    position_tickers = set()
    for row in raw_rows:
        action = row.get("Action", "").strip()
        symbol = row.get("Symbol", "").strip()
        raw_date = row.get("Date", "").strip()
        qty_s = row.get("Quantity", "").strip()
        if not action or not raw_date or not re.search(r"\d{2}/\d{2}/\d{4}", raw_date):
            continue
        if action in OPTION_ACTIONS:
            m = re.match(r"([A-Z]+)\d*\s+\d{2}/\d{2}/\d{4}", symbol)
            if m:
                position_tickers.add(m.group(1))
        elif action in STOCK_ACTIONS and TICKER_RE.match(symbol):
            position_tickers.add(symbol)
        elif action == TRANSFER_IN_ACTION and TICKER_RE.match(symbol) and re.search(r"\d", qty_s):
            position_tickers.add(symbol)

    ticker_raw = defaultdict(list)
    other_rows = []
    for row in raw_rows:
        action = row.get("Action", "").strip()
        symbol = row.get("Symbol", "").strip()
        raw_date = row.get("Date", "").strip()
        if not action or not raw_date or not re.search(r"\d{2}/\d{2}/\d{4}", raw_date):
            continue

        assigned = None
        if action in OPTION_ACTIONS:
            m = re.match(r"([A-Z]+)\d*\s+\d{2}/\d{2}/\d{4}", symbol)
            if m:
                assigned = m.group(1)
        elif action in STOCK_ACTIONS and TICKER_RE.match(symbol):
            assigned = symbol
        elif action == TRANSFER_IN_ACTION and TICKER_RE.match(symbol):
            assigned = symbol
        elif symbol and symbol in position_tickers:
            assigned = symbol

        if assigned:
            ticker_raw[assigned].append(row)
        else:
            other_rows.append(row)

    ticker_transactions = {
        t: _parse_rows_to_transactions(rows)
        for t, rows in ticker_raw.items()
    }
    return ticker_transactions, other_rows
