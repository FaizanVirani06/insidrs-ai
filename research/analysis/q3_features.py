"""Question 3: what do the buys that beat the market have in common?

    python -m research.analysis.q3_features

Four parts, simplest first:
  A. Base rates by period and company size, against BOTH benchmarks
     (S&P 500 and Russell 2000), to see how much "insider buys lose to SPY"
     is just "small caps lost to large caps".
  B. One feature at a time: returns by bucket, top-minus-bottom spread, FDR.
  C. Logistic regression (did the buy beat the benchmark?), fitted on early
     years, scored on later years.  Coefficients are per one standard deviation.
  D. Gradient-boosted trees with permutation importance, same time split.

Every feature is something known on the filing date.  Market cap is SEC-reported
shares outstanding x the price the insider paid.  One caveat: the momentum
fields come from the production price table (which has known bad ticks).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, information_coefficient, spread, summarize, winsorize
from research.common import load_config

pd.set_option("display.width", 220, "display.max_columns", 30)

NUMERIC = {
    "log_dollars": "purchase size (log $)",
    "pct_holdings_change": "purchase as % of prior holdings",
    "dollars_pct_mcap": "purchase as share of market cap",
    "cluster_n_other": "other insiders who filed buys in prior 14 days",
    "trend_ret_20d": "stock return, prior 20 days",
    "trend_ret_60d": "stock return, prior 60 days",
    "trend_dist_52w_high": "distance below 52-week high",
    "trend_dist_52w_low": "distance above 52-week low",
    "log_mcap": "market cap at filing (log)",
    "spy_ret_126d": "S&P 500 return, prior 6 months",
    "filing_delay_days": "days from trade to filing",
    "prior_n_60": "insider's number of earlier buys",
}
BINARY = {"trend_above_sma_50": "above 50-day average", "trend_above_sma_200": "above 200-day average"}
CATEGORICAL = {"role": "insider role", "mcap_bucket_pit": "company size", "sector": "sector", "period": "period"}
PERIODS = [(2009, 2017, "2010-17"), (2018, 2019, "2018-19"), (2020, 2021, "2020-21"), (2022, 2023, "2022-23"),
           (2024, 2030, "2024-26")]


def load(cfg) -> pd.DataFrame:
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = df[(df["side"] == "buy") & df["qualifies"]].copy()
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    df["period"] = ""
    for lo, hi, name in PERIODS:
        df.loc[df["year"].between(lo, hi), "period"] = name
    df["log_mcap"] = np.log10(df["mcap_pit"].where(df["mcap_pit"] > 0))
    df["pct_holdings_change"] = df["pct_holdings_change"].clip(upper=1000)
    df["mcap_bucket_pit"] = df["mcap_bucket_pit"].fillna("unknown")
    df["sector"] = df["sector"].fillna("unknown")
    for h in cfg["horizons"]:
        df[f"ex_{h}"] = winsorize(df[f"excess_{h}"])
        df[f"exsc_{h}"] = winsorize(df[f"excess_smallcap_{h}"])
    return df


def base_rates(df, horizons, n_boot) -> pd.DataFrame:
    rows = []
    groups = [("all", "all", df)] + [("period", k, g) for k, g in df.groupby("period")] + \
             [("company size", k, g) for k, g in df.groupby("mcap_bucket_pit")] + \
             [("role", k, g) for k, g in df.groupby("role")]
    for h in horizons:
        for kind, name, g in groups:
            for bench, col in [("S&P 500", f"ex_{h}"), ("Russell 2000", f"exsc_{h}")]:
                d = g[g[col].notna()]
                rows.append({"horizon": h, "group": kind, "value": name, "benchmark": bench,
                             **summarize(d, col, n_boot=n_boot)})
    return pd.DataFrame(rows)


def single_feature(df, h, n_boot) -> tuple[pd.DataFrame, pd.DataFrame]:
    ret = f"exsc_{h}" if df[f"exsc_{h}"].notna().any() else f"ex_{h}"
    d = df[df[ret].notna()]
    rows, spreads = [], []
    for col, label in {**NUMERIC, **BINARY}.items():
        x = d[col]
        if x.notna().sum() < 200:
            continue
        if col in BINARY or x.nunique() <= 5:
            bins = x.where(x.notna()).astype("float").clip(upper=2).map({0.0: "0", 1.0: "1", 2.0: "2+"})
            order = [b for b in ["0", "1", "2+"] if (bins == b).any()]
        else:
            q = pd.qcut(x.rank(method="first"), 5, labels=["Q1 low", "Q2", "Q3", "Q4", "Q5 high"])
            bins, order = q.astype("object"), ["Q1 low", "Q2", "Q3", "Q4", "Q5 high"]
        for b in order:
            rows.append({"horizon": h, "feature": label, "bucket": b, **summarize(d[bins == b], ret, n_boot=n_boot)})
        spreads.append({"horizon": h, "feature": label, "comparison": f"{order[-1]} minus {order[0]}",
                        **spread(d, ret, bins == order[-1], bins == order[0], n_boot=n_boot)})
    for col, label in CATEGORICAL.items():
        if col == "period":
            continue
        for b, g in d.groupby(col):
            rows.append({"horizon": h, "feature": label, "bucket": b, **summarize(g, ret, n_boot=n_boot)})
    return pd.DataFrame(rows), pd.DataFrame(spreads)


def design(df, features, train_mask):
    """Numeric matrix for the models: standardise on TRAIN statistics only, flag missing values."""
    X = pd.DataFrame(index=df.index)
    for col in features:
        x = df[col].astype(float)
        lo, hi = x[train_mask].quantile([0.01, 0.99])
        x = x.clip(lo, hi)
        mu, sd = x[train_mask].mean(), x[train_mask].std()
        if x.isna().mean() > 0.01:
            X[f"{col}__missing"] = x.isna().astype(float)
        X[col] = ((x - mu) / (sd if sd > 0 else 1.0)).fillna(0.0)
    for col in ("role", "mcap_bucket_pit"):
        dummies = pd.get_dummies(df[col], prefix=col, dtype=float)
        top = df.loc[train_mask, col].value_counts().index[0]           # most common level = reference
        X = X.join(dummies.drop(columns=f"{col}_{top}"))
    return X


def independent_columns(X: pd.DataFrame, train) -> pd.DataFrame:
    """Drop columns that are constant or an exact combination of earlier ones.

    Example: every momentum field is missing for the same rows, so their
    "missing" flags are identical; a regression cannot separate identical columns.
    """
    keep, basis = [], np.ones((int(train.sum()), 1))
    for col in X.columns:
        trial = np.column_stack([basis, X.loc[train, col].to_numpy()])
        if np.linalg.matrix_rank(trial) > basis.shape[1]:
            keep.append(col)
            basis = trial
    dropped = [c for c in X.columns if c not in keep]
    if dropped:
        print(f"[q3] dropped redundant columns: {', '.join(dropped)}")
    return X[keep]


def models(df, h, cfg) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    import statsmodels.api as sm
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    ret = f"exsc_{h}" if df[f"exsc_{h}"].notna().any() else f"ex_{h}"
    d = df[df[ret].notna()].copy()
    y = (d[ret] > 0).astype(int)
    train = (d["filing_date"] <= pd.Timestamp(cfg["analysis"]["model_train_end"])).to_numpy()
    feats = list(NUMERIC) + list(BINARY)
    X = independent_columns(design(d, feats, train), train)

    # ---- logistic regression, standard errors clustered by month -------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = sm.Logit(y[train], sm.add_constant(X[train])).fit(
            disp=0, cov_type="cluster", cov_kwds={"groups": pd.factorize(d.loc[train, "month"])[0]})
    coef = pd.DataFrame({"horizon": h, "feature": fit.params.index, "coef_per_sd": fit.params.values,
                         "odds_ratio": np.exp(fit.params.values), "p": fit.pvalues.values})
    coef = coef[coef["feature"] != "const"]
    coef["p_fdr"] = bh_adjust(coef["p"])
    p_logit = fit.predict(sm.add_constant(X[~train], has_constant="add"))

    # ---- gradient-boosted trees (handles non-linear effects and interactions) -
    gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=200,
                                        random_state=0).fit(X[train], y[train])
    p_gb = gb.predict_proba(X[~train])[:, 1]
    imp = permutation_importance(gb, X[~train], y[~train], scoring="roc_auc", n_repeats=5, random_state=0)
    importance = (pd.DataFrame({"horizon": h, "feature": X.columns, "auc_drop_when_shuffled": imp.importances_mean,
                                "sd": imp.importances_std}).sort_values("auc_drop_when_shuffled", ascending=False))

    # ---- out-of-sample scorecard ---------------------------------------------
    test = d[~train]
    score = []
    for name, p in [("logistic regression", np.asarray(p_logit)), ("gradient-boosted trees", p_gb)]:
        top = pd.Series(p >= np.quantile(p, 0.8), index=test.index)
        bottom = pd.Series(p <= np.quantile(p, 0.2), index=test.index)
        s = spread(test, ret, top, bottom, n_boot=cfg["analysis"]["n_boot"])
        score.append({"horizon": h, "model": name, "train_n": int(train.sum()), "test_n": int((~train).sum()),
                      "test_auc": roc_auc_score(y[~train], p), "base_hit_rate": float(y[~train].mean()),
                      "top20%_hit_rate": float(y[~train][top.to_numpy()].mean()),
                      "top20%_mean_excess": float(test.loc[top, ret].mean()),
                      "top_minus_bottom_20%": s.get("spread"), "lo": s.get("lo"), "hi": s.get("hi"), "p": s.get("p")})
    return coef, importance, pd.DataFrame(score)


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    n_boot, horizons = cfg["analysis"]["n_boot"], cfg["horizons"]
    df = load(cfg)

    base = base_rates(df, horizons, n_boot)
    base.to_csv(out / "q3_base_rates.csv", index=False)
    show = ["horizon", "group", "value", "benchmark", "n", "months", "mean", "mean_lo", "mean_hi", "median", "hit_rate"]
    print("\n== A. Base rates: qualifying insider buys vs each benchmark ==")
    print(base[[c for c in show if c in base]].round(4).to_string(index=False))

    parts = [single_feature(df, h, n_boot) for h in horizons]
    buckets = pd.concat([p[0] for p in parts], ignore_index=True)
    spreads = pd.concat([p[1] for p in parts], ignore_index=True)
    spreads["p_fdr"] = bh_adjust(spreads["p"]) if "p" in spreads else np.nan
    buckets.to_csv(out / "q3_feature_buckets.csv", index=False)
    spreads.to_csv(out / "q3_feature_spreads.csv", index=False)
    show = ["horizon", "feature", "bucket", "n", "mean", "mean_lo", "mean_hi", "median", "hit_rate"]
    print("\n== B. One feature at a time (excess vs small-cap benchmark where available) ==")
    print(buckets[[c for c in show if c in buckets]].round(4).to_string(index=False))
    print("\n== B. Top bucket minus bottom bucket, FDR-adjusted across features ==")
    print(spreads.round(4).to_string(index=False))

    coefs, imps, scores = zip(*[models(df, h, cfg) for h in horizons])
    coef, imp, score = pd.concat(coefs), pd.concat(imps), pd.concat(scores)
    coef.to_csv(out / "q3_logit.csv", index=False)
    imp.to_csv(out / "q3_tree_importance.csv", index=False)
    score.to_csv(out / "q3_model_scores.csv", index=False)
    print(f"\n== C. Logistic regression: P(beat benchmark), trained on filings <= {cfg['analysis']['model_train_end']} ==")
    print(coef.round(4).to_string(index=False))
    print("\n== D. Tree model: what the test-set AUC loses when each feature is shuffled ==")
    print(imp.groupby("horizon").head(10).round(4).to_string(index=False))
    print("\n== Out-of-sample scorecard (later years only; AUC 0.50 = coin flip) ==")
    print(score.round(4).to_string(index=False))
    # ---- E. Follow-up to Q1: is the live rating's negative relation just a size effect? ----
    live = df[df["rating_class"] == "live"]
    rows = []
    h = horizons[0]
    for bench, col in [("S&P 500", f"ex_{h}"), ("Russell 2000", f"exsc_{h}")]:
        for name, g in [("all sizes", live)] + list(live.groupby("mcap_bucket_pit")):
            rows.append({"benchmark": bench, "company size": name,
                         **information_coefficient(g[g[col].notna()], "rating", col)})
    e = pd.DataFrame(rows)
    e.to_csv(out / "q3_live_rating_by_size.csv", index=False)
    print(f"\n== E. Live AI rating vs {h}-day excess return, within company-size groups ==")
    print(e.round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
