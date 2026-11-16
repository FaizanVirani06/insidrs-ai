"""Question 4 (brief): do insider SELLS carry any signal?

    python -m research.analysis.q4_sells

Returns here are the STOCK's excess return after the filing (not a short
position).  If sells were informative the stock would lag its benchmark
afterwards, i.e. the numbers below would be clearly negative, and more
negative than for a typical stock.  Buys are shown alongside for contrast.

Not separated here: pre-planned (10b5-1) and tax-related sales, which are
known to be uninformative and make up a large share of sells.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, information_coefficient, spread, summarize, winsorize
from research.common import load_config

pd.set_option("display.width", 220, "display.max_columns", 30)


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    n_boot = cfg["analysis"]["n_boot"]
    df = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = df[df["qualifies"]].copy()
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    df["who"] = np.where(df["role"] == "ten_pct_owner", "funds / 10% holders", "officers & directors")

    rows, spreads, ics = [], [], []
    for h in cfg["horizons"]:
        smallcap = df[f"excess_smallcap_{h}"].notna().any()
        col, bench = (f"excess_smallcap_{h}", "Russell 2000") if smallcap else (f"excess_{h}", "S&P 500")
        df["ex"] = df.groupby("side")[col].transform(winsorize)
        d = df[df["ex"].notna()]
        for side in ("sell", "buy"):
            s = d[d["side"] == side]
            groups = [("all", s)] + [(k, g) for k, g in s.groupby("who")] + [(f"role: {k}", g) for k, g in s.groupby("role")]
            if side == "sell":
                big = s["dollars_total"] >= s["dollars_total"].quantile(0.9)
                groups += [("largest 10% by dollars", s[big]),
                           ("sold >25% of holdings", s[s["pct_holdings_change"] > 25]),
                           ("2+ other insiders also selling", s[s["cluster_n_other"] >= 2])]
            for name, g in groups:
                rows.append({"horizon": h, "benchmark": bench, "side": side, "group": name,
                             **summarize(g, "ex", n_boot=n_boot)})
        # Same company-months, sells vs buys: do stocks insiders sold lag stocks insiders bought?
        spreads.append({"horizon": h, "comparison": "stocks sold minus stocks bought",
                        **spread(d, "ex", d["side"] == "sell", d["side"] == "buy", n_boot=n_boot)})
        o = d[d["who"] == "officers & directors"]
        spreads.append({"horizon": h, "comparison": "officers & directors only: sold minus bought",
                        **spread(o, "ex", o["side"] == "sell", o["side"] == "buy", n_boot=n_boot)})
        # Live AI sell rating: a useful rating would be NEGATIVELY related to the stock's later return.
        live = d[(d["side"] == "sell") & (d["rating_class"] == "live")]
        ics.append({"horizon": h, "signal": "live AI sell rating", **information_coefficient(live, "rating", "ex")})

    table = pd.DataFrame(rows)
    table["p_fdr"] = bh_adjust(table["p_mean_ne_0"]) if "p_mean_ne_0" in table else np.nan
    table.to_csv(out / "q4_sells.csv", index=False)
    show = ["horizon", "benchmark", "side", "group", "n", "months", "mean", "mean_lo", "mean_hi", "median", "hit_rate", "p_fdr"]
    print("\n== Stock's excess return AFTER an insider trade is filed ==")
    print(table[[c for c in show if c in table]].round(4).to_string(index=False))
    sp = pd.DataFrame(spreads)
    sp.to_csv(out / "q4_sell_vs_buy.csv", index=False)
    print("\n== Sells versus buys ==\n", sp.round(4).to_string(index=False))
    ic = pd.DataFrame(ics)
    ic.to_csv(out / "q4_sell_rating_ic.csv", index=False)
    print("\n== Live AI sell rating vs later stock return (negative = rating was useful) ==\n", ic.round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
