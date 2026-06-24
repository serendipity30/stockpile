# GEX changes — test plan

Working notes for verifying last night's GEX work before pushing /
closing the issues. Branch `main`, uncommitted changes in:

- `compute/gex_summary.py`
- `display/gex_chart.py`
- `display/gex_strikes_table.py`
- `tabs/gex.py`

## What changed

1. **Shared GEX primitive.** The per-strike GEX math (calls +, puts −)
   was duplicated in the chart, the strikes-of-interest table, and the
   summary. It's now a single `per_strike_gex()` in `gex_summary.py`
   that all three call. This version also adds a `× 0.01` factor (the
   standard "per 1% move" GEX definition) the old code lacked — so
   **absolute GEX numbers are now ~100× smaller than before**. Bar
   shapes are unchanged (relative); the printed numbers shift.

2. **"Zero-gamma" → "Gamma flip" rename + new chart line.** Relabeled
   everywhere a user sees it (metric, table column, summary column,
   tab explainer), and added a **violet dashed vertical line** on the
   chart marking the flip level, alongside the existing spot line.

## How to run

```
uv run streamlit run options-scanner/run_app.py
```

Opens at `http://localhost:8501` → **GEX** tab (and the Single Ticker
tab's GEX chart).

## Testing checklist

1. **It launches at all.** The chart and table now import
   `per_strike_gex` from the compute module — opening the GEX tab
   confirms there's no typo / circular import.

2. **Three views agree.** For one ticker, the chart bars, the
   strikes-of-interest table, and the GEX summary row should reflect
   the *same* per-strike values. On a liquid chain (SPY / NVDA / AMD),
   check the table's top wall/amp strikes line up with the tallest
   +/− bars.

3. **The new gamma-flip line.** Confirm the chart shows **two**
   vertical lines — spot plus a violet dashed "Gamma flip $X" line.
   - Flip near spot → labels are offset (flip label one line lower,
     `dy=16`); verify they read cleanly.
   - Flip far from spot → x-axis is zoomed to GEX-carrying strikes, so
     a far-off flip line may clip at the edge or sit off-screen.
   - No flip (gamma never crosses zero) → the violet line should be
     absent, not error.

4. **Numbers didn't get weird from the ×0.01.** Total GEX and table
   values are ~100× smaller. Confirm formatting still reads sanely (no
   `0.00` collapse) and **Regime** still matches the sign of net GEX.

5. **Consistent rename.** "Gamma flip" everywhere user-facing — metric
   (g3), chart line label, strikes table, multi-ticker summary column,
   tab explainer. No leftover "Zero-Γ".

Cosmetic: `gex_chart.py:5` module docstring still says "Zero-gamma
level" — harmless, fix whenever.

## Issues found while testing (2026-06-04)

### A. Bad centering on Single Ticker GEX chart

**Symptom:** 30–60 DTE scan rendered the bars only in part of the
chart width, dead space filling the rest.

**Root cause (confirmed via live repro):** the pre-existing zoom math
in `gex_chart.py`. The window is `x_min = min(core_lo, spot) * 0.97`
/ `x_max = max(core_hi, spot) * 1.03`, where `core_lo/core_hi` are the
min/max strikes of the 99%-|GEX| set. When that core sits to one side
of spot — or a single far strike stretches it — the window balloons
and the bars cluster in a fraction of the width. Repro: QQQ core =
[194.78, 455.0] with spot 744.21 → window **[188.9, 766.5]**.

**Not** caused by last night's changes — this logic predates the diff,
and the new flip line is NaN-guarded / additive.

**Fix (applied 2026-06-04):** the x-window is now centered on spot. The
half-width reaches the farthest 99%-|GEX| core edge (core always
included), floored at ±2% of spot, optionally extended to reach the
gamma flip (capped at ~1.6x the core reach), padded 4%, then applied
symmetrically: `x = [spot − half, spot + half]`. Spot reads at the
middle every scan and a lopsided core can no longer shove bars to one
side. Verified on Schwab SPY: core [600, 825], flip 579 → window
[572, 935.6], midpoint = spot 753.8.

### B. Chart never renders (1–60 DTE + GEX tab)

**Symptom:** the 1–60 DTE Single Ticker chart never appeared; same on
the GEX tab. No Streamlit error shown.

**Root cause (confirmed via live repro):** the *silent early return*
at `if gex.empty or gex["gex"].abs().sum() == 0: return` in
`show_gex_chart`. On a chain with no usable open interest the per-strike
GEX sums to zero and the function bails with no user-facing message, so
the chart just vanishes. Repro: SPY returned a chain with `abs_sum == 0`
(gamma was clean — no NaN/inf — the OI was the problem). The
strikes-of-interest table has the same silent guard.

**Not** caused by last night's changes — `× 0.01` is a uniform scale
and can't drive `abs_sum` to zero.

**Caveat:** Yahoo was badly degraded during repro (pre-market
2026-06-04 — AMD/SPY/QQQ 30–60 empty, SPY 404 "delisted", QQQ 15 rows),
so the 1-60-vs-30-60 difference under *healthy* full-chain data was not
reproduced. Re-test during market hours; if 1–60 still blanks with real
OI present, that's a separate cause to chase.

**Fix (applied 2026-06-04):** both silent guards in `show_gex_chart`
now emit an `st.info` instead of returning blank — "no gamma data" for
the missing-column case, "no open interest across this chain's strikes
in the selected DTE range" for the zero-`abs_sum` case. The strikes
table (`show_gex_strikes_of_interest`) stays silent on purpose — it
always renders directly below the chart, so the chart's message covers
it and avoids a duplicate notice. Still to verify with healthy
market-hours data.

### C. Schwab GEX chart blanks when the gamma flip is far out (REGRESSION)

**Symptom:** Single Ticker tab, Schwab SPY, Calls·SELL 1–60 DTE — GEX
chart area blank, but the Gamma flip metric card showed $245. YF on the
same scan rendered fine and had no flip card.

**Root cause (confirmed via live Schwab fetch 2026-06-04):** the new
gamma-flip line. Schwab gamma is clean (no sentinels/NaN); the GEX walls
sit near spot (740–765, spot 753) so the chart zooms x to ~[720, 790],
but cumulative GEX first crosses zero at strike 245 — far outside that
window. The flip line drawn at x=245 blows out the layered chart's
shared x-axis and collapses the real bars to an invisible sliver. The
spot line never does this because the zoom window is built to always
include spot. YF dodged it: its cumulative GEX never crossed zero
(zero_cross NaN) so no flip line was drawn.

**Fix (applied 2026-06-04):** only draw the flip line/label when
`x_min <= zero_cross <= x_max` (plus `clip=True` on the marks). The flip
value still shows in the metric card. Verify: re-scan Schwab SPY — the
bars should render.

**Follow-up (resolved 2026-06-04):** flip now computed by a shared
`gamma_flip_strike` helper — the actual cumulative-GEX sign change
nearest spot (interpolated), used by both the chart metric and the
summary table (they agree now). Fixes the bogus far-tail value: Schwab
SPY 245 → 579. The spot-centered window now extends to include the flip
when that keeps it within ~1.6x the core's reach, so the line draws
(Schwab SPY: window → [572, 935.6], flip 579 shown). A flip beyond that
stays card-only (in-range guard) so it can't shrink the bars to a sliver.

### D. YF gamma-flip card never appears in the UI (RESOLVED 2026-06-04)

**RESOLUTION:** not a code bug — a **stale Streamlit session**. A
temporary debug `st.caption` added to `show_gex_chart` forced a clean
module reload, after which the YF flip rendered correctly: live debug
read `flip=774.47 total_gex=1.42e9 strikes=398 df_rows=3487
cum=[-4.7e9,1.4e9] provider=yahoo spot=756.87` — matching the
script repro exactly. The earlier "never" was the running session not
picking up the `gamma_flip_strike` change (and/or a stale cached df);
Streamlit's hot-reload is unreliable for deeply-imported modules +
`@st.cache_data`. Fix going forward: fully restart `streamlit run`
after editing imported modules. Debug line removed.


**Symptom:** user reports the "Gamma flip" card *never* shows on a YF
Single Ticker scan; it does show on Schwab. Confirmed by the user
2026-06-04 (scanned SPY/YF live — still no card).

**What's verified:**
- `gamma_flip_strike` is provider-agnostic and works on YF data.
- A 6-arg `fetch_and_enrich("SPY", "calls"/"puts"/"both", 1, 60,
  "yahoo", None)` diagnostic returns a **two-sided** chain (calls,
  puts, both all identical — 398 strikes) whose cumulative GEX
  **crosses sign**, giving flip ≈ **$774.5**. So by my repro YF *should*
  show a flip right now — but the UI doesn't.
- `fetch.py`: `fetch_and_enrich` defaults `fit_both_sides=True`, so
  even "calls"/"puts" fetch BOTH sides and return the full two-sided
  chain. So single-sided is NOT the cause (my earlier calls-only theory
  was wrong — disproven by repro).
- `res["df"]` (= `df_fit_full`, fed to `show_gex_chart`) is the
  `fetch_and_enrich` output directly (single.py:465), no extra filter
  at the call site.

**The unclosed gap:** my diagnostic passed only 6 args; the UI
(single.py:383-389) also passes `surface_filters`/`algo_config`/
`score_config`. They *default* to `DEFAULT_CONFIG` (which my repro also
used), so in theory they match — yet the UI shows no flip. Not yet
explained.

**INVESTIGATED 2026-06-04 ~1pm — no code-path difference found:**
- Default Single Ticker preset is "Global" = `FILTER_DEFAULT` (single.py
  `_SF_PRESETS`, line 51) — identical to the surface filter my 6-arg
  repro already used. So the surface filter is NOT the difference.
- Exact-path repro (`fetch_and_enrich("SPY","calls",1,60,"yahoo",None)`)
  RIGHT NOW returns 398 strikes, two-sided, cumulative crosses sign
  *robustly* (−5.9e9 → +1.9e9, flips ~766–776) → flip ≈ **$770**. So the
  UI should show it; the computation in `show_gex_chart` is identical
  (`df_fit_full` = `res["df"]` = fetch output, single.py 465→536).
- `fetch_and_enrich` does NOT side-filter (unlike `fetch_position`,
  fetch.py:140); `compute_iv_excess` doesn't drop the strikes (398 kept).

**Conclusion:** likely NOT a bug. YF's crossing is borderline (net-neg
earlier today → no flip; net-pos now → flip), so it legitimately shows
no card much of the time. Remaining suspect for a *concurrent*
mismatch: stale `@st.cache_data(ttl=300)` df in the user's session
(user declined to rescan live, so "never" may be from an earlier
non-crossing scan).

**TEST FOR USER:** nudge the DTE range in the UI (busts the cache key) +
rescan YF SPY → should surface flip ~$770. If it still doesn't show with
crossing data, add a one-line debug print of `zero_cross` in
`show_gex_chart` to capture the live value — only then is it a render
bug.

## Min/max DTE filter on GEX tab — IMPLEMENTED 2026-06-04

The GEX tab now has **Min DTE / Max DTE** inputs (default 0–60, Min
floored at 0 so 0DTE is allowed, Max at 1) replacing the hardcoded
`fetch_and_enrich(t, "both", 0, 60, …)`. The scanned range is stored in
`gex_results` and reflected in the caption, the EXPIRATIONS card, and
the "no options" message. Lets the GEX tab match the Single Ticker
chart's DTE range for apples-to-apples.

Known asymmetry left as-is (per user 2026-06-04): the Schwab chain
fetcher (`schwab_chain.py:72`, `if dte <= 0: continue`) drops same-day
expiries, so 0DTE only flows through on Yahoo. The Min DTE help text
notes this. Single Ticker still floors Min DTE at 1 by design (0DTE is
degenerate for the IV-surface / premium-selling workflow).

## OPEN — chart bar density on dense-strike underlyings

The one remaining open thread (filed to the GitHub issue 2026-06-04, not
built). On SPY/QQQ/SPX the strike grid is $1–$5, so the spot-centered
zoom window holds ~250 strikes and the bars render as unreadable threads
— not useful for reading a GEX profile. Fine on coarse-strike names.

Proposed options (decision pending):
1. **Bin strikes into round buckets** (recommended) — adaptive "nice"
   width (1 / 2.5 / 5 / 10 / 25…) chosen so the window lands at ~30–40
   bars (~$10 for SPY); GEX summed per bucket. Bin **only the chart
   bars** — keep the strikes-of-interest table and `gamma_flip_strike`
   at exact per-strike precision. Standard GEX-profile look.
2. **Tighter default zoom** — narrow the window closer to spot. Simpler,
   but SPY's $1 grid is still dense and you lose far walls (e.g. the
   ~$600 put wall that pulls the current window wide).
3. **Both** — round buckets + a narrower window.
