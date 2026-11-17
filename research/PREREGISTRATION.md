# Pre-registration: priced-in test and opportunistic insider buys

*Written 17 Nov 2026, before any of the analyses below were run. The git commit
that adds this file is the timestamp. Changes after that commit must be listed
in the "Amendments" section at the bottom, with the date and the reason.*

## 1. Holdout

- **Development sample:** qualifying buys filed 2010-01-01 to 2024-12-31.
- **Holdout:** qualifying buys filed 2025-01-01 onward. It is opened **once**,
  after the development analysis is final, with
  `python -m research.analysis.h_preregistered --open-holdout`. Every opening
  is appended to `research/HOLDOUT_LOG.md`.

**Prior exposure, disclosed honestly.** The holdout is fresh for these
hypotheses, not untouched data. Earlier work (Q1–Q4 in `WRITEUP.md`) computed
pooled statistics over 2010–2026, including:

- base rates, and the AI rating results (Q1 live ratings are all 2025–26 filings);
- returns by quintile of the stock's prior 20-day return, pooled over all
  years, versus the Russell 2000. The lowest quintile returned +1.0% at 60 days
  and −2.1% at 180 days, and the top-minus-bottom spread was not significant.
  H2 below is therefore not a naive hypothesis: a pooled dip effect has already
  been looked at and was not found;
- track-record persistence (Q2, tested on 2018–2026).

## 2. Population

Qualifying buys as defined by `research/build_dataset.py` and `config.yaml`
(code P, at least $5,000, trade price at least $1, no amendments or duplicates,
filed within 365 days of the trade, no suspect price tick in the window), with
a price on the first trading day after the filing.

## 3. Outcome

**Primary outcome:** cumulative abnormal return (CAR) from the close of the
first trading day after the filing date to 60 trading days later. Daily
abnormal return = stock return − risk-free rate − Σ β·factor, using the
Fama-French five factors plus momentum (Ken French daily data). Betas are
estimated per event on trading days t−269 to t−20 relative to the trade date,
with at least 120 valid days required.

- Winsorized at the 1st and 99th percentiles of the development sample; the
  holdout is clipped at the same cutoffs.
- **Secondary outcomes**, reported but not used for decisions: the same CAR at
  20 and 180 days; a market-model CAR at 60 days; excess return versus the
  Russell 2000 ETF (IWM) at 60 days; the primary outcome net of the assumed
  trading costs in `config.yaml`.

## 4. Descriptive analysis: how much is priced in before you can buy?

No hypothesis test. For qualifying buys, mean CAR (and IWM excess) over each window:

| Window | From (close) | To (close) | Who can earn it |
|---|---|---|---|
| Pre-trade | 20 trading days before the trade | trade date | nobody (it is the "dip") |
| B: trade to disclosure | trade date | last trading day before the filing date | only the insider |
| C: disclosure | last trading day before the filing | first trading day after the filing | partly a very fast trader; mostly no one |
| D: tradeable | first trading day after the filing | +5, +20, +60, +180 trading days | anyone |

Reported for all buys and by group (officers & directors, 10% holders, the
trader types and dip groups below).

**Interpretation rule, fixed in advance:** if B + C is clearly positive and D
is near zero, the information exists but is priced before an outside investor
can act on it.

## 5. Definitions

- **Trader type** (following my reading of Cohen, Malloy & Pomorski, *Decoding
  Inside Information*, J. Finance 2012), computed per insider (SEC CIK, across
  companies) from all open-market trades (codes P and S, amendments and
  duplicates excluded) that were filed before the current filing:
  - **eligible:** traded in each of the three calendar years before the year of the current trade;
  - **routine:** eligible, and traded in the same calendar month in all three of those years;
  - **opportunistic:** eligible and not routine;
  - **insufficient history:** everyone else (includes first-time traders).
- **Dip:** the stock's excess return versus IWM over the 20 trading days ending
  at the trade-date close is −10% or worse.
- **Post-report:** the trade date is 0–30 calendar days after the company's
  latest 10-Q or 10-K filing date (from SEC XBRL, filed before the trade). This
  is a proxy for the post-earnings trading window; actual earnings-release
  dates are not available.
- **Infrequent buyer:** an officer or director (not a 10%-holder-only filer)
  with no open-market purchase, in any company, in the 24 months before the
  trade date (counting only purchases filed before the current filing).

## 6. Hypotheses (primary family, development sample, primary outcome)

| ID | Contrast | Population | Predicted sign |
|---|---|---|---|
| H1 | opportunistic minus routine | classified buys | + |
| H2 | dip minus no dip | all qualifying buys | + |
| H3 | dip and post-report minus all others | buys with both measures known | + |
| H4 | opportunistic and dip minus all other classified buys (the author's own strategy) | classified buys with dip known | + |
| H5 | infrequent minus frequent officer/director buyers | officers & directors | + |

## 7. Tests and decision rules

- **Inference:** difference in means, 95% CI and two-sided p from a bootstrap
  resampling whole filing months (`n_boot` in `config.yaml`); Benjamini–Hochberg
  across H1–H5.
- **"Supported in development"** requires all three of:
  1. FDR-adjusted p < 0.05;
  2. the same sign in each development sub-period (2010–14, 2015–19, 2020–24);
  3. a positive mean for the top group after assumed trading costs (reported; a
     negative value is noted as "real but not tradeable" rather than rejecting
     the hypothesis).
- **Holdout:** only hypotheses supported in development are tested, one-sided
  in the predicted direction, Holm-adjusted across those tested, at α = 0.05.
  All holdout numbers are reported whatever they show.

## 8. Known limitations, stated in advance

- **Survivorship:** the company universe is currently listed tickers, so
  delisted companies are missing.
- **Incomplete history:** the filing backfill is about half complete, so some
  routine traders will be classified as "insufficient history".
- **Earnings proxy:** periodic-report dates lag earnings releases by days to weeks.
- **Factor betas versus characteristics:** factor betas estimated from past
  returns do not fully remove characteristic effects (e.g. a stock's own momentum).
- **180-day holdout results** for 2026 filings mature through 2027.

## Study 2: can a real-time reader capture the disclosure reaction?

*Added 17 Nov 2026, before any of these measurements were run.*

**Motivation.** In the development sample, 1.6% of excess return (factor
BHAR, 95% CI +1.3% to +1.8%) arrives in the two-day disclosure window, and
little arrives afterwards. Part of that window may be tradeable by someone who
reads each Form 4 the moment EDGAR accepts it.

**Data.**
- **Acceptance time** for each filing, from SEC submissions data (UTC,
  converted to New York time).
- **Daily open and close prices** from Yahoo, adjusted with the same factor as
  the close. No intraday prices are used.

**First available price (P_first)**, by acceptance session on New York trading days:

| Accepted | Price just before (P_before) | First price a daily-data trader can get (P_first) |
|---|---|---|
| Before 9:30, or on a non-trading day | previous close | next open |
| 9:30–16:00 (market hours) | that day's open | that day's close (conservative: the intraday move after acceptance is not measurable) |
| 16:00 or later | that day's close | next trading day's open |

**Measures**, all as excess returns versus IWM over the same timestamps,
qualifying buys in the development sample (filed 2010–2024):

- **Gap** = P_before → P_first: reaction an outsider cannot capture with daily prices.
- **Capture** = P_first → standard entry (the close of the first trading day
  after the filing date): what acting immediately adds over the original design.
- **Real-time 60-day** = P_first → 60 trading days after the P_first day.

**Hypotheses** (predicted sign +):

| ID | Test |
|---|---|
| R1 | mean Capture > 0 |
| R2 | mean real-time 60-day excess return, net of the assumed costs in `config.yaml`, > 0 |

**Decision rules.**
- Same as section 7: month-clustered bootstrap, Benjamini–Hochberg across R1
  and R2, the same sign in each sub-period (2010–14, 2015–19, 2020–24), and a
  one-sided test in the 2025+ holdout only for hypotheses supported in development.
- Descriptive breakdowns (by session, officers and directors versus 10%
  holders, liquidity tier) are reported but not used for decisions.

**Known limitations.**
- Daily data only: for market-hours filings the intraday reaction after
  acceptance is counted as lost, which understates what a fast trader captures.
- Opening auctions in small caps have wide spreads; the cost tiers are
  probably optimistic for open entries.

## Amendments

**Amendment 1 (17 Nov 2026, after the first development run).** Added a
buy-and-hold abnormal return (BHAR: compounded stock return minus compounded
factor-predicted return) as a secondary outcome and to the window table.

- **Reason.** The first run showed factor-adjusted CARs well above the
  compounded excess return versus IWM: +2.6% versus +0.3% at 60 days, and +5.4%
  versus −0.8% at 180 days. A CAR sums daily returns, which overstates
  long-horizon returns of volatile stocks by roughly half the daily variance per
  day (about 0.05–0.08% a day for typical small caps). This is a known
  event-study problem (long-horizon CAR versus BHAR), and it should have been
  anticipated in the original plan.
- **What does not change.** The primary outcome and the decision rules are
  unchanged, so the H1–H5 verdicts from the first run stand as recorded.
  BHAR is used only to interpret the window table.
- **Exploratory addition.** A table describing who the routine and
  opportunistic buyers are (role, sector, size, liquidity, volatility) was
  added, prompted by H1 coming out opposite to the prediction. It is labelled
  exploratory and cannot support a claim without a new pre-registered test.

**First development run (17 Nov 2026), recorded before amendment 1.**

| Hypothesis | 60-day CAR spread (95% CI) | FDR p | Verdict |
|---|---|---|---|
| H1 opportunistic − routine | −3.75% (−6.4, −1.1) | 0.028 | not supported; significant in the opposite direction, with signs −7.3 / +0.6 / −5.7 across sub-periods |
| H2 dip | +0.1% (−2.7, +3.3) | 0.96 | not supported |
| H3 dip & post-report | +1.0% (−2.0, +4.3) | 0.90 | not supported |
| H4 opportunistic & dip | −1.9% (−7.5, +3.1) | 0.90 | not supported |
| H5 infrequent officer/director buyer | +0.2% (−1.0, +1.1) | 0.96 | not supported |

No hypothesis met the development criteria, so none qualifies for the holdout.
