"""Study 2 (PREREGISTRATION.md): can a real-time reader capture the disclosure reaction?

    python -m research.analysis.realtime                      # development sample (filed 2010-2024)
    HOLDOUT_CONFIRM=yes python -m research.analysis.realtime --open-holdout --hypotheses R1

For each qualifying buy, using the EDGAR acceptance time (New York) and daily
open/close prices:
    P_before  last price before the filing was public
    P_first   first price a trader using daily data could buy at
    Gap       P_before -> P_first          (lost to anyone using daily prices)
    Capture   P_first  -> standard entry   (what acting immediately adds)
    RT60      P_first  -> 60 trading days later
All are excess returns vs IWM over the same timestamps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os

import numpy as np
import pandas as pd

from research.analysis.stats import bh_adjust, summarize
from research.build_dataset import D, PriceIndex
from research.common import ROOT, load_benchmark, load_benchmark_open, load_config, price_paths

pd.set_option("display.width", 220, "display.max_columns", 30)
OPEN_MIN, CLOSE_MIN = 9 * 60 + 30, 16 * 60


def first_prices(cal: np.ndarray, acc_date: np.ndarray, acc_min: np.ndarray):
    """Session and (day, field) of P_before and P_first on the market calendar `cal`.

    field 0 = open, 1 = close. Returns session labels and day/field arrays.
    """
    n = len(acc_date)
    k = np.searchsorted(cal, acc_date, side="left")            # first trading day on/after the acceptance date
    on_day = (k < len(cal)) & (cal[np.minimum(k, len(cal) - 1)] == acc_date)
    session = np.full(n, "", dtype=object)
    bd, bf, fd_, ff = np.full(n, -1), np.zeros(n, int), np.full(n, -1), np.zeros(n, int)
    pre = on_day & (acc_min < OPEN_MIN)
    reg = on_day & (acc_min >= OPEN_MIN) & (acc_min < CLOSE_MIN)
    aft = on_day & (acc_min >= CLOSE_MIN)
    off = ~on_day
    session[pre], session[reg], session[aft], session[off] = "pre-market", "market hours", "after close", "non-trading day"
    bd[pre], bf[pre], fd_[pre], ff[pre] = k[pre] - 1, 1, k[pre], 0          # prev close -> open
    bd[reg], bf[reg], fd_[reg], ff[reg] = k[reg], 0, k[reg], 1              # open -> close (conservative)
    bd[aft], bf[aft], fd_[aft], ff[aft] = k[aft], 1, k[aft] + 1, 0          # close -> next open
    bd[off], bf[off], fd_[off], ff[off] = k[off] - 1, 1, k[off], 0          # last close -> next open
    bad = (bd < 0) | (fd_ >= len(cal))
    bd[bad], fd_[bad] = -1, -1
    return session, bd, bf, fd_, ff


def price_at(series_dates, opens, closes, cal, day_idx, field):
    """Stock price at calendar day index + field; NaN if the stock has no price that day."""
    out = np.full(len(day_idx), np.nan)
    ok = day_idx >= 0
    days = cal[np.where(ok, day_idx, 0)]
    pos = np.searchsorted(series_dates, days)
    pos_c = np.minimum(pos, len(series_dates) - 1)
    hit = ok & (pos < len(series_dates)) & (series_dates[pos_c] == days)
    vals = np.where(field == 0, opens[pos_c] if opens is not None else np.nan, closes[pos_c])
    out[hit] = vals[hit]
    return out, np.where(hit, pos_c, -1)


def measure(df: pd.DataFrame, cfg) -> pd.DataFrame:
    acc = pd.read_parquet(cfg["paths"]["data_dir"] / "acceptance.parquet")
    df = df.merge(acc, on="accession_number", how="inner")
    local = df["acceptance_utc"].dt.tz_convert("America/New_York")
    df["acc_date"] = local.dt.tz_localize(None).dt.normalize()
    df["acc_min"] = local.dt.hour * 60 + local.dt.minute
    df["acc_after_filing_date"] = df["acc_date"] > df["filing_date"]

    cal, iwm_close = load_benchmark(cfg, "IWM")
    o = load_benchmark_open(cfg, "IWM")
    if o is None:
        raise SystemExit("IWM opens missing: rerun research.fetch_prices --refresh (opens are a new field)")
    iwm_open = pd.Series(o[1], index=o[0]).reindex(cal).to_numpy()
    session, bd, bf, fd_, ff = first_prices(cal, df["acc_date"].to_numpy().astype(D), df["acc_min"].to_numpy())
    df["session"] = session

    def bench(day_idx, field):
        out = np.full(len(day_idx), np.nan)
        ok = day_idx >= 0
        vals = np.where(field == 0, iwm_open[np.where(ok, day_idx, 0)], iwm_close[np.where(ok, day_idx, 0)])
        out[ok] = vals[ok]
        return out

    b_before, b_first = bench(bd, bf), bench(fd_, ff)
    entry_idx = np.searchsorted(cal, df["entry_date"].to_numpy().astype(D))
    entry_idx = np.where((entry_idx < len(cal)) & (cal[np.minimum(entry_idx, len(cal) - 1)]
                                                    == df["entry_date"].to_numpy().astype(D)), entry_idx, -1)
    b_entry = bench(entry_idx, np.ones(len(df), int))
    rt_idx = np.where(fd_ >= 0, fd_ + 60, -1)
    rt_idx = np.where(rt_idx < len(cal), rt_idx, -1)
    b_rt = bench(rt_idx, np.ones(len(df), int))

    prices = PriceIndex(price_paths(cfg)[0])
    cols = {c: np.full(len(df), np.nan) for c in ("p_before", "p_first", "p_entry", "p_rt60")}
    for cik, pos in df.groupby("issuer_cik").indices.items():
        sd, sc = prices.get(cik)
        if len(sd) == 0:
            continue
        so = prices.get_open(cik)
        cols["p_before"][pos] = price_at(sd, so, sc, cal, bd[pos], bf[pos])[0]
        cols["p_first"][pos] = price_at(sd, so, sc, cal, fd_[pos], ff[pos])[0]
        cols["p_entry"][pos] = price_at(sd, so, sc, cal, entry_idx[pos], np.ones(len(pos), int))[0]
        cols["p_rt60"][pos] = price_at(sd, so, sc, cal, rt_idx[pos], np.ones(len(pos), int))[0]
    for c, v in cols.items():
        df[c] = v
    later = entry_idx >= fd_                         # standard entry must not precede the first available price
    df["gap"] = df["p_first"] / df["p_before"] - 1 - (b_first / b_before - 1)
    df["capture"] = np.where(later, df["p_entry"] / df["p_first"] - 1 - (b_entry / b_first - 1), np.nan)
    df["rt60"] = df["p_rt60"] / df["p_first"] - 1 - (b_rt / b_first - 1)
    df["std60"] = df["excess_smallcap_60"]           # the original design, for comparison
    return df


def assumed_cost(df, cfg) -> pd.Series:
    cost, lower = pd.Series(np.nan, index=df.index), 0.0
    for t in cfg["costs"]["round_trip_by_daily_volume"]:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        cost[(df["adv_usd_20d"] >= lower) & (df["adv_usd_20d"] < hi)] = t["cost"]
        lower = hi
    return cost


def exploratory_liquidity(df, cfg, out, n_boot) -> None:
    """EXPLORATORY, not pre-registered: is the captured reaction larger than trading costs anywhere?"""
    tiers, lower = cfg["costs"]["round_trip_by_daily_volume"], 0.0
    df = df.copy()
    df["tier"] = "unknown"
    for t in tiers:
        hi = np.inf if t["max_usd"] is None else t["max_usd"]
        df.loc[(df["adv_usd_20d"] >= lower) & (df["adv_usd_20d"] < hi), "tier"] = t["label"]
        lower = hi
    df["capture_net"] = df["capture"] - df["cost"]          # buy at first price, sell at the standard entry close
    rows = []
    for name, g in [("all", df)] + [(t["label"], df[df["tier"] == t["label"]]) for t in tiers]:
        c = summarize(g[g["capture"].notna()], "capture", n_boot=n_boot)
        nc = summarize(g[g["capture_net"].notna()], "capture_net", n_boot=n_boot)
        rows.append({"liquidity": name, "n": c.get("n"), "assumed_cost": g["cost"].mean(),
                     "capture": c.get("mean"), "capture_lo": c.get("mean_lo"), "capture_hi": c.get("mean_hi"),
                     "capture_net": nc.get("mean"), "net_lo": nc.get("mean_lo"), "net_hi": nc.get("mean_hi")})
    t = pd.DataFrame(rows)
    t.to_csv(out / "realtime_exploratory_liquidity_dev.csv", index=False)
    print("\n== EXPLORATORY (not pre-registered): capture by liquidity, before and after one round trip ==")
    print(t.round(4).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-holdout", action="store_true")
    ap.add_argument("--hypotheses", default="R1,R2")
    args = ap.parse_args()
    cfg = load_config()
    out = cfg["paths"]["output_dir"] / "tables"
    out.mkdir(exist_ok=True)
    n_boot = cfg["analysis"]["n_boot"]
    a = pd.read_parquet(cfg["paths"]["data_dir"] / "analysis.parquet")
    a = a[(a["side"] == "buy") & a["qualifies"]]
    df = measure(a, cfg)
    df["month"] = df["filing_date"].dt.to_period("M").astype(str)
    df["is_dev"] = df["filing_date"] < pd.Timestamp(cfg["preregistered"]["holdout_start"])
    for c in ("gap", "capture", "rt60", "std60"):
        lo, hi = df.loc[df["is_dev"], c].quantile([0.01, 0.99])
        df[c] = df[c].clip(lo, hi)
    df["cost"] = assumed_cost(df, cfg)
    df["rt60_net"] = df["rt60"] - df["cost"]
    df["who"] = np.where(df["role"] == "ten_pct_owner", "10% holders", "officers & directors")

    if args.open_holdout:
        if os.environ.get("HOLDOUT_CONFIRM") != "yes":
            raise SystemExit("Opening the holdout spends it. Re-run with HOLDOUT_CONFIRM=yes once development is final.")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ROOT / "research" / "HOLDOUT_LOG.md", "a") as f:
            f.write(f"- {stamp}: Study 2 holdout opened, testing {args.hypotheses}. Commit this line.\n")
        sample, tag = df[~df["is_dev"]], "holdout"
    else:
        sample, tag = df[df["is_dev"]], "dev"
    in_split = a["filing_date"] < pd.Timestamp(cfg["preregistered"]["holdout_start"])
    n_split = int(in_split.sum() if tag == "dev" else (~in_split).sum())
    print(f"\nSample: {tag}, {len(sample):,} of {n_split:,} qualifying buys matched to an acceptance time")
    print(f"Accepted after the date on the filing (late-night filings): {sample['acc_after_filing_date'].mean():.1%}")

    # In the holdout, print only the pre-registered tests: descriptive tables would reveal
    # 2025+ returns and contaminate the holdout for any later hypothesis.
    if not args.open_holdout:
        rows = []
        groups = [("all", sample)] + [(f"session: {k}", g) for k, g in sample.groupby("session")] + \
                 [(k, g) for k, g in sample.groupby("who")]
        for name, g in groups:
            row = {"group": name, "n": len(g), "share": len(g) / len(sample)}
            for c in ("gap", "capture", "rt60", "std60", "rt60_net"):
                s = summarize(g[g[c].notna()], c, n_boot=n_boot)
                row.update({c: s.get("mean"), f"{c}_lo": s.get("mean_lo"), f"{c}_hi": s.get("mean_hi")})
            row["capture_median"] = g["capture"].median()
            rows.append(row)
        desc = pd.DataFrame(rows)
        desc.to_csv(out / f"realtime_by_session_{tag}.csv", index=False)
        print("\n== Excess return vs IWM: Gap (lost), Capture (gained by acting at once), 60 days from first price ==")
        show = ["group", "n", "share", "gap", "capture", "capture_lo", "capture_hi", "capture_median", "rt60", "std60", "rt60_net"]
        print(desc[show].round(4).to_string(index=False))

        exploratory_liquidity(sample, cfg, out, n_boot)

    tests = []
    for hid, col in (("R1", "capture"), ("R2", "rt60_net")):
        if hid not in args.hypotheses.split(","):
            continue
        s = summarize(sample[sample[col].notna()], col, n_boot=n_boot)
        tests.append({"id": hid, "measure": col, **s})
        if not args.open_holdout:
            for lo, hi in cfg["preregistered"]["subperiods"]:
                g = sample[sample[col].notna() & sample["year"].between(lo, hi)]
                ss = summarize(g, col, n_boot=n_boot)
                tests.append({"id": hid, "measure": f"{col} {lo}-{hi}", **ss})
    t = pd.DataFrame(tests)
    main_rows = ~t["measure"].str.contains(" ")
    if args.open_holdout:
        t.loc[main_rows, "p_one_sided"] = np.where(t.loc[main_rows, "mean"] > 0, t.loc[main_rows, "p_mean_ne_0"] / 2,
                                                   1 - t.loc[main_rows, "p_mean_ne_0"] / 2)
    else:
        t.loc[main_rows, "p_fdr"] = bh_adjust(t.loc[main_rows, "p_mean_ne_0"])
    t.to_csv(out / f"realtime_tests_{tag}.csv", index=False)
    print("\n== Pre-registered tests (R1: capture > 0; R2: 60 days from first price, net of costs > 0) ==")
    cols = ["id", "measure", "n", "months", "mean", "mean_lo", "mean_hi", "median", "hit_rate", "p_mean_ne_0",
            "p_fdr" if not args.open_holdout else "p_one_sided"]
    print(t[[c for c in cols if c in t]].round(4).to_string(index=False))
    print(f"\nTables: {out}")


if __name__ == "__main__":
    main()
