# Schwab Data Source Integration

## Overview

The options scanner supports two data sources:

- **Yahoo Finance** (default) — no setup required, uses `yfinance`
- **Schwab** — real-time quotes, actual Greeks, full chain coverage;
  requires a Schwab account and a free Schwab developer API account

## How to configure Schwab

### 1. Get API credentials

Register at [developer.schwab.com](https://developer.schwab.com).
- follow the steps, it required an approval which took a couple of hours
  before I could create app (next step)

Create an app and note your **App Key** and **App Secret**.
Set the callback URL to `https://127.0.0.1:8182/`.
- simple, just filling in some descriptive fields.
- after creating this app it also took a few hours before app
  was ready to use.

### 2. Create config.toml

```bash
cp options-scanner/config.toml.example options-scanner/config.toml
```

Edit `config.toml` and fill in your credentials:

```toml
[data_source]
provider = "schwab"

[schwab]
app_key      = "your-app-key"

app_secret   = "your-app-secret"

callback_url = "https://127.0.0.1:8182/"
token_file   = "~/.config/schwab-token.json"
```

### 3. Authenticate (first run only)

```bash
uv run options-scanner/schwab_auth.py
```
- This won't work until app is ready.
- You may get key and secret before app is ready to be used.

This opens a browser, logs you in to Schwab, and saves an OAuth token.
Subsequent runs refresh the token silently.
- this will ask you to login
- it wants you to login to your schwab account, not the new developer acct.
- You will get an SSL warning since you're using a self-signed cert locally.
- You'll have to press the advanced button to continue

## Usage

### CLI

```bash
# Use Schwab (reads from config.toml)
uv run options-scanner/run_scanner.py AMD --calls

# Override to Yahoo for one run
uv run options-scanner/run_scanner.py AMD --calls --data-source yahoo

# Override to Schwab for one run (without changing config.toml)
uv run options-scanner/run_scanner.py AMD --calls --data-source schwab
```

### Portfolio CLI

```bash
uv run options-scanner/run_portfolio.py --csv input/schwab028.csv
uv run options-scanner/run_portfolio.py --csv input/schwab028.csv \
    --data-source schwab
```

### Web UI

Open the sidebar (>> arrow) and select **Data source** from the
dropdown. The default is read from `config.toml`.

## What changes with Schwab

| Feature | Yahoo Finance | Schwab |
|---------|--------------|--------|
| Option chain data | Delayed/stale | Real-time |
| Bid / Ask | Last market refresh | Live NBBO |
| IV | Stale (hours old) | Current |
| Delta | Black-Scholes from stale IV | Real Greek |
| Earnings dates | Yahoo Finance | Yahoo Finance |

Earnings dates always come from Yahoo Finance — the Schwab API does
not provide this data. Everything else (chain, prices, roll close cost)
uses the selected provider.

## Architecture

```
chain.py:fetch_chain(provider="yahoo"|"schwab")
  ├── provider="yahoo"  → _fetch_chain_yahoo()   (existing yfinance code)
  └── provider="schwab" → schwab_chain.fetch_chain_schwab()

Roll close cost lookup:
  ├── provider="yahoo"  → stocks_shared.yahoo.fetch_option_chain()
  └── provider="schwab" → stocks_shared.schwab_live.fetch_option_chain_schwab()

Earnings (always Yahoo):
  └── earnings.fetch_earnings_dates()
```
