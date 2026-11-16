"""Robustness checks on the two results that looked positive, plus trading costs.

    python -m research.analysis.robustness

A. Fund track records (Q2): is the 60-day persistence real, or produced by a
   few very active funds buying the same thin stocks over and over?
B. Trading costs: how much of any edge survives realistic costs, by liquidity?
   The cost figures are ASSUMPTIONS from config.yaml, not measurements.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.analysis.stats import spread, summarize, winsorize
from research.common import load_config

pd.set_option("display.width", 220, "display.max_columns", 30)


def fund_persistence(df, cfg, h=60) -> pd.DataFrame:
    n_boot = cfg["analysis"]["n_boot"]
    ret = f"ex_{h}"
    d = df[(df["filing_date"] > pd.Timestamp(cfg["analysis"]["train_end"])) & df[ret].notna()
           & (df["role"] == "ten_pct_owner") & (df[f"prior_n_{h}"] >= 3)].copy()
    d["wr"] = d[f"prior_wins_{h}"] / d[f"prior_n_{h}"]
    d = d[(d["wr"] > 0.6) | (d["wr"] < 0.4)]
    d["high"] = d["wr"] > 0.6
    rows = []

    def add(label, g, cluster_col="month"):
        s = spread(g, ret, g["high"], ~g["high"], cluster_col=cluster_col, n_boot=n_boot)
        rows.append({"check": label, "funds_high": g.loc[g["high"], "insider_id"].nunique(),
                     "funds_low": g.loc[~g["high"], "insider_id"].nunique(), **s})

    add("baseline (as in Q2): every trade, resampling months", d)
    add("resampling whole FUNDS instead of months", d.assign(fund=d["insider_id"]), cluster_col="fund")
    busiest = d["insider_id"].value_counts()
    add("without the 10 most active funds", d[~d["insider_id"].isin(busiest.index[:10])])
    add("without the 50 most active funds", d[~d["insider_id"].isin(busiest.index[:50])])
    # One observation per fund per company per month: repeat buys of one stock count once.
    one = d.groupby(["insider_id", "issuer_cik", "month"], as_index=False).agg(**{ret: (ret, "mean"), "high": ("high", "first")})
    add("one observation per fund-company-month", one)
    # One observation per fund per month.
    one = d.groupby(["insider_id", "month"], as_index=False).agg(**{ret: (ret, "mean"), "high": ("high", "first")})
    add("one observation per fund-month", one)
    out = pd.DataFrame(rows)
    out.insert(0, "top10_funds_share_of_trades", round(float(busiest.iloc[:10].sum() / len(d)), 3))
    return out


def cost_table(df, cfg) -> pd.DataFrame:
    n_boot = cfg["analysis"]["n_boot"]
    tiers = cfg["costs"]["round_trip_by_daily_volume"]
    adv = df["adv_usd_20d"]
    tier, cost, lower = pd.Series("unknown", index=df.index), pd.Series(np.nan, index=df.index), 0.0
    for t in tiers:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        m = (adv >= lower) & (adv < hi)
        tier[m], cost[m], lower = t["label"], t["cost"], hi
    df = df.assign(tier=tier, cost=cost)
    rows = []
    subsets = {"all qualifying buys": df,
               "officers & directors": df[df["role"] != "ten_pct_owner"],
               "stock above its 200-day average": df[df["trend_above_sma_200"] == 1]}
    for h in cfg["horizons"]:
        for sname, sub in subsets.items():
            g0 = sub[sub[f"exsc_{h}"].notna() & sub["cost"].notna()]
            for label in ["ALL LIQUIDITY TIERS"] + [t["label"] for t in tiers]:
                g = g0 if label == "ALL LIQUIDITY TIERS" else g0[g0["tier"] == label]
                if g.empty:
                    continue
                gross = summarize(g, f"exsc_{h}", n_boot=n_boot)
                net = summarize(g.assign(net=g[f"exsc_{h}"] - g["cost"]), "net", n_boot=n_boot)
                rows.append({"horizon": h, "subset": sname, "liquidity": label, "n": len(g),
                             "share_of_buys": len(g) / max(len(g0), 1), "assumed_cost": float(g["cost"].mean()),
                             "gross_mean": gross.get("mean"), "net_mean": net.get("mean"),
                             "net_lo": net.get("mean_lo"), "net_hi": net.get("mean_hi"),
                             "net_hit_rate": net.get("hit_rate")})
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = df[(df["side"] == "buy") & df["qualifies"]].copy()
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    for h in cfg["horizons"]:
        df[f"ex_{h}"] = winsorize(df[f"excess_{h}"])
        df[f"exsc_{h}"] = winsorize(df[f"excess_smallcap_{h}"])

    a = fund_persistence(df, cfg)
    a.to_csv(out / "robust_fund_persistence.csv", index=False)
    print("\n== A. Funds: past win rate >60% minus <40%, next-trade 60-day excess (min 3 prior trades) ==")
    print(a.round(4).to_string(index=False))

    if df["adv_usd_20d"].notna().any():
        b = cost_table(df, cfg)
        b.to_csv(out / "robust_costs.csv", index=False)
        print("\n== B. Excess return vs Russell 2000 before and after ASSUMED round-trip trading costs ==")
        print(b.round(4).to_string(index=False))
        liq = df["adv_usd_20d"].describe(percentiles=[.1, .25, .5, .75, .9]).round(0)
        print("\nTypical daily dollar volume of bought stocks:\n", liq.to_string())
    else:
        print("\n== B. skipped: no volume data (needs the Yahoo price download) ==")
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
