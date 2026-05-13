# Stockpile CSV Format

A human-written transaction log for stock and options positions — for
use when you don't have a supported brokerage export (Schwab, Robinhood,
Fidelity, or Merrill Edge), or when you want to maintain your own
records independently.

The file is a plain CSV that you can create in Excel, Google Sheets, or
any text editor. Every row is one transaction. Stocks and options live
in the same file; the `action` column tells the tool what each row
means.

## Quick start

1. Copy `input/stockpile.csv.example` to `input/my-portfolio.csv`.
2. Delete the example rows and add your own transactions.
3. Open the Options Scanner web UI, upload/drag the file onto the **Portfolio**
   tab, and select **stockpile** as the format. Validation runs
   automatically and lists any problems before you scan.

## Columns

| Column | Required | Type | Notes |
|--------|----------|------|-------|
| `date` | always | `YYYY-MM-DD` | Transaction date |
| `action` | always | see below | What happened |
| `symbol` | always | `AAPL` | Underlying ticker — never the option string |
| `quantity` | usually | positive integer | Shares (stocks) or contracts (options); not needed for DIVIDEND |
| `option_type` | options only | `CALL` or `PUT` | Blank for stock rows |
| `strike` | options only | decimal | e.g. `190.00` |
| `expiration` | options only | `YYYY-MM-DD` | Blank for stock rows |
| `price` | recommended | decimal | Per share for stocks; per underlying share for options (multiply by 100 for one contract's value) |
| `fees` | optional | decimal | Total commissions; defaults to `0.00` |
| `amount` | optional | decimal | Net cash — positive = received, negative = paid. Computed from price and fees if blank. |
| `description` | optional | text | Free notes. Quote the field if it contains commas. |

**Tip:** Leave `amount` blank and let the tool compute it whenever
the math is simple (price × qty × 100 for options, price × qty for
stocks, minus fees). Fill it in explicitly when you have the exact
figure from your broker statement.

## Actions

### Stock actions

| Action | Meaning |
|--------|---------|
| `BUY` | Purchase shares |
| `SELL` | Sell shares |
| `DIVIDEND` | Cash dividend received |
| `SPLIT` | Stock split — record only the *additional* shares at $0 |
| `TRANSFER_IN` | Shares transferred in from another account |

### Option actions

| Action | Meaning | Opens or closes |
|--------|---------|-----------------|
| `STO` | Sell to Open — sell an option (short position) | Opens short |
| `BTO` | Buy to Open — buy an option (long position) | Opens long |
| `STC` | Sell to Close — sell a long option | Closes long |
| `BTC` | Buy to Close — buy back a short option | Closes short |
| `EXPIRED` | Option expired worthless | Closes either |
| `ASSIGNED` | Short option was assigned | Closes short; **add a stock row** |
| `EXERCISED` | Long option was exercised | Closes long; **add a stock row** |

## Sign convention

| You paid money | You received money |
|----------------|--------------------|
| BUY, BTO, BTC | SELL, STO, STC |
| `amount` is **negative** | `amount` is **positive** |

EXPIRED, ASSIGNED, and EXERCISED always have `amount = 0.00` on the
option row. The cash flow from the resulting stock transaction goes on
a separate BUY or SELL row (see below).

## Multi-row patterns

Some events require more than one row because they involve both an
option closing and a stock transaction.

### Assignment (short option assigned)

Assignment is a two-row event. First close the option, then record the
stock transaction that resulted.

**Short put assigned** (you buy shares at the strike):
```
date,action,symbol,quantity,option_type,strike,expiration,price,fees,amount
2025-07-18,ASSIGNED,TSLA,1,PUT,250.00,2025-07-18,0.00,0.00,0.00
2025-07-18,BUY,TSLA,100,,,,,0.00,-25000.00
```

**Short call assigned** (your shares are called away at the strike):
```
date,action,symbol,quantity,option_type,strike,expiration,price,fees,amount
2025-09-19,ASSIGNED,AAPL,1,CALL,190.00,2025-09-19,0.00,0.00,0.00
2025-09-19,SELL,AAPL,100,,,,,0.00,19000.00
```

### Exercise (long option exercised)

Exercise is also a two-row event.

**Long call exercised** (you buy shares at the strike):
```
date,action,symbol,quantity,option_type,strike,expiration,price,fees,amount
2025-12-05,EXERCISED,AMD,2,CALL,120.00,2027-01-15,0.00,0.00,0.00
2025-12-05,BUY,AMD,200,,,,,0.00,-24000.00
```

### Roll (close one position and open another)

A roll is two rows with the same date — a BTC (or STC) followed
immediately by an STO (or BTO).

```
date,action,symbol,quantity,option_type,strike,expiration,price,fees,amount
2026-03-15,BTC,AAPL,1,CALL,220.00,2026-06-19,0.80,0.65,-80.65
2026-03-15,STO,AAPL,1,CALL,230.00,2026-09-18,3.10,0.65,309.35
```

## Amount computation (when left blank)

The tool uses these formulas when `amount` is not provided:

| Action | Formula |
|--------|---------|
| `BUY`, `BTC`, `BTO` | `−(price × qty × mult) − fees` |
| `SELL`, `STC`, `STO` | `+(price × qty × mult) − fees` |
| `EXPIRED`, `ASSIGNED`, `EXERCISED` | `0` |
| `DIVIDEND`, `SPLIT`, `TRANSFER_IN` | `0` |

Where `mult` = 100 for options (per-contract value), 1 for stocks.

## Validation

The Options Scanner web UI validates your file automatically when you
upload it. You can also validate from the CLI:

```bash
uv run python -c "
from stocks_shared.validators import validate_stockpile_csv, count_data_rows
import pathlib
content = pathlib.Path('input/my-portfolio.csv').read_text('utf-8-sig')
issues = validate_stockpile_csv(content)
print(f'{count_data_rows(content)} rows — {len(issues)} issue(s)')
for i in issues:
    row = f'row {i.row}' if i.row else 'file'
    field = f' [{i.field}]' if i.field else ''
    print(f'  {i.severity.upper()} {row}{field}: {i.message}')
"
```

Errors block the portfolio scan; warnings are informational and the
scan can still run.

## Common mistakes

**Dates in the wrong format.** Use `YYYY-MM-DD` (e.g. `2025-07-18`),
not `07/18/2025` or `7/18/25`.

**Option columns filled in on a stock row.** Leave `option_type`,
`strike`, and `expiration` blank for BUY, SELL, DIVIDEND, SPLIT, and
TRANSFER_IN rows.

**ASSIGNED or EXERCISED with no matching stock row.** These events
are always two rows. The validator will warn if it sees ASSIGNED or
EXERCISED on a given date without a BUY or SELL for the same symbol
on that day.

**Quantity of 0 or negative.** Quantity is always a positive integer.
Direction (buy vs. sell, open vs. close) comes from the `action`
column, not from a signed quantity.

**SPLIT quantity is the total shares after the split.** It should be
the *additional* shares received, not the new total. In a 4:1 split
of 100 shares, you receive 300 additional shares — record `300`,
not `400`.

**DIVIDEND with quantity.** You don't need a quantity for dividends.
Put the total cash received in `amount` (or `price` per share and
let the tool compute the total).

## Comment lines

Lines starting with `#` are comments and are ignored. Use them freely
to organize your file into sections or explain unusual transactions:

```csv
# Covered calls on AAPL position
2025-06-15,STO,AAPL,1,CALL,200.00,2025-09-19,3.20,0.65,,

# === TSLA — added after put assignment in July 2025 ===
2025-07-18,BUY,TSLA,100,,,,,0.00,-25000.00,
```

## Full example

See [`input/stockpile.csv.example`](../input/stockpile.csv.example)
for a complete file covering every action type with realistic scenarios
and inline comments explaining each one.
