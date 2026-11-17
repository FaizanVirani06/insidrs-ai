"""E1-E3 execution rules (PREREGISTRATION.md, Amendment 4b).

    research/run.sh research.analysis.erules                       # development (filed 2010-2024)
    research/run.sh research.analysis.erules --within S1,S4        # + descriptive results inside S top groups
    HOLDOUT_CONFIRM=yes research/run.sh research.analysis.erules --stage B --rules E1,E3   # once, >= 2027-09-07

Parameters are fixed by the amendment and deliberately NOT in config.yaml.

Data situations the amendment does not cover are handled as proposed for Amendment 6
(see PROPOSED_AMENDMENT_6 below). The script refuses to run until PREREGISTRATION.md
contains "**Amendment 6", so the handling is registered before any results exist.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os

import numpy as np
import pandas as pd

from research.analysis.stats import normal_p, summarize
from research.build_dataset import D, PriceIndex
from research.common import ROOT, load_benchmark, load_benchmark_open, load_config, price_paths, require_clean_commit

pd.set_option("display.width", 220, "display.max_columns", 30)

# ---- fixed by Amendment 4(b) -------------------------------------------------------------
H = 60                      # holding window: t0 close to t0+60 close
E1_LIMIT, E1_DAYS = 0.98, 3
E2_TRAIL = 0.85
E3_TARGET, E3_STOP = 1.20, 0.85
RULES = ["E1", "E2", "E3"]
STAGES = {"dev": ("2010-01-01", "2024-12-31"), "B": ("2026-12-01", "2027-05-31")}
OPEN_ON_OR_AFTER = {"B": dt.date(2027, 9, 7)}

PROPOSED_AMENDMENT_6 = """
P1  Signals without a full t0..t0+60 price window (series ends: delisted or not yet matured)
    have no B0 and are excluded from every rule; counted (by filing month in a holdout).
P2  Signals whose daily-volume bucket is unknown (no 20-day dollar volume) have no cost and are
    excluded from every rule; counted.
P3  If a rule must execute at an open that is missing (E1 fill day, E2 exit day, or an E3 day whose
    low/high reaches a level), the signal is excluded from every rule (same population for all
    rules); counted. A missing high or low on other days simply cannot trigger (Amendment 4b).
P4  Development p-values are two-sided (as for S1-S10); "positive mean D" enforces the sign.
P5  IWM prices are taken on the same dates; if IWM has no bar that day, its last earlier bar is used.
"""


# ---- one signal -------------------------------------------------------------------------
def simulate(o, h, l, c, io, ic, cost):
    """Outcomes for one signal. Arrays have H+1 entries: index 0 = t0 ... H = t0+60.

    o/h/l/c: stock open/high/low/close (adjusted); io/ic: IWM open/close on the same days.
    Returns a dict with V for B0, E1, E1 (half cost), E1c, E2, E3, plus diagnostics.
    V = stock return in the position - IWM return over the same span - cost (0 if no position).
    `invalid` is True when a required execution price is missing (proposed P3).
    """
    nan = float("nan")
    out = {"invalid": False}

    def leg(p_in, p_out, b_in, b_out, cst):
        return (p_out / p_in - 1.0) - (b_out / b_in - 1.0) - cst

    out["B0"] = leg(c[0], c[H], ic[0], ic[H], cost)

    # E1: limit at 0.98 x P0, days t0+1..t0+3; fills only if the low goes BELOW L
    L = E1_LIMIT * c[0]
    out.update(E1=0.0, E1_half=0.0, e1_filled=False, e1_day=np.nan)
    for k in range(1, E1_DAYS + 1):
        if np.isfinite(l[k]) and l[k] < L:
            if not np.isfinite(o[k]):
                out["invalid"] = True
                break
            px = min(o[k], L)
            out["E1"] = leg(px, c[H], io[k], ic[H], cost)
            out["E1_half"] = leg(px, c[H], io[k], ic[H], cost / 2)
            out["e1_filled"], out["e1_day"] = True, k
            break
    # E1c: like E1, but an unfilled order buys at the t0+3 close
    out["E1c"] = out["E1"] if out["e1_filled"] else leg(c[E1_DAYS], c[H], ic[E1_DAYS], ic[H], cost)

    # E2: trailing stop on closes t0+1..t0+59, exit at the next day's open
    out.update(E2=out["B0"], e2_fired=False, e2_days=H)
    peak = c[0]
    for t in range(1, H):
        peak = max(peak, c[t])
        if c[t] <= E2_TRAIL * peak:
            if not np.isfinite(o[t + 1]):
                out["invalid"] = True
            else:
                out["E2"] = leg(c[0], o[t + 1], ic[0], io[t + 1], cost)
            out["e2_fired"], out["e2_days"] = True, t + 1
            break

    # E3: bracket, checked t0+1..t0+60; gaps exit at the open; stop first if both are hit the same day
    target, stop = E3_TARGET * c[0], E3_STOP * c[0]
    out.update(E3=out["B0"], e3_exit="none", e3_days=H)
    for k in range(1, H + 1):
        hit_stop = np.isfinite(l[k]) and l[k] <= stop
        hit_target = np.isfinite(h[k]) and h[k] >= target
        if np.isfinite(o[k]) and (o[k] <= stop or o[k] >= target):
            out["E3"] = leg(c[0], o[k], ic[0], io[k], cost)
            out["e3_exit"], out["e3_days"] = ("stop_gap" if o[k] <= stop else "target_gap"), k
            break
        if hit_stop or hit_target:
            if not np.isfinite(o[k]):            # cannot tell whether it gapped through the level
                out["invalid"] = True
                out["e3_exit"], out["e3_days"] = "unknown", k
                break
            px = stop if hit_stop else target
            out["E3"] = leg(c[0], px, ic[0], io[k], cost)
            out["e3_exit"], out["e3_days"] = ("stop" if hit_stop else "target"), k
            break
    if out["invalid"]:
        for key in ("B0", "E1", "E1_half", "E1c", "E2", "E3"):
            out[key] = nan
    return out


# ---- all signals ------------------------------------------------------------------------
def cost_bucket(adv: pd.Series, cfg) -> tuple[pd.Series, pd.Series]:
    cost, label, lower = pd.Series(np.nan, index=adv.index), pd.Series("unknown", index=adv.index), 0.0
    for t in cfg["costs"]["round_trip_by_daily_volume"]:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        m = (adv >= lower) & (adv < hi)
        cost[m], label[m], lower = t["cost"], t["label"], hi
    return cost, label


def build_signals(cfg) -> pd.DataFrame:
    a = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    df = a[(a["side"] == "buy") & a["qualifies"]].copy().reset_index(drop=True)
    df["cost"], df["bucket"] = cost_bucket(df["adv_usd_20d"], cfg)
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    cal, iwm_c = load_benchmark(cfg, "IWM")
    o = load_benchmark_open(cfg, "IWM")
    if o is None:
        raise SystemExit("IWM opens missing: run research.fetch_prices --refresh")
    iwm_o = pd.Series(o[1], index=o[0]).reindex(cal).to_numpy()
    prices = PriceIndex(price_paths(cfg)[0])
    rows = []
    for cik, g in df.groupby("issuer_cik"):
        dates, closes = prices.get(cik)
        opens = prices.get_open(cik)
        highs, lows = prices.get_high_low(cik)
        if len(dates) == 0 or opens is None or highs is None:
            for i in g.index:
                rows.append({"idx": i, "status": "no price data"})
            continue
        t0s = np.searchsorted(dates, g["entry_date"].to_numpy().astype(D))
        for i, t0 in zip(g.index, t0s):
            if t0 >= len(dates) or dates[t0] != np.datetime64(g.at[i, "entry_date"], "D"):
                rows.append({"idx": i, "status": "no entry bar"})
                continue
            if t0 + H >= len(dates):
                rows.append({"idx": i, "status": "window incomplete"})          # P1
                continue
            if not np.isfinite(g.at[i, "cost"]):
                rows.append({"idx": i, "status": "unknown volume bucket"})      # P2
                continue
            sl = slice(t0, t0 + H + 1)
            bi = np.searchsorted(cal, dates[sl], side="right") - 1              # P5
            r = simulate(opens[sl], highs[sl], lows[sl], closes[sl], iwm_o[bi], iwm_c[bi], float(g.at[i, "cost"]))
            r["idx"], r["status"] = i, ("missing execution open" if r["invalid"] else "ok")   # P3
            rows.append(r)
    sim = pd.DataFrame(rows).set_index("idx")
    return df.join(sim)


def in_stage(dates, stage):
    lo, hi = STAGES[stage]
    return (dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "B"], default="dev")
    ap.add_argument("--rules", default="", help="holdout B only: the rules supported in development")
    ap.add_argument("--within", default="", help="descriptive: also report inside these S hypotheses' top groups")
    args = ap.parse_args()
    commit = require_clean_commit()
    prereg = (ROOT / "research" / "PREREGISTRATION.md").read_text()
    if "**Amendment 6" not in prereg:
        raise SystemExit("Refusing to run: the handling of uncovered data situations (P1-P5 in this module) must be "
                         "registered as Amendment 6 first.")
    if args.stage == "B":
        today = dt.datetime.now(dt.timezone.utc).date()
        if today < OPEN_ON_OR_AFTER["B"]:
            raise SystemExit(f"Refusing to open holdout B: allowed on or after {OPEN_ON_OR_AFTER['B']} (UTC); today is {today}.")
        if os.environ.get("HOLDOUT_CONFIRM") != "yes":
            raise SystemExit("Opening a holdout spends it. Re-run with HOLDOUT_CONFIRM=yes once development is final.")
        if not [r for r in args.rules.split(",") if r]:
            raise SystemExit("Name the rules supported in development, e.g. --rules E1,E3")

    cfg = load_config()
    n_boot = cfg["analysis"]["n_boot"]
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    sig = build_signals(cfg)
    dev = in_stage(sig["filing_date"], "dev")
    ok = sig["status"] == "ok"
    for r in RULES + ["E1_half", "E1c"]:
        sig[f"D_{r}"] = sig[r] - sig["B0"]
        lo, hi = sig.loc[dev & ok, f"D_{r}"].quantile([0.01, 0.99])     # development cutoffs
        sig[f"D_{r}"] = sig[f"D_{r}"].clip(lo, hi)

    if args.stage == "B":
        keep = [r for r in args.rules.split(",") if r]
        s = sig[in_stage(sig["filing_date"], "B")]
        miss = s.loc[s["status"] != "ok", "month"].value_counts().sort_index()
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ROOT / "research" / "HOLDOUT_LOG.md", "a") as f:
            f.write(f"- {stamp}: E-rules holdout B opened at commit {commit}, testing {','.join(keep)}. "
                    f"Signals without an outcome by month: {miss.to_dict()}. Commit this line.\n")
        print(f"\nHoldout B: {len(s):,} signals; without an outcome by month: {miss.to_dict()}")
        rows = []
        for r in keep:
            d = s[s["status"] == "ok"]
            st = summarize(d, f"D_{r}", n_boot=n_boot)
            se = (st.get("mean_hi", np.nan) - st.get("mean_lo", np.nan)) / (2 * 1.96)
            z = st.get("mean", np.nan) / se if se and se > 0 else np.nan
            p1 = 0.5 * normal_p(z) if z > 0 else 1 - 0.5 * normal_p(z)
            rows.append({"rule": r, "n": st.get("n"), "mean_D": st.get("mean"), "lo": st.get("mean_lo"),
                         "hi": st.get("mean_hi"), "p_one_sided": p1})
        t = pd.DataFrame(rows).sort_values("p_one_sided")
        k = len(t)
        t["p_holm"] = np.minimum(1, np.maximum.accumulate([(k - i) * v for i, v in enumerate(t["p_one_sided"])]))
        t.to_csv(out / "erules_holdout_B.csv", index=False)
        print("\n== E rules, holdout B (only the pre-registered tests are shown) ==")
        print(t.round(4).to_string(index=False))
        return

    s = sig[dev]
    print(f"\nDevelopment: {len(s):,} qualifying buys (filed 2010-2024)")
    print("Signal status (P1-P3):", s["status"].value_counts().to_dict())
    d = s[s["status"] == "ok"].copy()

    # ---- pre-registered tests
    rows = []
    for r in RULES:
        st = summarize(d, f"D_{r}", n_boot=n_boot)
        rows.append({"rule": r, "n": st.get("n"), "months": st.get("months"), "mean_D": st.get("mean"),
                     "lo": st.get("mean_lo"), "hi": st.get("mean_hi"), "median_D": st.get("median"),
                     "p": st.get("p_mean_ne_0")})
    t = pd.DataFrame(rows)
    order = t["p"].sort_values()
    k = len(order)
    t.loc[order.index, "p_holm"] = np.minimum(1, np.maximum.accumulate([(k - i) * v for i, v in enumerate(order)]))
    stab = []
    for r in RULES:
        for lo, hi in cfg["preregistered"]["subperiods"]:
            g = d[d["year"].between(lo, hi)]
            st = summarize(g, f"D_{r}", n_boot=n_boot)
            stab.append({"rule": r, "period": f"{lo}-{hi}", "n": st.get("n"), "mean_D": st.get("mean"),
                         "lo": st.get("mean_lo"), "hi": st.get("mean_hi")})
    stab = pd.DataFrame(stab)
    signs = stab.groupby("rule")["mean_D"].apply(lambda v: [int(np.sign(x)) if np.isfinite(x) else 0 for x in v])
    t["subperiod_signs"] = t["rule"].map(signs)
    t["supported"] = [bool(ph < 0.05 and m > 0 and all(x == 1 for x in sg))
                      for ph, m, sg in zip(t["p_holm"], t["mean_D"], t["subperiod_signs"])]
    t.to_csv(out / "erules_dev_tests.csv", index=False)
    stab.to_csv(out / "erules_dev_stability.csv", index=False)
    print("\n== E1-E3, development: D = V(rule) - V(B0), winsorized; Holm across E1-E3 ==")
    print(t.round(4).to_string(index=False))
    print("\n== Sub-periods ==")
    print(stab.round(4).to_string(index=False))

    # ---- descriptive (not tested)
    desc = {"B0 mean V": d["B0"].mean(), "E1 fill rate": d["e1_filled"].mean(),
            "B0 V, E1 filled": d.loc[d["e1_filled"], "B0"].mean(),
            "B0 V, E1 unfilled": d.loc[~d["e1_filled"], "B0"].mean(),
            "E1 mean V": d["E1"].mean(), "E1 half-cost mean D (sensitivity)": d["D_E1_half"].mean(),
            "E1c mean D": d["D_E1c"].mean(), "E2 exit fired": d["e2_fired"].mean(),
            "E2 mean days held": d["e2_days"].mean(), "E3 mean days held": d["e3_days"].mean()}
    print("\n== Descriptive (not tested) ==")
    for k_, v in desc.items():
        print(f"  {k_:38s} {v:+.4f}" if "rate" not in k_ and "fired" not in k_ and "days" not in k_ else f"  {k_:38s} {v:.3f}")
    print("  E3 exits:", d["e3_exit"].value_counts(normalize=True).round(3).to_dict())
    byb = d.groupby("bucket")[["B0"] + [f"D_{r}" for r in RULES + ["E1c", "E1_half"]] + ["e1_filled"]].mean()
    byb.insert(0, "n", d.groupby("bucket").size())
    byb.to_csv(out / "erules_dev_by_bucket.csv")
    print("\nBy daily-volume bucket (mean V for B0, mean D for rules):")
    print(byb.round(4).to_string())

    if args.within:
        from research.analysis.study3 import hypotheses, prepare
        ev, ann, q = prepare(cfg)
        keys = ["issuer_cik", "owner_key", "accession_number"]
        rows = []
        for hid, desc_, frame, pop, top, bottom in hypotheses(ev, ann, q):
            if hid not in args.within.split(",") or frame is ann:
                continue
            tg = ev[pop & top.astype(bool) & (ev["side"] == "buy")][keys].drop_duplicates()
            g = d.merge(tg, on=keys)
            row = {"within": hid, "n": len(g), "B0 mean V": g["B0"].mean()}
            row.update({f"mean D_{r}": g[f"D_{r}"].mean() for r in RULES})
            rows.append(row)
        w = pd.DataFrame(rows)
        w.to_csv(out / "erules_dev_within_S.csv", index=False)
        print("\n== Descriptive: E rules inside the top group of S hypotheses ==")
        print(w.round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
