# Pluggable IV Surface: filters, algorithms, and scores

## Context

A contributor (LGbengs) critiqued the Single Ticker tab's IV-surface
logic (see `SURFACE_REFACTOR.MD`). The critique has 7 points, which
sort cleanly into the three layers we want to make pluggable:

1. **Filter** — which options feed the regression.
2. **Algorithm** — how the surface is fit from those options.
3. **Score** — the per-contract signal that ranks "how IV-rich/cheap"
   a contract is relative to the surface.

Today all three are effectively hardcoded in `iv_surface.py`: a fixed
filter set (via the already-pluggable `iv_filters.py`), one global
5-term polynomial fit, and a single implicit score (`iv_excess`, shown
as "IV+pp") that drives ranking everywhere.

**Goal:** mirror the existing `iv_filters.py` registry pattern for
algorithms and scores, port the current behavior as the default
preset (so nothing changes until the user opts in), and implement all
7 critique points as selectable algorithm/score/filter options. A
"Current" vs. "Surface v2 / LGbengs" preset toggle (plus an Advanced
expander for free mixing) drives the UI.

**Vocabulary constraint** (`options-scanner/CLAUDE.md`): the output is
a screening heuristic, not a mispricing claim. All new score labels
and copy use "IV-rich / IV-cheap / outlier / stands above the
surface" — never "mispriced / overpriced / anomaly".

## Decisions (confirmed with user)

- Build **all 7 points fully**, including #4 (realized-vol/VRP) and #7
  (historical percentile, a new persistent history store).
- The new **`signal_score` becomes the ranking key** everywhere; it
  defaults to raw IV+pp so default-preset behavior is byte-identical.
- v2 surface algorithm = **per-expiration polynomial**. **SVI** is
  shown in the dropdown as a disabled "coming soon" entry (documented
  extension point, no implementation yet).
- UI = **presets + Advanced override**.

## The three-layer pipeline

Current `compute_iv_excess` becomes an orchestrator running three
stages. Each stage is a registry mirroring `iv_filters.py` (a
`dict[str, dict]` of `{fn, defaults, label}`, plus a hashable
`tuple[(name, frozenset)]` config and an `apply`/dispatch helper):

1. **Filter** (`iv_filters.py`, extend) → subset for the fit.
2. **Algorithm** (`iv_algorithms.py`, NEW) → `iv_fitted` (+`iv_excess`)
   for all rows.
3. **Score** (`iv_scores.py`, NEW) → `signal_score` for all rows, plus
   a `signal_kind` string naming the active score.

### Layer 1 — filters (`iv_filters.py`)

- Add `_exclude_earnings(df)` → drops rows with `earnings_count > 0`
  from the fit (critique #2). Register as `exclude_earnings`.
- **Ordering fix (blocker for #2):** `fetch.py` currently calls
  `compute_iv_excess` *before* `annotate_earnings`, so `earnings_count`
  is all-zero at fit time. Reorder so earnings annotation runs first.

### Layer 2 — algorithms (`iv_algorithms.py`, NEW)

Each algorithm: `fn(df, fit_mask, **kwargs) -> np.ndarray` returning
`iv_fitted` for every row. Registry entries:

- `global_poly` (DEFAULT) — the current 5-term fit
  (`a + b·m + c·m² + d·√T + e·m·√T`, `np.linalg.lstsq`), moved verbatim
  from `iv_surface.py`. Preserve the `<5 rows` / `LinAlgError` fallback
  (flat surface, `iv_fitted = iv`).
- `per_expiration` (critique #5) — fit IV vs. moneyness independently
  per expiration slice (`a + b·m + c·m²`); expirations with `<3` fit
  rows fall back to that slice's mean IV.
- **Weighting (critique #3)** — both poly algorithms take a `weights`
  kwarg (`none` | `oi` | `inv_spread`). Implemented as WLS by
  pre-multiplying `X` and `y` by `√w` before `lstsq`.
- `svi` — registered with label "SVI (coming soon)", rendered
  **disabled** in the dropdown; `fn` raises `NotImplementedError`.
  Docstring marks it as the extension point.

### Layer 3 — scores (`iv_scores.py`, NEW)

Each score: `fn(df, fit_mask, ctx, **kwargs) -> (np.ndarray, label)`
where `ctx` carries ticker-level context (`hv_20`, history handle,
spot). Registry entries:

- `raw_pp` (DEFAULT) — `iv_excess`; label "IV+pp". Reproduces current
  ranking exactly.
- `zscore` (critique #1) — `iv_excess / std(residuals on fit rows)`;
  label "IV z". Honest cross-ticker framing.
- `relative` (critique #1) — `iv_excess / iv_fitted`; label "IV rel%".
- `composite_exec` (critique #6) —
  `iv_excess / max(spread_pct, 0.05)`, `spread_pct=(ask-bid)/mid`;
  label "Score". Penalizes unfillable wide-spread contracts.
- `vrp` (critique #4) — ranks by `vr_ratio = iv / hv_20`; label "VRP".
- `percentile` (critique #7) — percentile rank of each contract's
  `iv_excess` within the trailing-N-day pooled distribution for the
  ticker (from the history store); label "IV %ile". Blank until
  history accumulates.

## New infrastructure for #4 and #7

### #4 realized vol (`hv_20` / VRP)

- In `fetch.py`, after fetching the chain, call
  `stocks_shared.yahoo.fetch_history` (already exists, `yahoo.py:152`)
  for ~30 trading days, compute
  `hv_20 = std(log returns, 20d) * √252`, attach as a column (constant
  per ticker) and pass into score `ctx`. `vr_ratio = iv / hv_20`.

### #7 historical percentile (`iv_history.py`, NEW)

First persistent state in the scanner. Use **stdlib `sqlite3`** (no
new dependency) at a gitignored `options-scanner/cache/iv_history.db`:

- Table `iv_history(ticker, scan_date, type, strike, expiration, dte,
  iv_excess)`.
- `record_scan(ticker, df)` — replace today's rows for the ticker
  (idempotent on same-day reruns), called *after* scoring from both
  `fetch.py` (web) and `main.py` (CLI).
- `percentile_for(ticker, iv_excess_series, window_days=30)` — used by
  the `percentile` score; pooled per-ticker distribution. Cold start:
  returns NaN until enough history; UI/CLI render blank.
- Add `cache/` to `.gitignore`. Refinement (bucket by delta/DTE)
  noted as future, out of scope.

## Rewiring ranking & outputs to `signal_score`

`signal_score` defaults to `iv_excess`, so these all stay identical
under the default preset:

- `compute/top_ranks.py` — sort `["signal_score", "open_interest"]`.
- `display/scan_results.py`, `display/chain_table.py`,
  `display/cli.py` — sort by `signal_score`; show a score column
  whose header is the active `signal_kind` label (keep IV+pp visible
  too).
- `display/portfolio_action_card.py` (`:61` sort, `:130` copy) and
  `explanation.py` — sort/label via `signal_score`.
- `spreads.py` — propagate `signal_score` to the short leg alongside
  `short_iv_excess`.
- `main.py` — sort by `signal_score`; JSON `_to_candidate` adds
  `signal_score`, `signal_kind`, and `hv_20` / `vr_ratio`.
- `chain_common.py::build_option_row` — seed `signal_score` (=
  `iv_excess`), `hv_20`/`vr_ratio` (NaN) so columns always exist.

## Config plumbing & caching

- `iv_surface.compute_iv_excess` gains `algo_config`, `score_config`,
  and a `ctx` (ticker/hv_20/history) argument; orchestrates the 3
  stages. Default args reproduce current output.
- `fetch.py` `fetch_and_enrich` / `fetch_position` gain `algo_config`
  and `score_config` params (hashable tuples) threaded into the
  `@st.cache_data` key, exactly like `surface_filters` is today.

## UI (`tabs/single.py`, extend the existing expander)

Replace the "Surface fit filters" expander with a "Surface fit"
section:

- **Preset radio**: `Current` (global_poly + raw_pp + today's filters)
  vs. `Surface v2 / LGbengs` (per_expiration + inv_spread weights +
  exclude_earnings + zscore).
- **Advanced expander**: existing filter checkboxes + an **Algorithm**
  `selectbox` and a **Score** `selectbox` built from the registries.
  Coming-soon entries (SVI) appear disabled. Selecting the preset sets
  the three configs; Advanced lets the user override freely.
- Build the hashable `algo_config` / `score_config` tuples the same
  way `surface_filter_config` is built (`single.py:242`), pass to
  `fetch_and_enrich`. Portfolio tab uses the default preset for now.

## CLI flags

`run_scanner.py` / `main.py`: add `--preset {current,v2}`,
`--algorithm`, `--score` (default = current). Keeps the CLI the stable
interface the planned dashboard agent will call.

## Critical files

NEW: `options_scanner/iv_algorithms.py`,
`options_scanner/iv_scores.py`, `options_scanner/iv_history.py`.

MODIFY: `iv_filters.py`, `iv_surface.py`, `fetch.py`,
`compute/top_ranks.py`, `display/scan_results.py`,
`display/chain_table.py`, `display/cli.py`,
`display/portfolio_action_card.py`, `explanation.py`, `spreads.py`,
`main.py`, `chain_common.py`, `tabs/single.py`, `run_scanner.py`,
`SKILL.md`, `options-scanner/CLAUDE.md`, `.gitignore`.

## Tests (infra exists; grow per `project_test_backlog`)

- Keep all current tests green, incl. `tests/test_iv_surface.py` — the
  default path (global_poly + raw_pp) must stay byte-identical.
- NEW: `test_iv_algorithms.py` (per-expiration fit on synthetic
  per-slice surfaces; WLS weighting), `test_iv_scores.py` (each score's
  formula + the raw_pp == iv_excess identity), `test_iv_history.py`
  (record idempotency, percentile against synthetic history, cold-start
  NaN), and an `exclude_earnings` case in the filter tests.

## Verification

1. `uv run pytest options-scanner/` — all green, new suites included.
2. `uv run streamlit run options-scanner/run_app.py`:
   - Default/"Current" preset on AMD → IV+pp values & Top ranks
     unchanged vs. `main`.
   - Switch to "Surface v2" → fit and ranking visibly change; score
     column header updates (e.g. "IV z").
   - On an earnings-spanning ticker, toggling `exclude_earnings`
     shifts the fitted line.
   - VRP column populates (non-NaN `hv_20`).
   - `percentile` blank on first scan; re-scan a few times → values
     appear, history DB grows under `options-scanner/cache/`.
3. `uv run options-scanner/run_scanner.py AMD --json` → new
   `signal_score` / `signal_kind` / `hv_20` fields present; default
   ordering matches `main`.
