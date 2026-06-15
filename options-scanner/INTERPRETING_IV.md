# Interpreting IV+pp

This tool ranks options by **IV excess** — the gap between an
option's implied volatility and a fitted volatility surface. The
`IV+pp` column shows that gap in percentage points: `+5.2` means
the option's IV is 5.2 pp above where the smooth surface predicts
it should sit for that strike and expiration.

This doc explains what that signal actually represents, what it
doesn't, and how to use it without overinterpreting it.

## Does higher IV mean better premium?

Mechanically: yes, with certainty. Implied volatility is back-solved
from the market price under Black-Scholes — it's the σ that makes
the model output match the observed quote. Vega (∂Premium/∂σ) is
strictly positive for both calls and puts, so an option trading at
higher IV than its neighbors is — by definition — trading at a
higher price than the model-fair value implied by those neighbors.
The premium collected per contract is unambiguously larger.

So if your only question is "will I collect more dollars selling
this strike versus a nearby strike with the same delta?", the
answer when IV+pp is positive is yes.

## Is that better premium *favorable*?

That's a separate question, and the answer is "it depends."

You're being paid more because the market expects (or fears) more
realized volatility on that strike than the fitted surface
suggests. The edge — if there is one — only exists when the fitted
surface is closer to the true future distribution than the market's
pricing is. Three scenarios:

- **The elevated IV is noise.** A stale print, thin liquidity, or a
  one-off demand imbalance pushed the IV above neighbors with no
  underlying information. Selling here captures real edge: you
  collect rich premium against a position whose actual risk matches
  the smoother surface.

- **The elevated IV reflects information you don't have.**
  Earnings, pending litigation, an FDA decision, a takeover rumor,
  dealer positioning the surface doesn't capture. Selling here
  looks rich in IV space but you're being paid fairly (or being
  underpaid) for a real risk the market is pricing in. The premium
  is bigger but so is the conditional payoff against you.

- **The elevated IV is structural skew.** Out-of-the-money puts
  routinely trade above the surface because there's persistent
  demand for downside hedges. A 2-D polynomial surface doesn't
  fully model that. The IV+pp is real but not edge — it's an
  artifact of fitting a smooth function to a non-smooth phenomenon.

The scanner's ranking implicitly assumes outliers are noise. That
assumption is where the uncertainty lives — not in the price↔IV
mechanics.

## Reading IV+pp magnitudes

A rough heuristic for what the magnitudes mean in practice:

- **Under ~3pp** — the chain's IV is roughly uniform; ranking is
  mostly noise. No strike stands out from the surface. This is the
  common case for liquid, low-event tickers.
- **3–5pp** — moderate elevation. Worth a glance, especially if it
  clusters at a specific strike or expiration.
- **5pp+** — meaningfully above neighbors. The kind of strike
  worth investigating on your broker. Still not a mispricing claim
  — see the three scenarios above — but a stronger ranking signal.

## What this is not

- **Not a mispricing claim.** Vol smiles and skew are real. The
  no-arbitrage principle does not require the surface to be smooth.
- **Not arbitrage.** Even an IV genuinely above the true surface is
  not a riskless trade — you take on the option's underlying
  exposure when you sell it.
- **Not a recommendation.** Treat every outlier as a starting point
  for further analysis on your broker, not a trade signal.

## Earnings and IV

The scanner tracks only the **next** earnings date — further-out
dates the data source returns are estimates from the historical
cadence, not company-confirmed, so it treats earnings as a single
upcoming event. A `⚠` next to an expiration flags one that is **≤60 DTE
and expires after that date**: its IV (and so its IV+pp) carries
earnings premium, and it's the slice excluded from the surface fit.
Elevated IV near earnings is expected and is not a free
lunch — the market is pricing in the uncertainty of the
announcement. Selling into earnings IV is a strategy in itself
(short straddle / iron condor / etc.), but it goes beyond what
this IV-vs-surface screen surfaces. An IV+pp spike right before
earnings is information you already had.

## The fitted surface

The surface is a 2-D fit: IV ≈ f(log-moneyness, √T). It assumes IV
varies smoothly across strikes (the smile) and across time (term
structure).

Before fitting, the scanner applies a configurable data-cleaning
pipeline to remove quotes that would distort the surface:

- **OTM only** — deep-ITM options inherit inflated IV from their
  put-call-parity counterparts; excluding them keeps the fit in
  the tradeable range
- **Spread filter** — wide bid-ask spreads signal illiquid or
  stale quotes; those options are dropped from the regression
- **Delta range** — options with |Δ| outside 0.10–0.95 are
  excluded by default; the 0.10 floor drops far-OTM wings whose
  thin, wide-spread quotes (and unreliable broker IV) would
  otherwise distort the surface curvature
- **Earnings (short-dated only)** — options expiring within 60 DTE
  that span the next earnings carry a jump premium that would pull
  the surface up, so they're left out of the fit. Longer-dated
  contracts stay in: one earnings is a negligible share of their
  variance, and excluding them would needlessly thin — or, at long
  DTE, empty — the fit. A guard keeps this filter from ever emptying
  the fit subset

These defaults are configurable under the **Advanced surface fit**
expander in the Single Ticker tab (the **Fit:** preset toggle picks
Global vs. Per-expiry). All options still appear in the chart and
table — only the regression itself is filtered.

To see which contracts fed the fit — and why a fit sometimes falls
back to tracing the quotes — open the **Surface-fit diagnostics**
expander below the chart: a filter funnel shows where contracts dropped
out, and a per-expiration table flags slices fit by fallback. On the
chart itself, filled dots fed the fit and hollow dots were filtered
out, and the **All expirations** view toggle overlays every
expiration's fitted line so you can see the whole surface at once.

The surface does not model:

- Asymmetric skew beyond what the polynomial captures
- Strike-specific events (e.g. a special dividend ex-date inside
  one expiration)
- Dealer positioning concentrating at specific strikes
- Stale quotes outside market hours (especially on Schwab)

When you see an outlier, asking "could any of the above explain
it?" is usually a faster gut check than placing a trade.

## Buy mode (the inverse)

`--buy` flips the ranking: lowest IV+pp first. The same mechanics
apply in reverse. An option trading meaningfully below the surface
is priced under model-fair value relative to its neighbors. Whether
that's edge for the buyer depends on the same three scenarios — is
the low IV noise (stale, thin), information (the market knows
something benign is coming), or structural (a strike where supply
exceeds demand)?
