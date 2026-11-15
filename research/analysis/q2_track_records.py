"""Question 2: do insider track records persist?

    python -m research.analysis.q2_track_records

The product idea is "follow insiders with good records".  That only works if
an insider's PAST win rate says something about their NEXT trade.

For every qualifying buy, build_dataset.py already stored the insider's record
on earlier buys whose holding period had finished before this filing
(prior_n / prior_wins / prior_sum_ex).  Nothing here looks ahead.

Small samples: an insider who is 2-for-2 has a 100% win rate and almost no
evidence behind it.  We shrink every win rate toward the average:
    shrunk = (wins + k * p0) / (n + k)
p0 (the average win rate) and k (how many "average" trades to add) are
estimated from the early years only and then held fixed for the test years.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, information_coefficient, spread, summarize, winsorize
from research.common import load_config

pd.set_option("display.width", 220, "display.max_columns", 30)
N_BINS = [(0, 0, "no record"), (1, 2, "1-2 prior"), (3, 4, "3-4 prior"), (5, 9, "5-9 prior"), (10, 10**9, "10+ prior")]


def fit_prior(train: pd.DataFrame, h: int) -> tuple[float, float]:
    """Estimate p0 and k from the training years (beta-binomial, method of moments).

    Uses each insider's FINAL training-period record. k is large when insiders'
    true win rates are all similar (records are mostly luck) and small when
    they genuinely differ.
    """
    g = train[train[f"ex_{h}"].notna()].groupby("insider_id")[f"ex_{h}"].agg(n="size", wins=lambda s: (s > 0).sum())
    g = g[g["n"] >= 3]
    p0 = g["wins"].sum() / g["n"].sum()
    rate = g["wins"] / g["n"]
    # observed variance of win rates = true variance + binomial noise; solve for the true part
    noise = (p0 * (1 - p0) / g["n"]).mean()
    true_var = max(rate.var(ddof=1) - noise, 1e-6)
    k = max(p0 * (1 - p0) / true_var - 1, 1.0)
    return float(p0), float(k)


def load(cfg) -> pd.DataFrame:
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = df[(df["side"] == "buy") & df["qualifies"]].copy()
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    # Funds (10% holders with no officer/director role) trade for different reasons: keep them apart.
    df["who"] = np.where(df["role"] == "ten_pct_owner", "funds / 10% holders", "officers & directors")
    df = df.sort_values(["filing_date", "accession_number"])
    # First time this insider buys this company: any record must come from OTHER companies,
    # so it cannot simply be "this stock kept going up".
    df["first_buy_in_company"] = df.groupby(["insider_id", "issuer_cik"]).cumcount() == 0
    for h in cfg["horizons"]:
        df[f"ex_{h}"] = winsorize(df[f"excess_{h}"])
    return df


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    n_boot = cfg["analysis"]["n_boot"]
    split = pd.Timestamp(cfg["analysis"]["train_end"])
    df = load(cfg)
    train, test = df[df["filing_date"] <= split], df[df["filing_date"] > split]
    print(f"\nQualifying buys: {len(df):,}   train (<= {split.date()}): {len(train):,}   test: {len(test):,}")

    all_buckets, all_spreads, all_ic, priors = [], [], [], []
    for h in cfg["horizons"]:
        ret = f"ex_{h}"
        p0, k = fit_prior(train, h)
        priors.append({"horizon": h, "avg_win_rate_p0": p0, "shrinkage_k": k})
        d = test[test[ret].notna()].copy()
        n, w = d[f"prior_n_{h}"], d[f"prior_wins_{h}"]
        d["raw_wr"] = (w / n).where(n > 0)
        d["shrunk_wr"] = (w + k * p0) / (n + k)
        d["prior_mean_ex"] = (d[f"prior_sum_ex_{h}"] / n).where(n > 0)

        for who, g in [("all", d)] + list(d.groupby("who")):
            # (a) Does simply HAVING a record matter, and how big must it be?
            for lo, hi, label in N_BINS:
                b = g[n[g.index].between(lo, hi)]
                all_buckets.append({"horizon": h, "who": who, "record": label, "past win rate": "any",
                                    **summarize(b, ret, n_boot=n_boot)})
                if lo == 0:
                    continue
                for name, mask in [("low  (<40%)", b["raw_wr"] < 0.4), ("mid  (40-60%)", b["raw_wr"].between(0.4, 0.6)),
                                   ("high (>60%)", b["raw_wr"] > 0.6)]:
                    all_buckets.append({"horizon": h, "who": who, "record": label, "past win rate": name,
                                        **summarize(b[mask], ret, n_boot=n_boot)})
            # (b) High-record minus low-record insiders, at different minimum sample sizes.
            for min_n in (1, 3, 5, 10):
                e = g[n[g.index] >= min_n]
                all_spreads.append({"horizon": h, "who": who, "subset": "all buys", "min prior trades": min_n,
                                    **spread(e, ret, e["raw_wr"] > 0.6, e["raw_wr"] < 0.4, n_boot=n_boot)})
                f = e[e["first_buy_in_company"]]
                all_spreads.append({"horizon": h, "who": who, "subset": "first buy in a company", "min prior trades": min_n,
                                    **spread(f, ret, f["raw_wr"] > 0.6, f["raw_wr"] < 0.4, n_boot=n_boot)})
            # (c) Rank correlation between the record and the next trade's return.
            rec = g[n[g.index] >= 1]
            for sig, label in [("raw_wr", "raw win rate"), ("shrunk_wr", "shrunk win rate"),
                               ("prior_mean_ex", "past average excess return")]:
                all_ic.append({"horizon": h, "who": who, "signal": label, **information_coefficient(rec, sig, ret)})

    pri = pd.DataFrame(priors)
    print("\n== Shrinkage parameters (fitted on training years only) ==\n", pri.round(3).to_string(index=False))
    pri.to_csv(out / "q2_prior.csv", index=False)

    buckets = pd.DataFrame(all_buckets)
    buckets["p_fdr"] = bh_adjust(buckets["p_mean_ne_0"]) if "p_mean_ne_0" in buckets else np.nan
    buckets.to_csv(out / "q2_buckets.csv", index=False)
    show = ["horizon", "who", "record", "past win rate", "n", "months", "mean", "mean_lo", "mean_hi", "median",
            "hit_rate", "hit_lo", "hit_hi"]
    print("\n== Next-trade excess return by size and quality of the insider's past record (test years) ==")
    print(buckets[[c for c in show if c in buckets]].round(4).to_string(index=False))

    spreads = pd.DataFrame(all_spreads)
    spreads["p_fdr"] = bh_adjust(spreads["p"]) if "p" in spreads else np.nan
    spreads.to_csv(out / "q2_spreads.csv", index=False)
    print("\n== Insiders with past win rate >60% minus those <40% (next-trade excess return) ==")
    print(spreads.round(4).to_string(index=False))

    ic = pd.DataFrame(all_ic)
    ic.to_csv(out / "q2_ic.csv", index=False)
    print("\n== Rank correlation between past record and next-trade excess return ==")
    print(ic.round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
