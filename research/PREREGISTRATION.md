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

## Study 3: ten hypotheses chosen by the author (18 Nov 2026)

*Added before any data for these definitions was extracted or examined.*

**Samples.**

| Stage | Filings | Use |
|---|---|---|
| Development | 2010–2024 | estimation |
| Holdout A | 2025-01-01 to 2026-11-30 | first confirmation |
| Holdout B (forward) | 2026-12-01 onward | final confirmation, once outcomes mature |

Prior exposure of Holdout A, disclosed:
- Its pooled returns entered the Q1–Q4 summaries.
- It was opened once for Study 2's R1, which displayed only the capture measure.

None of the measures below has been computed on it.

**Primary outcome.** Factor-adjusted buy-and-hold abnormal return (Fama-French
five factors plus momentum, betas from trading days −269 to −20 relative to the
trade) from the standard entry (the close of the first trading day after the
filing date) to 60 trading days later. It is winsorized at development 1%/99%
cutoffs, separately for buys, sells and option exercises.

The exception is S5, whose outcome is defined there.

- **Secondary outcomes** (not used for decisions): the same at 20 and 180
  days, and excess return versus IWM at 60 days.
- **Populations:** qualifying buys and qualifying sells as in `build_dataset.py`.
  Option-exercise events are defined in S9.

**Hypotheses.**

| ID | Population | Contrast (top minus bottom) | Predicted sign |
|---|---|---|---|
| S1 | buys | top minus bottom quintile of the disclosure-window return (BHAR from the close before the filing date to the entry close); quintile cutoffs from development | + (under-reaction) |
| S2 | buys | price fell between trade and filing (BHAR from the trade-date close to the close before the filing date ≤ −2%) minus price rose (≥ +2%) | + |
| S3 | buys | "switcher": the insider had ≥ 3 open-market sells and no open-market buys in the 36 months before the trade, minus other buys by insiders with ≥ 1 open-market trade in those 36 months | + |
| S4 | buys | accumulation: the filing's purchases span ≥ 2 calendar days, or the same insider filed a qualifying buy in the same company in the previous 30 days; minus neither | + |
| S5 | earnings announcements | 3-day excess return versus IWM around a company's earnings release, with ≥ 1 qualifying officer/director buy filed in the 90 days before the release, minus releases without | + |
| S6 | buys made 0–30 days after an earnings release | the release's 3-day excess reaction ≤ −5% (buying after an earnings drop), minus > −5% | + |
| S7 | buys | discretionary (filing does not mention Rule 10b5-1) minus plan purchases (filing mentions 10b5-1 or ticks the 10b5-1 box) | + |
| S8 | sells | discretionary sells (no 10b5-1 mention and no tax-withholding mention) minus plan sells (10b5-1 mentioned or ticked); outcome is the stock's return | − |
| S9 | officer/director option exercises | exercise-and-hold (an M transaction and no open-market S in the same filing) minus exercise-and-sell (M with S) | + |
| S10 | buys by 10% holders | an initial or amended Schedule 13D on the company accepted in the 365 days before the filing date (active intent), minus no 13D | + |

**Definitions and data.**
- **Earnings releases:** 8-K filings listing item 2.02, from SEC submissions
  data, with exact acceptance times.
- **Announcement day:** the acceptance day if accepted on a trading day before
  16:00 New York time, otherwise the next trading day.
- **3-day window:** the close two trading days before the announcement day to
  the close one trading day after.
- **Filing-text flags** (10b5-1, tax withholding) are filing-level text
  searches of the Form 4 XML, so they apply to every reporting person on that filing.
- **Option exercises:** filings with an M transaction, excluding amendments.
  There is no size filter. The trade date is the earliest transaction date in the filing.
- **"Open-market trades"** for S3 are code P and S events (amendments and
  duplicates excluded), counted only if filed before the current filing.

**Tests and decision rules.**
- **Inference:** difference in means, 95% CI and two-sided p from the
  month-clustered bootstrap; Benjamini–Hochberg across S1–S10.
- **Supported in development** requires:
  - FDR p < 0.05;
  - the predicted sign;
  - the same sign in each development sub-period (2010–14, 2015–19, 2020–24).
- **Holdout A:** only supported hypotheses; one-sided in the predicted
  direction, Holm-adjusted, α = 0.05; only the tests are printed.
- **Holdout B:** the same tests rerun once outcomes have matured. A hypothesis
  is called confirmed only if it passes both holdouts.
- **After costs:** each top group's mean net of assumed costs is reported
  (for S8, the short side is not costed).

**Known limitations, stated in advance.**
- **Text flags are crude.** A filing can mention 10b5-1 for one transaction but not another.
- **Plan purchases are rare,** so S7 may have little power.
- **Schedule 13D is matched to the company, not to the buyer,** so S10 tests
  "a 10% holder buying in a company under active ownership", not "the activist buying".
- **Earnings releases before EDGAR item tagging** may be missing, so coverage
  is checked and reported by year.

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

**Study 2, development results (run 18 Nov 2026), recorded before the holdout was opened.**
64,609 of 64,609 development buys matched to an acceptance time. Sessions:
65% after the close, 29% during market hours, 6% pre-market. None was
accepted after the date on the filing.

| | Mean (95% CI) | Median | By sub-period | FDR p | Verdict |
|---|---|---|---|---|---|
| Gap (lost to a daily-data trader) | +0.99% | | | | descriptive |
| R1 Capture | +0.33% (+0.26, +0.41) | +0.09% | +0.34 / +0.34 / +0.32 | < 0.0001 | supported in development |
| R2 60 days from first price, net of costs | −1.33% (−2.28, −0.30) | −2.94% | −0.57 / −1.03 / −1.79 | 0.009 | not supported (significantly negative) |

Only R1 qualifies for the holdout test.

**Display change before opening the holdout (18 Nov 2026).** In
`--open-holdout` mode, `realtime.py` now prints only the pre-registered test,
so that 2025+ returns are not revealed for any later hypothesis. An exploratory
breakdown of capture by liquidity tier was added for the development sample only.

**Study 2, holdout result (opened 17 Nov 2026, 16:54 UTC, R1 only).**
11,238 of 11,243 holdout buys (filed 2025 onward) matched to an acceptance time.

| | Mean (95% CI) | Median | Hit rate | n | One-sided p | Verdict |
|---|---|---|---|---|---|---|
| R1 Capture | +0.28% (+0.06, +0.50) | +0.13% | 52.0% | 11,232 (21 months) | 0.0067 | **confirmed** |

The holdout has now been used once, for the capture measure only. Any future
hypothesis tested on 2025+ data must disclose this.


**Study 3 clarification (18 Nov 2026, before any Study 3 data was extracted).**
S4's "the filing's purchases span ≥ 2 calendar days" is implemented as
purchases on two or more different calendar days (last transaction date after
the first). The option-exercise events' liquidity for the cost estimate is the
same 20-day median dollar volume used elsewhere.

**Amendment 2: date corrections (17 Nov 2026, committed after 17:51 UTC).**
Several dates above were typed incorrectly as 18 Nov. The git commit times,
which are what this document relies on, are authoritative. The earlier text is
left unchanged.

| Text above | Correct date | Commit |
|---|---|---|
| "Study 3 … (18 Nov 2026)" | 17 Nov 2026, 17:14:27 UTC | `4b1cfa2` |
| "Study 2, development results (run 18 Nov 2026), recorded before the holdout was opened" | run and recorded 17 Nov 2026, committed 16:50:40 UTC, before the holdout was opened at 16:54 UTC (`HOLDOUT_LOG.md`) | `ae669f9` |
| "Display change before opening the holdout (18 Nov 2026)" | 17 Nov 2026, 16:50:40 UTC | `ae669f9` |
| "Study 3 clarification (18 Nov 2026 …)" | 17 Nov 2026, 17:18:18 UTC | `6714c53` |

This branch has never been force-pushed, and will not be, so these commit
times can be checked on GitHub.

**Amendment 3: additions to Study 3 (17 Nov 2026, before any Study 3 data was extracted).**

*(a) Plan flags, measured two ways.* Since April 2023, Form 4 has a checkbox
for trades made under a Rule 10b5-1 plan. Before that, plans appear only in
free-text footnotes. Three filing-level flags replace the single flag:

- **`plan_text`:** after removing every XML element whose name contains "10b5",
  the filing text mentions "10b5-1" (any separator).
- **`plan_box`:** an XML element whose name contains "10b5" has the value 1 or true.
- **`plan_negated`** (diagnostic only): the text says "not … pursuant to …
  10b5-1" or similar.

S7 and S8 keep their pre-registered definition: plan = `plan_text` or `plan_box`.

Before extraction, a read-only query counts, by year, filings that mention
10b5-1, filings with an element named like the checkbox, and negated mentions.
It also lists the element names found in 2023+ filings. The output is recorded
in the next amendment.

*(b) S7r and S8r, secondary tests: did the 2023 rule change alter the
plan-versus-discretionary gap?*

| | Before the reform | After the reform |
|---|---|---|
| Filed | 2010-01-01 to 2023-02-26 | 2023-04-01 onward |

Filings between 2023-02-27 and 2023-03-31 are excluded.

- **Consistent measure in both periods:** plan = `plan_text`; discretionary =
  not `plan_text` and no tax-withholding mention.
- **S8r** (sells) = (discretionary − plan)_after − (discretionary − plan)_before,
  on the primary outcome. **Predicted sign: negative.** If the reform made plan
  sells less informative, returns after plan sells rise relative to
  discretionary sells.
- **S7r** (buys): the same contrast, two-sided, with no predicted sign.
- **Inference:** each period's spread is estimated with the month-clustered
  bootstrap; the difference is tested with a normal approximation
  (SE = √(SE_before² + SE_after²)).
- **Development:** "after" is 2023-04-01 to 2024-12-31.
- **Holdout A:** "after" is 2025-01-01 to 2026-11-30, compared with the same
  development "before" estimate. One-sided for S8r.
- **Status:** these are not part of the S1–S10 FDR family. An effect is called
  supported only if it is significant in the predicted direction in development
  and in Holdout A.
- **Power is limited:** about 21 post-reform months in development and 23 in Holdout A.
- **Robustness (reported, not decisive):** "after" plan = `plan_text` or `plan_box`.
- **Validation (descriptive):** for April 2023 onward, a cross-tabulation of
  `plan_text` against `plan_box` for buys and sells. It shows how much of the
  checkbox population the footnote measure finds, which bounds how noisy the
  "before" plan group is.

*(c) S10b, secondary: activist buys matched to the buyer.*
- **Data:** for each insider CIK that appears as a 10% holder on a qualifying
  buy, download that CIK's own SEC submissions (filer side) and keep its
  Schedule 13D and 13D/A accession numbers.
- **Definition:** a buy is an **activist buy** if the buyer filed, alone or as
  a group member, a Schedule 13D or 13D/A on the same company (the same
  accession number appears in the buyer's and the company's submissions),
  accepted before the Form 4 filing date and within the 365 days before it.
- **Contrast:** activist buys minus other 10%-holder buys, on the primary
  outcome. Predicted sign +.
- **Status:** reported alongside S10, not in the FDR family; same support rule as S8r.
- **Limitation:** a fund family that files the 13D through a different legal
  entity from the one on the Form 4 is not matched.

*(d) S9, explicit treatment of code F and other non-sale codes.*
- **"Hold"** = the filing has an option exercise (code M) and no open-market
  sale (code S, non-derivative) by that reporting person.
- **Shares withheld** to pay the exercise price or taxes (code F), and any other
  disposition that is not code S (for example code D, a disposition to the
  issuer), do **not** count as a sale. An exercise with F but no S is "hold".
- **"Sell"** = an exercise with at least one code S row on the same filing.
- **Limitation:** a sale reported on a separate Form 4 is not linked to the exercise.

**Amendment 4: holdout timing and execution rules (committed before any Study 3 data was extracted; the commit time is the date).**

*(a) When each Study 3 holdout is opened.* As first written, Holdout A had no
opening date and Holdout B ("once outcomes have matured") had no end date.
That would allow running a holdout before its outcomes exist, or looking at
Holdout B repeatedly as data accumulates. Both are fixed here.

| Stage | Filings | Opened | Why that date |
|---|---|---|---|
| Holdout A | 2025-01-01 to 2026-11-30 (unchanged) | once, on or after **2027-03-08** | the last filing's 60-day outcome matures at the 2027-03-01 close; one week is allowed for price-data lag |
| Holdout B | **2026-12-01 to 2027-05-31** (was: open-ended) | once, on or after **2027-09-07** | the last filing's 60-day outcome matures at the 2027-08-26 close |

- Each holdout is opened **once**. Holdout B has no interim looks.
- At opening, any holdout filing still missing its primary outcome is reported
  as a count, by month. It is not silently dropped.
- Filings after 2027-05-31 are not used to confirm anything in Study 3.
- The 20- and 180-day secondary outcomes are reported with whatever has
  matured at opening; they are not used for decisions.
- `analysis/study3.py` will refuse to open a stage before its date.

*(b) E1–E3: pre-registered execution rules (a separate family from S1–S10).*
These test whether simple entry and exit timing improves on the standard
entry. They do not test stock selection or the author's own due diligence;
that is tested separately by a forward decision log.

**Population.** All qualifying buys (as in `build_dataset.py`), and
descriptively within the top group of any S hypothesis supported in development.

**Baseline (B0).** Buy at the standard entry: the close of the first trading
day after the filing date (call it day t0, price P0). Sell at the close of
t0 + 60 trading days.

**Price data.** These rules need daily highs and lows, which are not stored
yet. `fetch_prices.py` will add `high_adj` and `low_adj` (High and Low
× Adj Close / Close, the same basis as `open_adj`). Every stage is re-fetched
together, before any E rule is computed. A day with no high or low cannot
trigger an intraday condition.

**Rules.** The parameters are fixed here. Other values may be run only as
labelled exploratory analysis.

| ID | Rule |
|---|---|
| E1 | **Limit entry.** After the t0 close, place a buy limit at L = 0.98 × P0, good for days t0+1 to t0+3. It fills on the first of those days whose low is **below** L, at min(that day's open, L). If it doesn't fill, there is no trade. Exit at the t0+60 close, as in B0. |
| E2 | **Trailing stop.** Enter as B0. If any close from t0+1 to t0+59 is ≤ 0.85 × the highest close since entry (the entry close included), exit at the next day's open. Otherwise exit at the t0+60 close. |
| E3 | **Bracket.** Enter as B0, with a target of 1.20 × P0 and a stop of 0.85 × P0, checked on days t0+1 to t0+60. If a day opens at or beyond either level, exit at the open. Otherwise, if the low reaches the stop, exit at the stop; if the high reaches the target, exit at the target. **If both are reached the same day, the stop is assumed to come first.** If neither is reached, exit at the t0+60 close. |

**Outcome (per signal).** V = the stock's return while in the position, minus
IWM's return over the same period, minus costs. The window is t0 close to
t0+60 close for every rule. Money that is not in the stock is assumed to be in
IWM, so it earns zero excess. That makes an unfilled E1 signal V = 0 with no
cost: missing a winner counts against E1. For fills at an intraday price,
IWM's leg starts or ends at that day's open. IWM excess is used rather than
the factor BHAR because these rules change the holding window, and that is the
return an investor actually gets.

**Costs.** Each executed round trip is charged the round-trip cost for its
daily-volume bucket in `config.yaml`, the same as B0, including E1's limit
fills. This is deliberately conservative. A sensitivity run charges E1 fills
half the cost (no spread crossed on entry); it is reported, not decisive.

**Test.**
- D = V(rule) − V(B0) for the same signal, winsorized at development 1%/99% cutoffs.
- Mean D, 95% CI and p from the month-clustered bootstrap (`n_boot`).
- **Predicted sign: + for E1, E2 and E3** (the author's belief that timing adds value).
- **Supported in development** (2010–2024): Holm-adjusted p < 0.05 across
  E1–E3, positive mean D, and the same sign in each development sub-period.
- **Confirmation:** Holdout B only, under the rules in (a). One-sided, Holm
  across the rules supported in development, α = 0.05. Holdout A is not used
  for E1–E3, so its single opening stays limited to S1–S10 and the secondary
  tests already registered.

**Also reported (descriptive, not tested):**
- E1's fill rate, and B0's V for filled versus unfilled E1 signals. This shows
  whether the limit fills mainly on the losers (adverse selection).
- E1c: like E1, but an unfilled order buys at the t0+3 close.
- E2 and E3: how often each exit fires, and the mean days held.
- Every rule by volume bucket.

**Known limitations.**
- Daily bars do not show the order of prices within a day. E3's "stop first"
  rule and E1's requirement that the low go below L (not just touch it) lean
  against the rules.
- Limit-order queue position and partial fills are not modelled.
- The cost figures are assumptions, as elsewhere.

*(c) Still to record before extraction (Amendment 5).* The output of
`phase0/check_10b5.sql` that Amendment 3(a) says will be recorded "in the next
amendment" goes into Amendment 5 instead. So does the outside registration
below. Study 3 extraction does not start until Amendment 5 is committed and pushed.

**Amendment 5: pre-extraction record (to be completed and committed before any Study 3 data is extracted).**

*(a) 10b5-1 query output* (`phase0/check_10b5.sql`, run [DATE, TIME UTC]):

[paste both result tables here, unedited]

*(b) Outside timestamp.* This document as of commit [HASH] (the Amendment 4
commit) was registered at [OSF REGISTRATION URL] on [DATE]. That
registration, not git, is the independent timestamp for Study 3. Studies 1
and 2 rely on the GitHub commit history only.
