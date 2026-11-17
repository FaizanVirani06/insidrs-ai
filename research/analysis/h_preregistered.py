"""Pre-registered tests (research/PREREGISTRATION.md). Development sample by default.

    python -m research.analysis.h_preregistered                  # development sample (2010-2024)
    HOLDOUT_CONFIRM=yes python -m research.analysis.h_preregistered --open-holdout   # ONCE, at the end

Part 1: how much of the return is priced in before an outsider can buy (descriptive).
Part 2: hypotheses H1-H5, with FDR, sub-period stability and costs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, normal_p, spread, summarize
from research.common import ROOT, load_config

pd.set_option("display.width", 220, "display.max_columns", 40)
KEYS = ["issuer_cik", "owner_key", "accession_number", "side"]
PRIMARY = "car_ff6_D60"
SECONDARY = ["car_ff6_D20", "car_ff6_D180", "car_mkt_D60", "ex_iwm_D60"]
WINDOWS = ["pre20", "B", "C", "D5", "D20", "D60", "D180"]


def load(cfg) -> pd.DataFrame:
    data = cfg["paths"]["data_dir"]
    a = pd.read_parquet(data / "analysis.parquet")
    a = a[(a["side"] == "buy") & a["qualifies"]]
    ev = pd.read_parquet(data / "events_v2.parquet")
    df = a.merge(ev, on=KEYS, how="inner")
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    pre = cfg["preregistered"]
    df["dip"] = (df["dip_ex20"] <= pre["dip_threshold"]).where(df["dip_ex20"].notna())
    df["post_report"] = df["post_report_days"].between(0, pre["post_report_max_days"]).where(df["post_report_days"].notna())
    df["officer_director"] = df["role"] != "ten_pct_owner"
    df["classified"] = df["trader_type"].isin(["routine", "opportunistic"])
    df["opportunistic"] = df["trader_type"] == "opportunistic"
    df["is_dev"] = df["filing_date"] < pd.Timestamp(pre["holdout_start"])
    return df


def clip_to_dev(df: pd.DataFrame, cols) -> pd.DataFrame:
    """Winsorize at the development sample's 1st/99th percentiles (same cutoffs for the holdout)."""
    df = df.copy()
    for c in cols:
        lo, hi = df.loc[df["is_dev"], c].quantile([0.01, 0.99])
        df[c] = df[c].clip(lo, hi)
    return df


def assumed_cost(df, cfg) -> pd.Series:
    cost, lower = pd.Series(np.nan, index=df.index), 0.0
    for t in cfg["costs"]["round_trip_by_daily_volume"]:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        cost[(df["adv_usd_20d"] >= lower) & (df["adv_usd_20d"] < hi)] = t["cost"]
        lower = hi
    return cost


def hypotheses(df):
    """(id, description, population, top group, bottom group) exactly as pre-registered."""
    dip_known = df["dip"].notna()
    return [
        ("H1", "opportunistic minus routine", df["classified"], df["opportunistic"], ~df["opportunistic"]),
        ("H2", "dip minus no dip", dip_known, df["dip"] == True, df["dip"] == False),  # noqa: E712
        ("H3", "dip & post-report minus others", dip_known & df["post_report"].notna(),
         (df["dip"] == True) & (df["post_report"] == True), ~((df["dip"] == True) & (df["post_report"] == True))),  # noqa: E712
        ("H4", "opportunistic & dip minus other classified", df["classified"] & dip_known,
         df["opportunistic"] & (df["dip"] == True), ~(df["opportunistic"] & (df["dip"] == True))),  # noqa: E712
        ("H5", "infrequent minus frequent officer/director buyers", df["officer_director"],
         ~df["bought_in_prior_window"], df["bought_in_prior_window"]),
    ]


def decomposition(df, n_boot) -> pd.DataFrame:
    groups = {"all qualifying buys": df, "officers & directors": df[df["officer_director"]],
              "10% holders": df[~df["officer_director"]],
              "opportunistic": df[df["trader_type"] == "opportunistic"],
              "routine": df[df["trader_type"] == "routine"],
              "insufficient history": df[df["trader_type"] == "insufficient history"],
              "dip": df[df["dip"] == True], "opportunistic & dip": df[df["opportunistic"] & (df["dip"] == True)]}  # noqa: E712
    rows = []
    for name, g in groups.items():
        for w in WINDOWS:
            for measure in ("car_ff6", "ex_iwm"):
                col = f"{measure}_{w}"
                d = g[g[col].notna()]
                s = summarize(d, col, n_boot=n_boot)
                rows.append({"group": name, "window": w, "measure": measure, **s})
    return pd.DataFrame(rows)


def test_hypotheses(df, cfg, holdout: bool, keep=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_boot = cfg["analysis"]["n_boot"]
    df = df.assign(cost=assumed_cost(df, cfg))
    rows, stability = [], []
    for hid, desc, pop, top, bottom in hypotheses(df):
        if keep and hid not in keep:
            continue
        for outcome in [PRIMARY] + SECONDARY:
            d = df[pop & df[outcome].notna()]
            s = spread(d, outcome, top[d.index], bottom[d.index], n_boot=n_boot)
            t = d[top[d.index]]
            net = (t[outcome] - t["cost"]).mean() if t["cost"].notna().any() else np.nan
            rows.append({"id": hid, "hypothesis": desc, "outcome": outcome, **s,
                         "top_mean": t[outcome].mean(), "top_mean_net_of_costs": net})
        if not holdout:
            for lo, hi in cfg["preregistered"]["subperiods"]:
                d = df[pop & df[PRIMARY].notna() & df["year"].between(lo, hi)]
                s = spread(d, PRIMARY, top[d.index], bottom[d.index], n_boot=n_boot)
                stability.append({"id": hid, "period": f"{lo}-{hi}", **s})
    res = pd.DataFrame(rows)
    prim = res["outcome"] == PRIMARY
    if holdout:
        # one-sided in the predicted (+) direction, Holm across the hypotheses tested
        se = (res["hi"] - res["lo"]) / (2 * 1.96)
        res["p_one_sided"] = [0.5 * normal_p(z) if z > 0 else 1 - 0.5 * normal_p(z) for z in res["spread"] / se]
        p = res.loc[prim, "p_one_sided"].sort_values()
        k = len(p)
        res.loc[p.index, "p_holm"] = np.minimum(1, np.maximum.accumulate([(k - i) * v for i, v in enumerate(p)]))
    else:
        res.loc[prim, "p_fdr"] = bh_adjust(res.loc[prim, "p"])
    return res, pd.DataFrame(stability)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-holdout", action="store_true")
    ap.add_argument("--hypotheses", default="H1,H2,H3,H4,H5",
                    help="holdout only: the hypotheses supported in development, e.g. H1,H4")
    args = ap.parse_args()
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    df = load(cfg)
    df = clip_to_dev(df, [f"{m}_{w}" for m in ("car_ff6", "car_mkt", "ex_iwm") for w in WINDOWS])

    if args.open_holdout:
        if os.environ.get("HOLDOUT_CONFIRM") != "yes":
            raise SystemExit("Opening the holdout spends it. Re-run with HOLDOUT_CONFIRM=yes once development is final.")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ROOT / "research" / "HOLDOUT_LOG.md", "a") as f:
            f.write(f"- {stamp}: holdout opened ({int((~df['is_dev']).sum()):,} buys), "
                    f"testing {args.hypotheses}. Commit this line.\n")
        sample, tag = df[~df["is_dev"]], "holdout"
    else:
        sample, tag = df[df["is_dev"]], "dev"
    print(f"\nSample: {tag}, {len(sample):,} qualifying buys, filed "
          f"{sample['filing_date'].min().date()} to {sample['filing_date'].max().date()}")
    print("Trader types:", sample["trader_type"].value_counts().to_dict())

    dec = decomposition(sample, cfg["analysis"]["n_boot"])
    dec.to_csv(out / f"prereg_decomposition_{tag}.csv", index=False)
    print("\n== Part 1. Mean return by window (factor-adjusted CAR; excess vs IWM in brackets) ==")
    car = dec[dec["measure"] == "car_ff6"].pivot(index="group", columns="window", values="mean")[WINDOWS]
    iwm = dec[dec["measure"] == "ex_iwm"].pivot(index="group", columns="window", values="mean")[WINDOWS]
    table = car.map(lambda v: f"{v:+.2%}") + " [" + iwm.map(lambda v: f"{v:+.2%}") + "]"
    print(table.to_string())
    ci = dec[(dec["measure"] == "car_ff6") & (dec["group"] == "all qualifying buys")]
    print("\nAll qualifying buys, factor-adjusted CAR with 95% CI:")
    print(ci[["window", "n", "months", "mean", "mean_lo", "mean_hi", "median", "hit_rate"]].round(4).to_string(index=False))

    res, stab = test_hypotheses(sample, cfg, holdout=args.open_holdout,
                                keep=args.hypotheses.split(",") if args.open_holdout else None)
    res.to_csv(out / f"prereg_hypotheses_{tag}.csv", index=False)
    print(f"\n== Part 2. Pre-registered hypotheses, primary outcome = {PRIMARY} ==")
    cols = ["id", "hypothesis", "n_top", "n_bottom", "spread", "lo", "hi", "months", "p",
            "p_fdr" if not args.open_holdout else "p_holm", "top_mean", "top_mean_net_of_costs"]
    print(res[res["outcome"] == PRIMARY][[c for c in cols if c in res]].round(4).to_string(index=False))
    if not stab.empty:
        stab.to_csv(out / "prereg_stability_dev.csv", index=False)
        print("\n== Sub-period stability (primary outcome) ==")
        print(stab[["id", "period", "n_top", "n_bottom", "spread", "lo", "hi", "p"]].round(4).to_string(index=False))
    print("\n== Secondary outcomes (not used for decisions) ==")
    print(res[res["outcome"] != PRIMARY][["id", "outcome", "n_top", "spread", "lo", "hi", "p"]].round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
