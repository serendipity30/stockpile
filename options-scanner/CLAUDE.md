# CLAUDE.md — options-scanner

## Purpose

Scan an option chain and rank each option by IV excess — how far its
implied volatility sits above or below a fitted 2-D surface — to
surface IV-rich candidates for covered calls, cash-secured puts, and
roll setups (or IV-cheap candidates in buy mode).

The output is a **screening heuristic, not a mispricing or arbitrage
claim**. Vol smiles and skew are legitimate, the no-arbitrage
principle does not require the surface to be smooth, and IV+pp
deviations can reflect demand pressure, event risk, or stale prints
as easily as a tradeable signal. Phrase user-facing copy accordingly
— "mispriced", "overpriced", "underpriced", "anomaly" are out;
"IV-rich", "IV-cheap", "outlier", "stands above/below the surface"
are in. "Rich premium" / "cheap premium" are conventional trader
vernacular and remain fine.

## How it works

1. Fetch all expirations with DTE >= min_dte from Yahoo Finance
2. Annotate earnings events within each expiration window (elevated IV
   around earnings is expected, not a signal)
3. Fit an IV surface and score each option, via a three-stage
   **pluggable pipeline**:
   - **Filter** (`iv_filters.py`) — which options feed the regression.
     Defaults: OTM-only, spread ≤ 50% of mid, delta 0.10–0.95, and
     *short-dated* (≤ 60 DTE) earnings-spanning options excluded — long-
     dated contracts stay in the fit, since one earnings is a negligible
     share of their variance, and a guard keeps the filter from emptying
     the fit; an always-on sanity stage (IV noise floor/ceiling, DTE > 0)
     is prepended via `with_sanity`. Opt-in: min-OI and `fresh_quotes`
     (drop known-stale Yahoo quotes)
   - **Algorithm** (`iv_algorithms.py`) — `global_poly` (default) or
     `per_expiration`; produces `iv_fitted`. Both accept `weights`
     (`oi` / `inv_spread` / `vega`) and `robust` (`huber` / `tukey`
     IRLS so outliers can't drag the surface toward themselves).
     `global_poly` drops its m²·√T curvature term below 3 expirations
   - **Score** (`iv_scores.py`) — the ranking key `signal_score`;
     defaults to `raw_pp` (= IV excess), with z-score, relative,
     execution-cost composite, VRP, and historical-percentile options
4. Compute IV excess = actual IV − fitted IV (positive = IV-rich,
   sits above the fitted surface)
5. Display ranked table including delta, annualized yield, and OI

The Single Ticker tab exposes a **Global / Per-expiry** preset toggle
(the "Fit:" radio) plus an **Advanced surface fit** expander to mix the
three stages; the CLI mirrors this via `--preset {current,v2}` /
`--algorithm` / `--fit-weights` / `--robust` / `--score` (the CLI
preset names differ from the UI labels). The
`percentile` score persists scans to a gitignored SQLite store
(`options-scanner/cache/`) and is blank until history accumulates.

## Running the tool

Always run from the **repo root** using `uv run`:

```bash
# Both calls and puts (default)
uv run options-scanner/run_scanner.py AAPL

# Covered call selection only
uv run options-scanner/run_scanner.py AAPL --calls

# Cash-secured put selection only
uv run options-scanner/run_scanner.py AAPL --puts

# Roll an existing short call
uv run options-scanner/run_scanner.py AAPL --roll \
    --type call --strike 185 --expiration 2026-01-16

# Adjust filters
uv run options-scanner/run_scanner.py AAPL --calls \
    --min-dte 400 --min-oi 50 --top 20
```

Never use `python` directly — dependencies won't be resolved.
Run `uv sync` from repo root after any `pyproject.toml` change.

## Output columns

| Column  | Meaning                                            |
|---------|----------------------------------------------------|
| Top     | Web UI only. Rank within the top-N list per type (1 = strongest signal); blank if not in top N |
| Strike  | Option strike price                                |
| Expiration | Expiration date                                 |
| DTE     | Days to expiration                                 |
| Bid/Ask/Mid | Market prices                                 |
| IV%     | Implied volatility (annualized %)                  |
| IV+pp   | IV excess above surface fit (positive = rich)      |
| _score_ | Active-score column (z-score, VRP, etc.) shown next to IV+pp when a non-default score drives ranking; header is the score's label |
| Delta   | Black-Scholes delta (call: 0–1, put: −1–0)         |
| Ann%    | Annualized yield: calls vs. spot, puts vs. strike  |
| OI      | Open interest                                      |
| Vol     | Web UI only. Today's trading volume (short-term liquidity) |
| NetCr   | Roll mode only: net credit received if rolled here |

## LT capital gains note

Selling an option and holding the short position for 366+ days
qualifies the premium for long-term capital gains rates. The tool
prints the earliest qualifying close date for a position opened today.

## YouTube production materials (sibling private repo)

Scripts, slide HTML, and image assets for the YouTube tutorials
about this tool live in a separate private repo at
`../stockpile-private/options-scanner/youtube/` (sibling directory
to this one). They are active working material and Claude should
treat them as in-scope when asked.

Layout: one subfolder per episode, under
`../stockpile-private/options-scanner/youtube/`.

- `ep1/` — first episode: full tool walkthrough. Script at
  `ep1/script.md`, slide HTMLs (`*-slide.html`), and `ep1/images/`
  with thumbnails and screenshots.
- `ep2/` — second episode in active drafting. Focused on the
  Schwab data source plus features added since ep1 (GEX chart,
  index tickers, stockpile CSV, polish). Script at `ep2/script.md`.
- Future episodes follow the same `epN/` pattern.

When the user asks about "the script", "the episode", or "the
YouTube video" without naming one, assume the most recent episode
folder. Read the existing script before making edits — episodes
follow a consistent template (slide cues in `[NN ...]`, on-camera
directions in parens, content blocks separated by `---`).
