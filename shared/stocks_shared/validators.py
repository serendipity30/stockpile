"""Validation for the stockpile manual-entry CSV format."""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime


_STOCK_ACTIONS  = frozenset({"BUY", "SELL", "DIVIDEND", "SPLIT", "TRANSFER_IN"})
_OPTION_ACTIONS = frozenset({"STO", "BTO", "STC", "BTC", "EXPIRED", "ASSIGNED", "EXERCISED"})
_ALL_ACTIONS    = _STOCK_ACTIONS | _OPTION_ACTIONS
_OPEN_ACTIONS   = frozenset({"STO", "BTO"})
_CLOSE_ACTIONS  = frozenset({"STC", "BTC", "EXPIRED", "ASSIGNED", "EXERCISED"})
_REQUIRED_COLS  = frozenset({"date", "action", "symbol", "quantity"})
_OPTION_COLS    = frozenset({"option_type", "strike", "expiration"})


@dataclass
class ValidationIssue:
    row: int       # 1-based data row; 0 = file/header level
    field: str     # column name, or "" for row-level
    severity: str  # "error" | "warning"
    message: str


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _parse_nonneg(s: str) -> float | None:
    try:
        v = float(s.strip())
        return v if v >= 0 else None
    except (ValueError, AttributeError):
        return None


def _parse_number(s: str) -> float | None:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


def _strip_comments(content: str) -> list[str]:
    return [
        line for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def validate_stockpile_csv(content: str) -> list[ValidationIssue]:
    """Validate stockpile-format CSV content.

    Returns a list of ValidationIssue objects describing every structural
    and business-logic problem found.  An empty list means the file is
    clean.  Row numbers are 1-based data rows (excluding the header line).
    """
    issues: list[ValidationIssue] = []

    lines = _strip_comments(content)
    if not lines:
        issues.append(ValidationIssue(0, "", "error",
            "File is empty or contains only comments."))
        return issues

    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if reader.fieldnames is None:
        issues.append(ValidationIssue(0, "", "error", "Could not read CSV header."))
        return issues

    fieldnames = {f.strip().lower() for f in reader.fieldnames if f}
    missing = _REQUIRED_COLS - fieldnames
    if missing:
        issues.append(ValidationIssue(0, "", "error",
            f"Missing required column(s): {', '.join(sorted(missing))}."))
        return issues

    has_opt_cols = _OPTION_COLS.issubset(fieldnames)

    today = date.today()

    # Collected data for cross-row business-logic checks
    # (symbol, expiration, strike, option_type) → net contract count
    opt_net: dict[tuple, int] = {}
    # symbol → net share count
    share_net: dict[str, int] = {}
    # (date_str, symbol) → set of actions on that day
    day_actions: dict[tuple, set] = {}

    for row_num, row in enumerate(reader, start=1):
        def f(col: str) -> str:
            return (row.get(col) or "").strip()

        def err(field: str, msg: str) -> None:
            issues.append(ValidationIssue(row_num, field, "error", msg))

        def warn(field: str, msg: str) -> None:
            issues.append(ValidationIssue(row_num, field, "warning", msg))

        # ── date ──────────────────────────────────────────────────────────
        date_val = f("date")
        row_date = None
        if not date_val:
            err("date", "Missing date.")
        else:
            row_date = _parse_date(date_val)
            if row_date is None:
                err("date", f"'{date_val}' is not a valid YYYY-MM-DD date.")

        # ── action ────────────────────────────────────────────────────────
        action_raw = f("action")
        action = action_raw.upper()
        if not action_raw:
            err("action", "Missing action.")
            action = ""
        elif action not in _ALL_ACTIONS:
            err("action",
                f"Unknown action '{action_raw}'. "
                f"Valid: {', '.join(sorted(_ALL_ACTIONS))}.")
            action = ""  # skip further action-specific checks

        # ── symbol ────────────────────────────────────────────────────────
        symbol = f("symbol").upper()
        if not symbol:
            err("symbol", "Missing symbol.")

        # ── quantity ──────────────────────────────────────────────────────
        qty_val = f("quantity")
        qty: int | None = None
        if not qty_val:
            if action != "DIVIDEND":  # dividend total is in amount; qty not needed
                err("quantity", "Missing quantity.")
        else:
            try:
                q = int(float(qty_val))
                if q <= 0:
                    err("quantity",
                        f"Quantity must be a positive integer, got {qty_val!r}.")
                else:
                    qty = q
            except ValueError:
                err("quantity",
                    f"Quantity must be a positive integer, got {qty_val!r}.")

        # ── option columns ────────────────────────────────────────────────
        opt_type_val = f("option_type") if has_opt_cols else ""
        strike_val   = f("strike")      if has_opt_cols else ""
        exp_val      = f("expiration")  if has_opt_cols else ""

        exp_date: date | None = None
        strike_f: float | None = None

        if action in _OPTION_ACTIONS:
            if not has_opt_cols:
                err("", "Option columns (option_type, strike, expiration) "
                        "are missing from the file header.")
            else:
                if not opt_type_val:
                    err("option_type",
                        f"Required for {action} — must be CALL or PUT.")
                elif opt_type_val.upper() not in ("CALL", "PUT"):
                    err("option_type",
                        f"Must be CALL or PUT, got {opt_type_val!r}.")

                if not strike_val:
                    err("strike", f"Required for {action}.")
                else:
                    try:
                        strike_f = float(strike_val)
                        if strike_f <= 0:
                            err("strike",
                                f"Strike must be positive, got {strike_val!r}.")
                    except ValueError:
                        err("strike",
                            f"Strike must be a number, got {strike_val!r}.")

                if not exp_val:
                    err("expiration", f"Required for {action}.")
                else:
                    exp_date = _parse_date(exp_val)
                    if exp_date is None:
                        err("expiration",
                            f"'{exp_val}' is not a valid YYYY-MM-DD date.")
                    elif action in _OPEN_ACTIONS and exp_date < today:
                        warn("expiration",
                             f"Expiration {exp_val} is in the past.")

        elif action in _STOCK_ACTIONS and has_opt_cols:
            if opt_type_val:
                warn("option_type",
                     f"option_type is set on a stock action ({action}) — "
                     "should be blank.")
            if strike_val:
                warn("strike",
                     f"strike is set on a stock action ({action}) — "
                     "should be blank.")
            if exp_val:
                warn("expiration",
                     f"expiration is set on a stock action ({action}) — "
                     "should be blank.")

        # ── optional numeric fields ───────────────────────────────────────
        price_val = f("price")
        if price_val and _parse_nonneg(price_val) is None:
            err("price", f"Must be a non-negative number, got {price_val!r}.")

        fees_val = f("fees")
        if fees_val and _parse_nonneg(fees_val) is None:
            err("fees", f"Must be a non-negative number, got {fees_val!r}.")

        amount_val = f("amount")
        if amount_val and _parse_number(amount_val) is None:
            err("amount", f"Must be a number, got {amount_val!r}.")

        # ── business logic: share counts ──────────────────────────────────
        if action in _STOCK_ACTIONS and symbol and qty is not None:
            prev = share_net.get(symbol, 0)
            if action == "BUY":
                share_net[symbol] = prev + qty
            elif action == "SELL":
                new_count = prev - qty
                if new_count < 0:
                    warn("quantity",
                         f"Share count for {symbol} goes negative after "
                         f"this SELL ({prev} held, selling {qty}).")
                share_net[symbol] = new_count
            elif action == "SPLIT":
                share_net[symbol] = prev + qty

        # ── business logic: option contract counts ────────────────────────
        if (action in _OPTION_ACTIONS and symbol and qty is not None
                and has_opt_cols and strike_f is not None and exp_val):
            opt_key = (symbol, exp_val, f"{strike_f:.2f}",
                       opt_type_val.upper() if opt_type_val else "")
            prev = opt_net.get(opt_key, 0)
            if action in _OPEN_ACTIONS:
                opt_net[opt_key] = prev + qty
            elif action in _CLOSE_ACTIONS:
                new_count = prev - qty
                if new_count < 0:
                    warn("quantity",
                         f"Contract count for {symbol} "
                         f"{opt_type_val} {strike_val} {exp_val} "
                         f"goes negative — check for missing open transaction.")
                opt_net[opt_key] = new_count

        # ── collect day/symbol actions for paired-row checks ─────────────
        if row_date and symbol and action:
            key = (row_date.isoformat(), symbol)
            day_actions.setdefault(key, set()).add(action)

    # ── cross-row: ASSIGNED/EXERCISED should have a matching stock row ────
    for (day, sym), actions in day_actions.items():
        if "ASSIGNED" in actions:
            if "BUY" not in actions and "SELL" not in actions:
                issues.append(ValidationIssue(0, "", "warning",
                    f"ASSIGNED for {sym} on {day} has no matching BUY or SELL "
                    "on the same date — add the resulting stock transaction."))
        if "EXERCISED" in actions:
            if "BUY" not in actions and "SELL" not in actions:
                issues.append(ValidationIssue(0, "", "warning",
                    f"EXERCISED for {sym} on {day} has no matching BUY or SELL "
                    "on the same date — add the resulting stock transaction."))

    return issues


def count_data_rows(content: str) -> int:
    """Return the number of non-comment, non-blank data rows (excluding header)."""
    lines = _strip_comments(content)
    return max(0, len(lines) - 1)  # subtract header row
