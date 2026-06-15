"""Tests for the Schwab CSV parser."""

from stocks_shared.parsers.schwab import (
    parse_dollar,
    parse_date,
    _parse_rows_to_transactions,
)


def _make_row(action, symbol, *, qty="", price="", fees="", amount="",
              description="", date="06/12/2026"):
    """Build a raw Schwab CSV DictReader row."""
    return {
        "Date": date,
        "Action": action,
        "Symbol": symbol,
        "Description": description or symbol,
        "Quantity": qty,
        "Price": price,
        "Fees & Comm": fees,
        "Amount": amount,
    }


# ── parse_dollar ──────────────────────────────────────────────────────────────

class TestParseDollar:
    def test_positive(self):
        assert parse_dollar("$2,036.12") == 2036.12

    def test_negative(self):
        assert parse_dollar("-$1620.00") == -1620.0

    def test_empty(self):
        assert parse_dollar("") is None


# ── parse_date ────────────────────────────────────────────────────────────────

class TestParseDate:
    def test_plain(self):
        assert parse_date("06/12/2026") == "06/12/2026"

    def test_as_of(self):
        # Settlement rows carry "<process date> as of <trade date>"; the trade
        # date is what counts for ordering.
        assert parse_date("06/15/2026 as of 06/12/2026") == "06/12/2026"


# ── ordering ──────────────────────────────────────────────────────────────────

class TestOrdering:
    def test_reversed_to_chronological_across_days(self):
        # Schwab CSVs are newest-first; oldest day should come out first.
        rows = [
            _make_row("Buy", "ADBE", qty="10", date="04/22/2026"),
            _make_row("Buy", "ADBE", qty="5",  date="04/15/2026"),
        ]
        txns = _parse_rows_to_transactions(rows)
        assert txns[0][6] == 5    # Apr 15 first
        assert txns[1][6] == 10

    def test_same_day_round_trip_buy_before_sell(self):
        # A same-day buy then sell is printed sell-first (newest-first). The
        # parser must replay it buy-first so shares don't go negative.
        rows = [
            _make_row("Sell", "SPCX", qty="12", price="$169.68",
                      fees="$0.04", amount="$2036.12"),
            _make_row("Buy", "SPCX", qty="12", price="$135.00",
                      amount="-$1620.00"),
        ]
        txns = _parse_rows_to_transactions(rows)
        assert [t[1] for t in txns] == ["Buy", "Sell"]
