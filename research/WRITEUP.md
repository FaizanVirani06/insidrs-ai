# Can you pick the good insider buys? A point-in-time study of 75,860 Form 4 purchases (2010–2026)

*InsidrsAI research write-up, November 2026. Code and every number below: `research/` in this repository.*

## Summary

- **The typical insider purchase did not beat the market.** Mean 60-day excess return versus the Russell 2000 was −0.1% (95% CI −1.0% to +1.0%); the median was −1.7%, and 45.6% of buys beat the benchmark.
- **The product's AI ratings did not work when tested honestly.** On ratings made at filing time, buys rated 8+ trailed the S&P 500 by 14.1% over 60 days, and the rank correlation between rating and return was −0.10. Ratings made after the fact looked predictive, because the model had been shown statistics that contained the outcome.
- **Officer and director track records do not persist.** A past win rate above 60% predicted nothing about the next trade, at any minimum record length.
- **10% holders (mostly funds) are the exception, at short horizons only.** Those with good records beat those with poor records by about 8–9 points over 60 days. This survives every concentration check tried, and is gone by 180 days.
- **Public price-trend features rank buys modestly out of sample** (AUC 0.54; top-minus-bottom fifth about 6 points), but assumed trading costs remove most of the edge.
- **Insider sells carry no detectable signal.**

## 1. Questions

1. Did the AI ratings predict forward excess returns on insider buys?
2. Do insider track records persist? This is the core product idea: "see which insiders are worth following".
3. What do buys that beat the market have in common?
4. Do sells carry any signal?

## 2. Data

| Item | Value |
|---|---|
| Form 4 filings parsed | 801K (2010–2026), from SEC EDGAR |
| Open-market purchases (transaction code P) | 118,447 events by 27,813 insiders (all identified by SEC CIK) |
| Qualifying buys after filters | 75,860 (74,729 with a 60-day return, 70,344 with 180-day) |
| Qualifying sells (code S) | 172,488 |
| Prices | Yahoo Finance daily adjusted close, close and volume; 5,156 of 5,776 tickers found |
| Benchmarks | SPY (S&P 500) and IWM (Russell 2000) |
| Market cap | SEC-reported shares outstanding × reported trade price; available for 73% of buys |
| AI ratings | 15,927 rated buys (Gemini 2.5, three prompt versions), Jan 2024 – Sep 2026 filings |

**Filters.** Exclusions, in order of size:

| Reason | Buys excluded |
|---|---|
| Under $5,000, or no reported price | 17,773 |
| No price data at entry | 12,369 |
| Trade price under $1 | 6,890 |
| Amendments (Form 4/A) | 3,413 |
| Holding window contains a likely bad price tick | 873 |
| Filed more than a year after the trade | 632 |
| Implausible dollar amount or price (parse errors) | 328 |
| Duplicate reports | 296 |

## 3. Method

**Returns**
- **Entry** is the close on the first trading day after the filing date. Most Form 4s are accepted after the close, so the filing-day close was often not tradeable.
- **Exit** is 60 or 180 trading days later.
- **Excess return** is the stock's return minus the benchmark's return over the same calendar dates.
- **Reporting.** Means are winsorized at the 1st and 99th percentiles and always shown next to the median and the hit rate (share of buys that beat the benchmark).

**Point-in-time features.** Every feature uses only what was public on the filing date.
- **Track record** counts only the insider's earlier trades whose holding period had already ended.
- **Cluster buying** counts officers and directors at the same company who had already filed a buy in the prior 14 days. It excludes people named on the same form, because fund families report one purchase through several legal entities.
- **Market cap** uses the latest 10-Q or 10-K share count filed before the Form 4.

**Inference**
- **Overlapping windows.** Trades filed in the same weeks share the same market, and 180-day windows overlap heavily. Confidence intervals therefore come from a bootstrap that resamples whole filing months (1,000 draws).
- **Rank correlations** are also computed month by month, and the t-statistic is taken across months.
- **Multiple testing.** p-values are adjusted for false discovery (Benjamini–Hochberg) within each results table.
- **Time splits, never shuffled.**
  - Track-record shrinkage is tuned on 2010–2017 and tested on 2018 onward.
  - Prediction models are fitted on filings through 2021 and scored on 2022 onward.

**AI ratings** were split by when they were made, using the server clock:
- **Live** (within 7 days of filing; 4,035 qualifying buys with a 60-day return) is the honest test.
- **Backfilled** (90 or more days later; 6,190) is shown only for contrast.

## 4. Results

### Q1. AI ratings

**Live ratings** (filed Feb–Aug 2026, 60-day excess return versus the S&P 500):

| Rating | Buys | Mean excess | Hit rate |
|---|---|---|---|
| All buys, same months | 4,776 | −4.7% | 38.2% |
| Below 6 | 209 | −2.0% | 41.6% |
| 6–6.9 | 2,263 | −3.5% | 39.8% |
| 7–7.9 | 1,465 | −8.1% | 35.0% |
| 8 and above | 98 | −14.1% | 30.6% |

- **Higher-rated buys did worse.** The top third by rating trailed the bottom third by 4.7 points (95% CI −7.2 to −1.1).
- **The rank correlation is −0.10**, negative in 6 of 7 months; −0.09 against the Russell 2000.
- **It is not a company-size effect.** Within size groups the correlation is −0.16 for small caps (t = −2.4), −0.06 for mid, −0.04 for micro and +0.03 for large (only 276 buys).
- **The rating has two parts, and they point different ways.** It is a deterministic formula score plus a Gemini adjustment limited to −2.5 to +1.6. The formula carries the negative relation (correlation −0.08). The Gemini adjustment is mildly positive (+0.04, t = 1.7) but not significant.

**Backfilled ratings** (2024–2025 filings) look good: 8+ rated buys returned +3.5% at 60 days and +14.3% at 180. That result is contaminated.
- 6,131 of the 6,190 were shown the insider's stored win rate, which production computes over all of the insider's trades, including the one being rated.
- All of the positive relation comes from the Gemini adjustment (correlation +0.09 at 60 days, +0.13 at 180).
- The adjustment works better on filings after the model's knowledge cutoff (+0.17) than before it (+0.06). Memorized outcomes would show the reverse, so the leaked input is the likely cause.

### Q2. Track-record persistence

Test period 2018 onward. Spread = next-trade excess return of insiders with a past win rate above 60%, minus those below 40%.

| Group | Min prior trades | 60-day spread (95% CI) | 180-day spread (95% CI) |
|---|---|---|---|
| Officers & directors | 1 | +0.1% (−1.9, +1.8) | −2.5% (−6.1, +1.2) |
| Officers & directors | 5 | −2.5% (−6.2, +0.8) | −6.6% (−12.8, +0.8) |
| Officers & directors | 10 | −2.6% (−6.4, +1.2) | −7.4% (−14.8, +0.9) |
| 10% holders | 3 | +8.8% (+2.8, +14.2) | +8.7% (−2.9, +19.4) |
| 10% holders | 10 | +6.4% (+0.2, +11.6) | +0.2% (−12.5, +11.7) |

**Officers and directors: no persistence.** The rank correlation between past win rate and next-trade return is about 0.02, and longer records do not help.

**10% holders: the 60-day effect is robust to concentration.** With a minimum of 3 prior trades, the spread is:

| Check | Spread (95% CI) |
|---|---|
| Baseline | +8.8% (+2.8, +14.2) |
| Resampling whole funds instead of months | +8.8% (+4.8, +12.7) |
| Without the 10 most active funds | +9.1% (+2.6, +15.6) |
| Without the 50 most active funds | +7.8% (−0.6, +15.6) |
| One observation per fund, company and month | +8.5% (+4.4, +12.5) |

The rank correlation is 0.08 at 60 days and about 0 at 180 days. An effect that appears at 60 days and disappears by 180 is consistent with skill. It is also consistent with the fund's own continued buying supporting a thinly traded stock; this study cannot tell the two apart.

**Shrinkage.** A beta-binomial prior fitted on 2010–2017 gives an average win rate of 46.7% and a prior strength of about 6 trades. The out-of-sample results imply that for officers and directors the right amount of shrinkage is close to total.

### Q3. What winners have in common

**Base rates.** Versus the Russell 2000:

| Horizon | Mean excess | Median | Beat benchmark |
|---|---|---|---|
| 60 days | −0.1% | −1.7% | 45.6% |
| 180 days | −1.1% | −4.4% | 43.3% |

A minority of large winners lifts the mean above the typical outcome. Results swing by period: the 180-day mean ranges from +3.0% (2018–19) to −6.3% (2022–23).

**Single features** (180 days, top bucket minus bottom bucket, FDR-adjusted across 28 tests):

| Feature | Spread (95% CI) | FDR p |
|---|---|---|
| Stock above its 200-day average | +5.2% (+2.7, +7.8) | 0.002 |
| Stock above its 50-day average | +4.6% (+2.3, +7.2) | 0.003 |
| Far above 52-week low | +5.1% (+1.3, +9.2) | 0.09 |
| Cluster buying (3+ other insiders vs none) | +2.3% (−1.9, +6.5) | 0.46 |
| Purchase as % of prior holdings | +2.1% (−1.1, +5.0) | 0.39 |
| Purchase size (dollars) | −2.7% (−6.8, +1.0) | 0.39 |
| Market cap at filing | −2.8% (−6.2, +0.9) | 0.29 |

The features that matter are ordinary price momentum, not insider-specific information. Insider role, purchase size, cluster buying and company size show no significant relation.

**Models** (fitted through 2021, scored on 2022–2026):

| Model | Horizon | AUC | Hit rate, top 20% (base) | Top minus bottom 20% (95% CI) |
|---|---|---|---|---|
| Logistic regression | 60d | 0.520 | 48.2% (43.6%) | +1.4% (−1.1, +4.0) |
| Gradient-boosted trees | 60d | 0.539 | 50.5% (43.6%) | +5.8% (+3.0, +9.0) |
| Logistic regression | 180d | 0.529 | 44.6% (41.7%) | +4.5% (−1.4, +9.8) |
| Gradient-boosted trees | 180d | 0.537 | 46.5% (41.7%) | +7.0% (+1.2, +13.1) |

- **The ranking signal is real but small,** and mostly comes from avoiding the worst buys: the tree model's top 20% averaged only +1.7% (60 days) and +1.1% (180 days) over the benchmark.
- **The most important inputs** are the S&P 500's prior six-month return, the stock's prior 60-day return and its distance from its 52-week high.
- **The strongest regression coefficient** is a company with under a year of price history, which lowers the odds of beating the benchmark by about 30%.

**Trading costs.** The cost per round trip is an assumption, set by liquidity: 5% for stocks trading under $100K a day, 2% for $100K–$1M, 1% for $1M–$10M, and 0.3% above $10M. The median bought stock traded $1.4M a day, and 16% traded under $100K.

| Subset | Horizon | Gross mean | Net mean (95% CI) |
|---|---|---|---|
| All qualifying buys | 60d | −0.1% | −1.9% (−2.8, −0.9) |
| All qualifying buys | 180d | −0.8% | −2.6% (−3.9, −1.2) |
| Above 200-day average | 60d | +1.3% | −0.7% (−1.7, +0.3) |
| Above 200-day average | 180d | +3.2% | +1.2% (−0.7, +3.2) |

### Q4. Sells

Across 167,834 qualifying sells, stocks returned +0.4% (60 days) and +0.3% (180 days) versus the Russell 2000 after the filing: no underperformance.
- No subgroup is significantly negative: large sales, sales of more than a quarter of holdings, sales with other insiders also selling, or any role.
- The live AI sell rating has no relation to later returns (correlation +0.005, n = 17,629).
- Pre-planned (10b5-1) and tax-related sales are not separated out.

## 5. Errors found and corrected during the study

Each of these would have produced a publishable-looking false result.

1. **Look-ahead in market cap.** The first version rescaled today's market cap by the price change since the filing. That quantity contains the stock's future return. It produced "large caps lose 14% over 180 days" and made market cap the strongest feature. With point-in-time share counts, both effects disappear.
2. **Joint filers counted as a cluster.** Fund families report one purchase through several entities, so a third of buys appeared to have three or more co-buyers. After excluding same-form co-filers and funds, the regression coefficient on cluster buying fell from 1.17 to 1.08 and lost significance.
3. **Leaked inputs to the AI ratings,** described in Q1.
4. **Bad price data.** Production prices had 13,540 one-day moves beyond +150% or −60%, and a maximum 60-day return of 89,000×. The mean excess return computed on them was +1,644%.

## 6. Limitations

- **Survivorship.**
  - The company universe is a list of currently listed tickers.
  - 620 tickers had no Yahoo data; production returns suggest the dropped buys did slightly worse (median −1.5% versus −1.2%).
  - Companies that delisted before the universe was built are absent entirely.
  - All results are probably biased upward.
- **Incomplete, non-random history.** About half of the 1.5 million discovered filings had been parsed, company by company, oldest first.
- **Live AI sample.** Seven months, one market regime, 60 days only; no live 180-day result exists yet.
- **Data quality.**
  - Momentum features come from the production price table, which has known bad ticks.
  - Market cap is missing for 27% of buys.
  - Yahoo data is unofficial and not licensed for commercial use.
- **Assumed costs.** Trading costs are not measured; the estimated net edge depends on them.
- **Multiple testing.** Several hundred comparisons were made, and FDR is controlled within each table, not across the whole study.

## 7. Conclusion

Insider purchases in this sample were, on average, no better than buying a small-cap index, and most individual purchases lost to it. Neither of the product's two main ideas held up:
- the AI rating, which pointed the wrong way when made in real time;
- following insiders with good records, which works only for 10% holders, only at 60 days, and only before costs.

A simple trend filter improves the odds modestly, but it reflects price momentum rather than insider information, and costs absorb most of it. The most useful output of the project is the infrastructure: a point-in-time dataset and test harness that caught four errors, each of which would have produced a convincing false result.

## 8. Follow-up: two pre-registered studies

Both studies were planned in writing and committed before any results
(`PREREGISTRATION.md`). The development sample was filings from 2010–2024, and
2025 onward was held out.

**Study 1: where does the return arrive, and does how an insider trades matter?**
- **Window returns** (56,244 buys). Factor-adjusted (Fama-French five factors
  plus momentum), buy-and-hold:

  | Window | Return (95% CI) |
  |---|---|
  | Trade to the day before filing (only the insider can earn this) | +0.29% (+0.23, +0.35) |
  | Two-day disclosure window | **+1.58% (+1.33, +1.79)** |
  | After an outsider can buy, 60 days | +1.69% (+0.41, +3.47), median +0.49% |

  Against the Russell 2000, the post-entry return is near zero.
- **Five hypotheses failed:** opportunistic versus routine insiders, buying
  after a dip, a dip after a periodic report, opportunistic buying after a dip,
  and an officer or director's first buy in two years.
- **One came out reversed:** routine buyers beat opportunistic ones by 4.8
  points. It flips sign in one sub-period, and exploration suggests it is
  driven by a few large 10% holders. It is left as a candidate for future testing.

**Study 2: can a real-time reader capture the disclosure reaction?**
Using each Form 4's exact EDGAR acceptance time and daily open and close prices:
- **About 1.0% is gone before the first price an outsider can trade at.** For
  most filings, accepted after the close, that is the overnight jump to the next open.
- **Buying at that first price instead of the next-day close captures a further +0.33%.**
  - Development: 95% CI +0.26 to +0.41, and stable across sub-periods.
  - Confirmed in the 2025+ holdout: +0.28% (CI +0.06 to +0.50), one-sided p = 0.007.
- **The captured amount is smaller than the assumed round-trip cost of these
  stocks.** Holding for 60 days from that first price returned −1.33% after costs.

**Conclusion of the follow-up.** Insider purchases contain real information,
worth about 1.5% over two days. Roughly two-thirds is priced before an outside
investor can act on daily data, and the part that can be captured is smaller
than the cost of trading these mostly small stocks. The information is real; the
edge for an outside investor is not.

## 9. Implications for the product

**Per-insider track records should not be the headline feature.** For officers and directors, a good record did not predict the next trade at any record length, so presenting it as a reason to follow someone would mislead users. 10% holders are the one group where records carried short-term information. A "fund watch" view framed around 60 days, with a liquidity warning, could be tested, but only after the scheduled job confirms the effect on filings made after this study.

**Minimum sample size.** No record length made officer and director records predictive, so any record is history, not a forecast. If win rates are shown:
- require at least 10 resolved trades;
- show the count and a shrunk rate next to the raw rate;
- always show the base rate of about 45%.

Even with no skill at all, an insider who beats the market 45% of the time on average will show a wide range of win rates from luck alone (approximate 95% ranges):

| Resolved trades | Win rate a no-skill insider can show |
|---|---|
| 5 | 1% to 89% |
| 10 | 14% to 76% |
| 20 | 23% to 67% |
| 50 | 31% to 59% |

**The AI rating.**
- Retire the 1–10 score or rebuild it and validate it on live data before showing it.
- Never present backfilled ratings as evidence of performance.
- Stop feeding stored outcome statistics into the prompt.

**Presenting results honestly to non-technical users.**
- **Use plain counts:** "beat the market 45 times out of 100", not an average return.
- **Use medians, not means.**
- **Show results after estimated trading costs**, and flag stocks that trade under $100K a day.
- **Avoid hindsight rankings.** A "best performing insiders" list built from past outcomes selects for luck.
- **State what the data cannot show:** delisted companies are missing, and past results are not a forecast.

**Speed is the only place value exists.** The follow-up studies show the
information is priced within about a day. A real-time alert is the most useful
thing the product can offer, but even an instant reader captured only about
0.3% on average, which is less than typical trading costs for these stocks.
That should shape the framing: "know what insiders are doing, as soon as it is
public", not "trade on it for profit".

**Production fixes this study implies** (the study corrects for them; the live product does not):
- stored insider statistics include the trade being rated and later ones;
- returns enter at the filing-day close;
- the cluster flag uses later filings and counts joint filers;
- market cap is a current snapshot.
