# stockpile

Monorepo of stock portfolio tools: position tracker, cost basis
charts, and shared parsing/finance utilities.

> **Disclaimer** — This software is provided free of charge, as-is,
> with no warranty of any kind. There is no guarantee of accuracy,
> completeness, or fitness for any particular purpose. All tools rely
> on third-party data sources (Yahoo Finance, brokerage CSV exports,
> Google Sheets) whose availability, accuracy, and format can change
> without notice; output quality is limited by what those sources
> return. Nothing produced by any tool in this repository constitutes
> financial advice. Investing and options trading involve substantial
> risk of loss. Do your own research before making any financial
> decision. The authors are not responsible for any trading losses or
> other damages arising from use of this software.

## Projects

- **shared** — pip-installable package (`stocks-shared`): CSV parsers
  (Schwab, Robinhood, Fidelity, Merrill Edge, and the
  [stockpile manual format](docs/stockpile-format.md)), Yahoo Finance
  helpers, FIFO analysis, Black-Scholes pricing
- **tools** — one-off migration scripts: Schwab→Robinhood CSV
  conversion, Merrill Edge PDF statement extractor
- **[positions](positions/README.md)** — Google Sheets position tracker
- **[cost-basis-charts](cost-basis-charts/README.md)** — Interactive
  cost basis vs. price charts (YouTube tutorial project)
- **[options-scanner](options-scanner/README.md)** — Find mispriced
  LEAPS to sell or buy. Three entry points: a CLI scanner for a single
  ticker, a portfolio scanner that reads a brokerage CSV, and a
  Streamlit web UI
- **[google-sheets-setup](google-sheets-setup/README.md)** — Google
  Sheets API setup docs

## Quick start

The fastest way to see something useful after cloning is the options
scanner web UI — no CLI knowledge required:

```bash
git clone https://github.com/medloh/stockpile.git
cd stockpile
uv sync
uv run streamlit run options-scanner/run_app.py
```

A browser tab opens at http://localhost:8501. Type a ticker on the
**Single Ticker** tab and hit Scan, or drag a brokerage CSV onto the
**Portfolio** tab.

For the other tools (charts, positions tracker), see the
[Running the projects](#running-the-projects) section below.

## Using Claude Code with this repo

The easiest way to get any of these tools running is with a Claude
Code subscription. Clone the repo, open Claude Code in the project
directory, and ask it to help you configure and run the tool with
your own brokerage export. It can walk you through setup, fix any
issues, and add new features — no manual coding required. All of the
tools in this repo were built this way.

Get Claude Code at: https://claude.ai/code

Subscriptions start at $20/month (Pro plan). The Max plan ($100/month)
gives higher usage limits, which is useful for longer coding sessions.

### Project slash commands

This repo ships with project-scoped slash commands under
`.claude/commands/`. Inside a Claude Code session, type `/` to see
them:

| Command | What it does |
|---------|--------------|
| `/scan TICKER [flags]` | Run the options-scanner CLI for one ticker |
| `/scan-portfolio --csv FILE` | Scan every open position in a brokerage CSV |
| `/scan-ui` | Launch the options scanner web UI |
| `/charts [--symbol X]` | Generate cost-basis charts |
| `/positions` | Run the Google Sheets position tracker |

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) — fast Python package and project
  manager (replaces pip + venv)

## Installing Python

If you don't have Python 3.12+, the easiest way is to let `uv` manage
it for you:

```bash
uv python install 3.12
```

Or install manually from [python.org](https://www.python.org/downloads/)
and ensure `python3 --version` reports 3.12+.

## Installing uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation, restart your terminal so `uv` is on your PATH.

## How the virtual environment works

This repo uses **uv workspaces**. The root `pyproject.toml` declares
all three sub-projects (`shared`, `positions`, `cost-basis-charts`) as
workspace members. When you run `uv sync`, uv:

1. Creates a single shared `.venv/` at the repo root
2. Installs all dependencies for every workspace member into it
3. Installs `shared` (the `stocks-shared` package) as an editable
   local package so changes to it are immediately reflected in the
   other projects

You never need to activate the virtual environment manually — `uv run`
handles that automatically.

## Setup

Clone the repo and sync dependencies (run once, and again after any
`pyproject.toml` change):

```bash
git clone https://github.com/medloh/stockpile.git
cd stockpile
uv sync
```

## Running the projects

Always use `uv run` from the **repo root**. This ensures the correct
virtual environment and the `stocks-shared` package are available
regardless of which sub-project you're running.

```bash
# Cost basis charts
uv run cost-basis-charts/run_charts.py

# Cost basis charts — single symbol only
uv run cost-basis-charts/run_charts.py --symbol SCHW

# Position tracker (Google Sheets)
uv run positions/run_tracker.py

# Options scanner — single ticker
uv run options-scanner/run_scanner.py AMD --calls

# Options scanner — every open position in a brokerage CSV
uv run options-scanner/run_portfolio.py --csv input/schwab028.csv

# Options scanner — Streamlit web UI (browser-based, no CLI knowledge)
uv run streamlit run options-scanner/run_app.py
```

**Do not** use `python` or `python3` directly — those will use the
system Python which doesn't have the project's dependencies installed.

## Configuration

Each sub-project has a `config.toml.example`. Copy it and fill in
your details:

```bash
# macOS / Linux / Git Bash
cp cost-basis-charts/config.toml.example cost-basis-charts/config.toml
cp positions/config.toml.example positions/config.toml

# Windows PowerShell or CMD
copy cost-basis-charts\config.toml.example cost-basis-charts\config.toml
copy positions\config.toml.example positions\config.toml
```

See the comments inside each file for what each field means.

Place your brokerage CSV exports in `input/` — both tools look there
by default. The `input/` directory is gitignored so your files stay
local.

## Adding new dependencies

To add a package to a specific sub-project:

```bash
uv add plotly --project cost-basis-charts
```
Then re-run `uv sync` to update the lockfile.

## Troubleshooting

### Windows: `ImportError: DLL load failed while importing base`

If you see an error like this when running on Windows:

```
ImportError: DLL load failed while importing base:
An Application Control policy has blocked this file.
```

This is Windows blocking pandas' C extension DLLs due to an
Application Control policy. Try running from an **administrator
PowerShell**:

1. Right-click PowerShell and select **Run as administrator**
2. Navigate to the repo: `cd path\to\stockpile`
3. Run normally: `uv run cost-basis-charts/run_charts.py`

