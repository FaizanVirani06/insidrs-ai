"""Study 3 (PREREGISTRATION.md): hypotheses S1-S10.

    python -m research.analysis.study3                                   # development (filed 2010-2024)
    HOLDOUT_CONFIRM=yes python -m research.analysis.study3 --stage A --hypotheses S1,S5   # Holdout A, once
    HOLDOUT_CONFIRM=yes python -m research.analysis.study3 --stage B --hypotheses S1,S5   # forward holdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import os

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, normal_p, spread
from research.common import ROOT, load_config

pd.set_option("display.width", 220, "display.max_columns", 30)
PRIMARY = "bhar_ff6_D60"
SECONDARY = ["bhar_ff6_D20", "bhar_ff6_D180", "ex_iwm_D60"]
STAGES = {"dev": ("2010-01-01", "2024-12-31"), "A": ("2025-01-01", "2026-11-30"), "B": ("2026-12-01", "2100-01-01")}
PREDICTED = {"S1": 1, "S2": 1, "S3": 1, "S4": 1, "S5": 1, "S6": 1, "S7": 1, "S8": -1, "S9": 1, "S10": 1}


def in_stage(dates: pd.Series, stage: str) -> pd.Series:
    lo, hi = STAGES[stage]
    return (dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi))


def assumed_cost(adv: pd.Series, cfg) -> pd.Series:
    cost, lower = pd.Series(np.nan, index=adv.index), 0.0
    for t in cfg["costs"]["round_trip_by_daily_volume"]:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        cost[(adv >= lower) & (adv < hi)] = t["cost"]
        lower = hi
    return cost


def prepare(cfg):
    data = cfg["paths"]["data_dir"]
    ev = pd.read_parquet(data / "study3_events.parquet")
    ann = pd.read_parquet(data / "study3_announcements.parquet")
    ev["month"] = ev["filing_date"].dt.to_period("M").astype(str)
    ann["month"] = ann["ann_day"].dt.to_period("M").astype(str)
    dev_ev, dev_ann = in_stage(ev["filing_date"], "dev"), in_stage(ann["ann_day"], "dev")
    # winsorize at development cutoffs, separately for buys, sells and exercises
    for c in [PRIMARY] + SECONDARY + ["bhar_ff6_C", "bhar_ff6_B"]:
        for side in ev["side"].unique():
            m = ev["side"] == side
            lo, hi = ev.loc[m & dev_ev, c].quantile([0.01, 0.99])
            ev.loc[m, c] = ev.loc[m, c].clip(lo, hi)
    lo, hi = ann.loc[dev_ann, "react3"].quantile([0.01, 0.99])
    ann["react3"] = ann["react3"].clip(lo, hi)
    # S1 quintile cutoffs from development buys
    q = ev.loc[(ev["side"] == "buy") & dev_ev, "bhar_ff6_C"].quantile([0.2, 0.8]).to_numpy()
    ev["cost"] = assumed_cost(ev["adv_usd_20d"], cfg)
    return ev, ann, q


def hypotheses(ev: pd.DataFrame, ann: pd.DataFrame, q):
    """(id, description, frame, population, top, bottom) exactly as pre-registered."""
    buy, sell, exe = ev["side"] == "buy", ev["side"] == "sell", ev["side"] == "exercise"
    od = ev["role"] != "ten_pct_owner"
    plan = ev["plan_10b5_1"] == True  # noqa: E712
    tax = ev["mentions_tax"] == True  # noqa: E712
    after_ann = ev["days_since_ann"].between(0, 30) & ev["last_ann_react3"].notna()
    eligible3 = (ev["prior36_sells"] + ev["prior36_buys"]) >= 1
    switcher = (ev["prior36_sells"] >= 3) & (ev["prior36_buys"] == 0)
    accum = ev["multi_day"].fillna(False) | ev["repeat_30d"].fillna(False).astype(bool)
    d13 = ev["days_since_13d"].between(0, 365)
    return [
        ("S1", "disclosure reaction: top minus bottom quintile", ev, buy & ev["bhar_ff6_C"].notna(),
         ev["bhar_ff6_C"] >= q[1], ev["bhar_ff6_C"] <= q[0]),
        ("S2", "price fell between trade and filing minus rose", ev, buy & ev["bhar_ff6_B"].notna(),
         ev["bhar_ff6_B"] <= -0.02, ev["bhar_ff6_B"] >= 0.02),
        ("S3", "long-time seller turned buyer minus other active insiders", ev, buy & eligible3, switcher, ~switcher),
        ("S4", "accumulation minus single buy", ev, buy, accum, ~accum),
        ("S5", "earnings release after officer/director buy minus without", ann, ann["react3"].notna(),
         ann["od_buy_90d"], ~ann["od_buy_90d"]),
        ("S6", "bought after an earnings drop minus after other releases", ev, buy & after_ann,
         ev["last_ann_react3"] <= -0.05, ev["last_ann_react3"] > -0.05),
        ("S7", "discretionary buys minus 10b5-1 plan buys", ev, buy & ev["plan_10b5_1"].notna(), ~plan, plan),
        ("S8", "discretionary sells minus plan sells (stock return)", ev, sell & ev["plan_10b5_1"].notna(),
         ~plan & ~tax, plan),
        ("S9", "exercise-and-hold minus exercise-and-sell (officers/directors)", ev, exe & od,
         ev["hold"] == True, ev["hold"] == False),  # noqa: E712
        ("S10", "10% holder buys with a recent Schedule 13D minus without", ev,
         buy & (ev["is_ten_percent_owner"] == 1), d13, ~d13),
    ]


def run(ev, ann, q, cfg, stage, keep, stability: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_boot = cfg["analysis"]["n_boot"]
    rows, stab = [], []
    ev_s, ann_s = in_stage(ev["filing_date"], stage), in_stage(ann["ann_day"], stage)
    for hid, desc, frame, pop, top, bottom in hypotheses(ev, ann, q):
        if keep and hid not in keep:
            continue
        is_ann = frame is ann
        outcomes = ["react3"] if is_ann else [PRIMARY] + SECONDARY
        sel = pop & (ann_s if is_ann else ev_s)
        for k, outcome in enumerate(outcomes):
            d = frame[sel & frame[outcome].notna()]
            s = spread(d, outcome, top[d.index].astype(bool), bottom[d.index].astype(bool), n_boot=n_boot)
            row = {"id": hid, "hypothesis": desc, "outcome": outcome, "primary": k == 0, **s}
            if k == 0 and not is_ann and hid != "S8":
                t = d[top[d.index].astype(bool)]
                row["top_mean"], row["top_mean_net_of_costs"] = t[outcome].mean(), (t[outcome] - t["cost"]).mean()
            rows.append(row)
            if k == 0 and stability:
                for lo, hi in cfg["preregistered"]["subperiods"]:
                    dd = d[d["year"].between(lo, hi)]
                    ss = spread(dd, outcome, top[dd.index].astype(bool), bottom[dd.index].astype(bool), n_boot=n_boot)
                    stab.append({"id": hid, "period": f"{lo}-{hi}", **ss})
    return pd.DataFrame(rows), pd.DataFrame(stab)


def verdicts(res: pd.DataFrame, stab: pd.DataFrame) -> pd.DataFrame:
    """Development decision rule: FDR p < 0.05, predicted sign, same sign in every sub-period."""
    prim = res[res["primary"]].copy()
    prim["p_fdr"] = bh_adjust(prim["p"])
    prim["predicted"] = prim["id"].map(PREDICTED)
    signs = stab.groupby("id")["spread"].apply(lambda s: [int(np.sign(v)) if np.isfinite(v) else 0 for v in s])
    prim["subperiod_signs"] = prim["id"].map(signs)
    prim["supported"] = [
        bool(pf < 0.05 and np.sign(sp) == pr and isinstance(sg, list) and len(sg) == 3 and all(x == pr for x in sg))
        for pf, sp, pr, sg in zip(prim["p_fdr"], prim["spread"], prim["predicted"], prim["subperiod_signs"])]
    return prim


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "A", "B"], default="dev")
    ap.add_argument("--hypotheses", default="", help="holdout only: the hypotheses supported in development")
    args = ap.parse_args()
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    ev, ann, q = prepare(cfg)

    if args.stage == "dev":
        res, stab = run(ev, ann, q, cfg, "dev", None, stability=True)
        prim = verdicts(res, stab)
        res.to_csv(out / "study3_dev_all_outcomes.csv", index=False)
        stab.to_csv(out / "study3_dev_stability.csv", index=False)
        prim.to_csv(out / "study3_dev_primary.csv", index=False)
        dev = in_stage(ev["filing_date"], "dev")
        print(f"\nDevelopment: {int((dev & (ev['side'] == 'buy')).sum()):,} buys, {int((dev & (ev['side'] == 'sell')).sum()):,} sells, "
              f"{int((dev & (ev['side'] == 'exercise')).sum()):,} exercises, "
              f"{int(in_stage(ann['ann_day'], 'dev').sum()):,} earnings releases")
        print("Coverage by year: 10b5-1 mentioned (buys/sells), releases with a 3-day reaction")
        cov = pd.DataFrame({
            "buys_10b5_1": ev[ev["side"] == "buy"].groupby("year")["plan_10b5_1"].mean(),
            "sells_10b5_1": ev[ev["side"] == "sell"].groupby("year")["plan_10b5_1"].mean(),
            "releases": ann[ann["react3"].notna()].groupby("year").size()})
        print(cov.round(3).to_string())
        print(f"\nS1 quintile cutoffs (disclosure-window BHAR): bottom <= {q[0]:+.4f}, top >= {q[1]:+.4f}")
        print("\n== Study 3, primary outcome (S5: 3-day earnings reaction; others: 60-day factor BHAR) ==")
        cols = ["id", "hypothesis", "n_top", "n_bottom", "spread", "lo", "hi", "months", "p", "p_fdr",
                "predicted", "subperiod_signs", "supported", "top_mean", "top_mean_net_of_costs"]
        print(prim[[c for c in cols if c in prim]].round(4).to_string(index=False))
        print("\n== Sub-period spreads ==")
        print(stab[["id", "period", "n_top", "n_bottom", "spread", "lo", "hi", "p"]].round(4).to_string(index=False))
        print("\n== Secondary outcomes (not used for decisions) ==")
        print(res[~res["primary"]][["id", "outcome", "n_top", "n_bottom", "spread", "lo", "hi", "p"]].round(4).to_string(index=False))
        return

    if os.environ.get("HOLDOUT_CONFIRM") != "yes":
        raise SystemExit("Opening a holdout spends it. Re-run with HOLDOUT_CONFIRM=yes once development is final.")
    keep = [h for h in args.hypotheses.split(",") if h]
    if not keep:
        raise SystemExit("Name the hypotheses supported in development, e.g. --hypotheses S1,S5")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(ROOT / "research" / "HOLDOUT_LOG.md", "a") as f:
        f.write(f"- {stamp}: Study 3 holdout {args.stage} opened, testing {','.join(keep)}. Commit this line.\n")
    res, _ = run(ev, ann, q, cfg, args.stage, keep, stability=False)
    prim = res[res["primary"]].copy()
    se = (prim["hi"] - prim["lo"]) / (2 * 1.96)
    z = prim["id"].map(PREDICTED) * prim["spread"] / se
    prim["p_one_sided"] = [0.5 * normal_p(v) if v > 0 else 1 - 0.5 * normal_p(v) for v in z]
    order = prim["p_one_sided"].sort_values()
    k = len(order)
    prim.loc[order.index, "p_holm"] = np.minimum(1, np.maximum.accumulate([(k - i) * v for i, v in enumerate(order)]))
    prim.to_csv(out / f"study3_holdout_{args.stage}.csv", index=False)
    print(f"\n== Study 3, holdout {args.stage} (only the pre-registered tests are shown) ==")
    print(prim[["id", "hypothesis", "n_top", "n_bottom", "spread", "lo", "hi", "months", "p_one_sided", "p_holm"]]
          .round(4).to_string(index=False))


if __name__ == "__main__":
    main()
