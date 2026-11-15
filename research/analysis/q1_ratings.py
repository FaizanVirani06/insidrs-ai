"""Question 1: did the AI ratings predict forward excess returns on insider buys?

    python -m research.analysis.q1_ratings

Reads data/analysis.parquet, writes tables to output/tables/q1_*.csv and a
chart to output/plots/, and prints the main tables.

Three groups are always kept apart:
  live      rated within days of the filing  -> the only honest test
  late      rated weeks later
  backfill  rated after the outcome was known, and shown the insider's stored
            win rate -> treat as contaminated; shown for contrast only
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, information_coefficient, spread, summarize, winsorize
from research.common import load_config

CLASSES = ["live", "late", "backfill"]
FIXED_BINS = [0, 6.0, 7.0, 8.0, 10.01]
FIXED_LABELS = ["<6", "6-6.9", "7-7.9", "8+"]
pd.set_option("display.width", 200, "display.max_columns", 30)


def load(cfg) -> pd.DataFrame:
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = df[(df["side"] == "buy") & df["qualifies"]].copy()
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    for h in cfg["horizons"]:
        df[f"ex_{h}"] = winsorize(df[f"excess_{h}"])       # clip extremes once, on all qualifying buys
    return df


def bucket_table(df, h, n_boot) -> pd.DataFrame:
    """Returns by rating bucket, for each rating class, plus an 'all buys' reference row."""
    rows = []
    ret = f"ex_{h}"
    d = df[df[ret].notna()]
    for cls in CLASSES:
        sub = d[d["rating_class"] == cls]
        if sub.empty:
            continue
        # Reference: every qualifying buy filed in the same months, rated or not.
        ref = d[d["month"].isin(sub["month"].unique())]
        rows.append({"class": cls, "bucket": "ALL BUYS same months", **summarize(ref, ret, n_boot=n_boot)})
        rows.append({"class": cls, "bucket": "all rated", **summarize(sub, ret, n_boot=n_boot)})
        fixed = pd.cut(sub["rating"], FIXED_BINS, labels=FIXED_LABELS, right=False)
        for lab in FIXED_LABELS:
            rows.append({"class": cls, "bucket": f"rating {lab}", **summarize(sub[fixed == lab], ret, n_boot=n_boot)})
        # Ratings are bunched between 6 and 8, so also cut into equal-sized thirds.
        third = pd.qcut(sub["rating"].rank(method="first"), 3, labels=["bottom third", "middle third", "top third"])
        for lab in third.cat.categories:
            rows.append({"class": cls, "bucket": lab, **summarize(sub[third == lab], ret, n_boot=n_boot)})
    out = pd.DataFrame(rows)
    out.insert(0, "horizon", h)
    return out


def ic_table(df, h) -> pd.DataFrame:
    """Rank correlation of the rating (and its two ingredients) with the forward return."""
    rows = []
    ret = f"ex_{h}"
    for cls in CLASSES:
        sub = df[(df["rating_class"] == cls) & df[ret].notna()]
        groups = {"all": sub}
        for pv, g in sub.groupby("prompt_version"):
            groups[f"prompt {pv}"] = g
        if cls == "backfill":
            # Leak check: was the model shown this insider's win rate (which may include this trade)?
            groups["shown insider win rate"] = sub[sub["shown_stats_n_60"].fillna(0) > 0]
            groups["not shown win rate"] = sub[sub["shown_stats_n_60"].fillna(0) == 0]
            groups["filed before model cutoff"] = sub[sub["in_model_training_window"]]
            groups["filed after model cutoff"] = sub[~sub["in_model_training_window"]]
        for gname, g in groups.items():
            for signal, label in [("rating", "final rating"), ("baseline_rating", "formula baseline"),
                                  ("rating_minus_baseline", "Gemini adjustment")]:
                rows.append({"horizon": h, "class": cls, "group": gname, "signal": label,
                             **information_coefficient(g, signal, ret)})
    return pd.DataFrame(rows)


def spread_table(df, h, n_boot) -> pd.DataFrame:
    rows = []
    ret = f"ex_{h}"
    for cls in CLASSES:
        sub = df[(df["rating_class"] == cls) & df[ret].notna()]
        if len(sub) < 30:
            continue
        r = sub["rating"].rank(method="first", pct=True)
        rows.append({"horizon": h, "class": cls, "comparison": "top third minus bottom third",
                     **spread(sub, ret, r > 2 / 3, r <= 1 / 3, n_boot=n_boot)})
        rows.append({"horizon": h, "class": cls, "comparison": "rating >=7 minus <7",
                     **spread(sub, ret, sub["rating"] >= 7, sub["rating"] < 7, n_boot=n_boot)})
        # Within-month version: remove each month's average first.
        dm = sub.assign(**{ret: sub[ret] - sub.groupby("month")[ret].transform("mean")})
        rows.append({"horizon": h, "class": cls, "comparison": "top minus bottom third, within month",
                     **spread(dm, ret, r > 2 / 3, r <= 1 / 3, n_boot=n_boot)})
    return pd.DataFrame(rows)


def coverage_table(cfg) -> pd.DataFrame:
    """Are the buys we had to drop (no Yahoo price) different from the ones we kept?

    Uses production's own 60-day excess return, which exists for both groups.
    If the dropped group did much worse, our results are biased upward.
    """
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    d = df[(df["side"] == "buy") & df["prod_ex_60"].notna()]
    d = d[d["qualifies"] | (d["exclude_reason"] == "no_entry_price")]
    g = d.assign(group=np.where(d["qualifies"], "kept", "dropped: no price")).groupby("group")["prod_ex_60"]
    return pd.DataFrame({"n": g.size(), "median_prod_excess_60d": g.median(),
                         "hit_rate": g.apply(lambda s: (s > 0).mean()),
                         "p25": g.quantile(.25), "p75": g.quantile(.75)}).reset_index()


def plot(buckets: pd.DataFrame, h: int, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, cls in zip(axes, ["live", "backfill"]):
        b = buckets[(buckets["class"] == cls) & buckets["bucket"].str.startswith("rating ") & (buckets["n"] > 0)]
        if b.empty:
            ax.set_title(f"{cls}: no data")
            continue
        x = np.arange(len(b))
        ax.bar(x, b["mean"] * 100, color="#4c72b0")
        ax.errorbar(x, b["mean"] * 100, yerr=[(b["mean"] - b["mean_lo"]) * 100, (b["mean_hi"] - b["mean"]) * 100],
                    fmt="none", ecolor="black", capsize=3)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(x, [f"{l.replace('rating ', '')}\nn={n:,}" for l, n in zip(b["bucket"], b["n"])])
        ax.set_title(f"{cls}-rated buys")
        ax.set_xlabel("AI buy rating")
    axes[0].set_ylabel(f"mean {h}-day return minus SPY (%)")
    fig.suptitle(f"Insider buys: {h}-day excess return by AI rating (bars: 95% CI, clustered by month)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["output_dir"]
    (out / "tables").mkdir(exist_ok=True)
    (out / "plots").mkdir(exist_ok=True)
    n_boot = cfg["analysis"]["n_boot"]
    df = load(cfg)

    counts = (df[df["rating"].notna()].groupby(["rating_class", "prompt_version"])
              .agg(rated_buys=("rating", "size"),
                   first_filing=("filing_date", "min"), last_filing=("filing_date", "max"),
                   **{f"with_{h}d_return": (f"ex_{h}", "count") for h in cfg["horizons"]}).reset_index())
    print("\n== Rated qualifying buys ==\n", counts.to_string(index=False))
    counts.to_csv(out / "tables" / "q1_counts.csv", index=False)

    buckets = pd.concat([bucket_table(df, h, n_boot) for h in cfg["horizons"]], ignore_index=True)
    # FDR across every bucket row tested (reference rows excluded).
    tested = ~buckets["bucket"].isin(["ALL BUYS same months"])
    buckets.loc[tested, "p_fdr"] = bh_adjust(buckets.loc[tested, "p_mean_ne_0"])
    buckets.to_csv(out / "tables" / "q1_buckets.csv", index=False)
    show = ["horizon", "class", "bucket", "n", "months", "mean", "mean_lo", "mean_hi", "median", "hit_rate",
            "hit_lo", "hit_hi", "p_fdr"]
    print("\n== Excess return by rating bucket (winsorized mean, 95% CI clustered by month) ==")
    print(buckets[[c for c in show if c in buckets]].round(4).to_string(index=False))

    ics = pd.concat([ic_table(df, h) for h in cfg["horizons"]], ignore_index=True)
    ics.to_csv(out / "tables" / "q1_ic.csv", index=False)
    print("\n== Rank correlation (IC) between signal and excess return ==")
    print(ics[ics["n"] >= 20].round(4).to_string(index=False))

    spreads = pd.concat([spread_table(df, h, n_boot) for h in cfg["horizons"]], ignore_index=True)
    if not spreads.empty and "p" in spreads:
        spreads["p_fdr"] = bh_adjust(spreads["p"])
    spreads.to_csv(out / "tables" / "q1_spreads.csv", index=False)
    print("\n== High-rated minus low-rated ==")
    print(spreads.round(4).to_string(index=False))

    cov = coverage_table(cfg)
    cov.to_csv(out / "tables" / "q1_coverage_bias.csv", index=False)
    print("\n== Coverage check: buys dropped for lack of a price vs buys kept (production 60d excess) ==")
    print(cov.round(4).to_string(index=False))

    plot(buckets[buckets["horizon"] == cfg["horizons"][0]], cfg["horizons"][0], out / "plots" / "q1_rating_buckets.png")
    print(f"\nTables: {out / 'tables'}   Chart: {out / 'plots' / 'q1_rating_buckets.png'}")


if __name__ == "__main__":
    main()
