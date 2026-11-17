"""Study 3 (PREREGISTRATION.md): event windows and features for hypotheses S1-S10.

    python -m research.build_study3

Inputs: analysis.parquet, filing_flags.parquet, exercises.parquet (from extract),
sec_filings.parquet (from fetch_acceptance), prices, IWM, factors.
Outputs:
    data/study3_events.parquet         one row per qualifying buy, qualifying sell and option-exercise event
    data/study3_announcements.parquet  one row per earnings release (8-K item 2.02)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.build_dataset import D, PriceIndex, role_of
from research.build_events import issuer_windows
from research.common import load_benchmark, load_config, price_paths

KEYS = ["issuer_cik", "owner_key", "accession_number", "side"]
CLOSE_MIN = 16 * 60


def announcement_days(cal: np.ndarray, acc_utc: pd.Series) -> np.ndarray:
    """Trading day on which the market can first react: the acceptance day if accepted
    on a trading day before 16:00 New York time, otherwise the next trading day."""
    local = acc_utc.dt.tz_convert("America/New_York")
    day = local.dt.tz_localize(None).dt.normalize().to_numpy().astype(D)
    minutes = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    k = np.searchsorted(cal, day, side="left")
    on_day = (k < len(cal)) & (cal[np.minimum(k, len(cal) - 1)] == day)
    k = np.where(on_day & (minutes >= CLOSE_MIN), k + 1, k)
    return np.where(k < len(cal), cal[np.minimum(k, len(cal) - 1)], np.datetime64("NaT", "D"))


def reaction3(dates, closes, bench_dates, bench_closes, ann_days) -> np.ndarray:
    """Excess return vs the benchmark from the close 2 trading days before the announcement day
    to the close 1 trading day after (stock's own trading days; NaN if the series has gaps)."""
    out = np.full(len(ann_days), np.nan)
    if len(dates) < 5:
        return out
    a = np.searchsorted(dates, ann_days)
    ok = (a >= 2) & (a + 1 < len(dates))
    a_c = np.clip(a, 2, len(dates) - 2)
    ok &= dates[a_c] == ann_days
    ok &= (dates[a_c + 1] - dates[a_c - 2]).astype(int) <= 10          # no long gap inside the window
    s, t = a_c - 2, a_c + 1
    b0 = np.searchsorted(bench_dates, dates[s], side="right") - 1
    b1 = np.searchsorted(bench_dates, dates[t], side="right") - 1
    stock = closes[t] / closes[s] - 1
    bench = bench_closes[np.maximum(b1, 0)] / bench_closes[np.maximum(b0, 0)] - 1
    out[ok] = (stock - bench)[ok]
    return out


def switcher_flags(history: pd.DataFrame, targets: pd.DataFrame, months: int = 36) -> pd.DataFrame:
    """S3: counts of the insider's open-market sells and buys in the `months` before the trade,
    using only trades filed before the target's filing."""
    n_sell = pd.Series(0, index=targets.index)
    n_buy = pd.Series(0, index=targets.index)
    window = np.timedelta64(int(months * 30.44), "D")
    groups = dict(tuple(history.groupby("insider_id")))
    for ins, t in targets.groupby("insider_id"):
        h = groups.get(ins)
        if h is None:
            continue
        ht, hf, hs = h["trade_date"].to_numpy(), h["filing_date"].to_numpy(), (h["side"] == "sell").to_numpy()
        for idx, tt, tf in zip(t.index, t["trade_date"].to_numpy(), t["filing_date"].to_numpy()):
            m = (hf < tf) & (ht < tt) & (ht >= tt - window)
            n_sell[idx], n_buy[idx] = int((m & hs).sum()), int((m & ~hs).sum())
    return pd.DataFrame({"prior36_sells": n_sell, "prior36_buys": n_buy})


def prior_same_buy(buys: pd.DataFrame, days: int = 30) -> pd.Series:
    """S4: the same insider filed a qualifying buy in the same company in the previous `days` days."""
    out = pd.Series(False, index=buys.index)
    for _, g in buys.groupby(["insider_id", "issuer_cik"]):
        if len(g) < 2:
            continue
        f = g["filing_date"].to_numpy()
        for idx, fd in zip(g.index, f):
            out[idx] = bool(((f < fd) & (f >= fd - np.timedelta64(days, "D"))).any())
    return out


def latest_before(left: pd.DataFrame, right: pd.DataFrame, left_on: str, right_on: str,
                  allow_exact: bool) -> pd.DataFrame:
    """As-of join per issuer (rows with a missing date are left unmatched)."""
    l = left[left[left_on].notna()].copy()
    l[left_on] = l[left_on].astype("datetime64[ns]")
    l = l.sort_values(left_on).reset_index()
    r = right.dropna(subset=[right_on]).copy()
    r[right_on] = r[right_on].astype("datetime64[ns]")
    r = r.sort_values(right_on)
    m = pd.merge_asof(l, r, left_on=left_on, right_on=right_on, by="issuer_cik", direction="backward",
                      allow_exact_matches=allow_exact)
    return m.set_index("index")


def main() -> None:
    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    df = pd.read_parquet(data / "analysis.parquet")
    flags = pd.read_parquet(data / "filing_flags.parquet").drop_duplicates("accession_number")
    sec = pd.read_parquet(data / "sec_filings.parquet")
    ex = pd.read_parquet(data / "exercises.parquet")

    # ---------------- populations
    buys = df[(df["side"] == "buy") & df["qualifies"]].copy()
    sells = df[(df["side"] == "sell") & df["qualifies"]].copy()
    ex = ex[~ex["form_type"].fillna("").str.upper().str.startswith("4/A")].copy()
    ex["side"] = "exercise"
    ex["filing_date"] = pd.to_datetime(ex["filing_date"], errors="coerce")
    ex["trade_date"] = pd.to_datetime(ex["trade_date"], errors="coerce")
    ex = ex.dropna(subset=["filing_date", "trade_date"])
    ex["role"] = [role_of(t, o, d, x) for t, o, d, x in
                  zip(ex["owner_title"], ex["is_officer"], ex["is_director"], ex["is_ten_percent_owner"])]
    ex["insider_id"] = ex["owner_cik"].where(ex["owner_cik"].notna() & (ex["owner_cik"] != ""), ex["owner_key"])
    ex["year"] = ex["filing_date"].dt.year
    # S9 (amendment 3d): "hold" = an exercise (M) with no open-market sale (non-derivative S) on the filing.
    # Shares withheld for the exercise price or taxes (F), and other non-S dispositions (e.g. D), are not sales.
    ex["hold"] = ex["n_s"] == 0
    common = KEYS + ["insider_id", "filing_date", "trade_date", "year", "role", "is_ten_percent_owner"]
    events = pd.concat([buys[common + ["last_tx_date", "adv_usd_20d"]], sells[common + ["adv_usd_20d"]],
                        ex[common + ["hold", "n_m", "n_s", "n_f"]]], ignore_index=True)
    events = events.merge(flags, on="accession_number", how="left")
    # S7/S8 as pre-registered: plan = mentioned in the text OR the 2023+ checkbox ticked
    has_flags = events["plan_text"].notna()
    events["plan_10b5_1"] = (events["plan_text"].fillna(False).astype(bool)
                             | events["plan_box"].fillna(False).astype(bool)).where(has_flags)
    print(f"[study3] {len(buys):,} buys, {len(sells):,} sells, {len(ex):,} option-exercise events")

    # ---------------- S3 switcher, S4 accumulation (buys)
    hist = df[~df["exclude_reason"].isin(["amendment", "duplicate"]) & df["trade_date"].notna()
              & df["filing_date"].notna()][["insider_id", "side", "trade_date", "filing_date"]]
    b = events["side"] == "buy"
    sw = switcher_flags(hist, events[b])
    events.loc[b, ["prior36_sells", "prior36_buys"]] = sw.to_numpy()
    span_days = (events["last_tx_date"] - events["trade_date"]).dt.days
    events["multi_day"] = span_days >= 1        # purchases on two or more different calendar days
    events.loc[b, "repeat_30d"] = prior_same_buy(events[b]).to_numpy()

    # ---------------- earnings releases (8-K item 2.02) and their 3-day reactions
    cal, iwm = load_benchmark(cfg, "IWM")
    ann = sec[sec["form"] == "8-K"].copy()
    ann["ann_day"] = announcement_days(cal, ann["acceptance_utc"])
    ann = ann.dropna(subset=["ann_day"]).sort_values("acceptance_utc").drop_duplicates(["issuer_cik", "ann_day"])
    prices = PriceIndex(price_paths(cfg)[0])
    ann["react3"] = np.nan
    for cik, pos in ann.groupby("issuer_cik").indices.items():
        dates, closes = prices.get(cik)
        ann.iloc[pos, ann.columns.get_loc("react3")] = reaction3(
            dates, closes, cal, iwm, ann["ann_day"].to_numpy()[pos].astype(D))
    ann["ann_day"] = pd.to_datetime(ann["ann_day"])

    # S5: officer/director qualifying buys filed in the 90 days before the release
    od = buys[buys["role"] != "ten_pct_owner"][["issuer_cik", "filing_date"]]
    allb = buys[["issuer_cik", "filing_date"]]
    for col, src in (("od_buy_90d", od), ("any_buy_90d", allb)):
        last = latest_before(ann[["issuer_cik", "ann_day"]], src.rename(columns={"filing_date": "buy_filed"}),
                             "ann_day", "buy_filed", allow_exact=False)
        gap = (last["ann_day"] - last["buy_filed"]).dt.days
        ann[col] = False
        ann.loc[last.index, col] = (gap <= 90).fillna(False).to_numpy()
    ann["year"] = ann["ann_day"].dt.year
    ann[["issuer_cik", "accession_number", "acceptance_utc", "ann_day", "react3", "od_buy_90d",
         "any_buy_90d", "year"]].to_parquet(data / "study3_announcements.parquet", index=False)
    print(f"[study3] {len(ann):,} earnings releases; 3-day reaction for {ann['react3'].notna().mean():.0%}")
    print("releases per year:", ann.groupby("year").size().to_dict())

    # S6: latest release on or before the trade date
    r = ann[["issuer_cik", "ann_day", "react3"]].rename(columns={"react3": "last_ann_react3"})
    last = latest_before(events.loc[b, ["issuer_cik", "trade_date"]], r, "trade_date", "ann_day", allow_exact=True)
    events.loc[last.index, "days_since_ann"] = (last["trade_date"] - last["ann_day"]).dt.days.to_numpy()
    events.loc[last.index, "last_ann_react3"] = last["last_ann_react3"].to_numpy()

    # S10: Schedule 13D on the company accepted in the 365 days before the filing date
    d13 = sec[sec["form"].str.contains("13D")][["issuer_cik", "acceptance_utc"]].copy()
    d13["d13_day"] = d13["acceptance_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    last = latest_before(events.loc[b, ["issuer_cik", "filing_date"]], d13[["issuer_cik", "d13_day"]],
                         "filing_date", "d13_day", allow_exact=False)
    events.loc[last.index, "days_since_13d"] = (last["filing_date"] - last["d13_day"]).dt.days.to_numpy()

    # S10b: a Schedule 13D on this company filed BY this buyer (alone or as a group member)
    events["days_since_own_13d"] = np.nan
    f13 = data / "filer_13d.parquet"
    if f13.exists():
        own = pd.read_parquet(f13)[["filer_cik", "accession_number"]].merge(
            sec[sec["form"].str.contains("13D")][["issuer_cik", "accession_number", "acceptance_utc"]],
            on="accession_number")
        own["d13_day"] = own["acceptance_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        own["key"] = own["issuer_cik"] + "|" + own["filer_cik"].astype(str)
        tb = events[b & (events["is_ten_percent_owner"] == 1)].copy()
        tb["key"] = tb["issuer_cik"] + "|" + pd.to_numeric(tb["insider_id"], errors="coerce").astype("Int64").astype(str)
        last = latest_before(tb[["key", "filing_date"]].rename(columns={"key": "issuer_cik"}),
                             own[["key", "d13_day"]].rename(columns={"key": "issuer_cik"}),
                             "filing_date", "d13_day", allow_exact=False)
        events.loc[last.index, "days_since_own_13d"] = (last["filing_date"] - last["d13_day"]).dt.days.to_numpy()
        print(f"[study3] 10%-holder buys with the buyer's own 13D on the company in the prior year: "
              f"{int(events['days_since_own_13d'].between(0, 365).sum()):,}")
    else:
        print("[study3] filer_13d.parquet not found; S10b skipped (run research.fetch_filer_13d)")

    # ---------------- event windows (factor BHAR etc.) for every event
    factors = pd.read_parquet(data / "factors.parquet")
    factors = factors.set_index(pd.DatetimeIndex(pd.to_datetime(factors["date"]).astype("datetime64[ns]")))
    bench = (cal, iwm)
    parts = []
    for cik, g in events.groupby("issuer_cik"):
        dates, closes = prices.get(cik)
        parts.append(issuer_windows(dates, closes, factors, bench, g[["trade_date", "filing_date"]]))
        # liquidity at entry for events that do not have it yet (option exercises), for the cost estimate
        miss = g.index[g["adv_usd_20d"].isna()]
        dv = prices.median_dollar_volume(cik)
        if len(miss) and dv is not None and len(dates):
            i = np.searchsorted(dates, g.loc[miss, "filing_date"].to_numpy().astype(D), side="right")
            ok = i < len(dates)
            events.loc[miss[ok], "adv_usd_20d"] = dv[i[ok]]
    events = events.join(pd.concat(parts))
    events.to_parquet(data / "study3_events.parquet", index=False)
    print(f"[study3] wrote {len(events):,} events; 60-day factor BHAR for "
          f"{events.groupby('side')['bhar_ff6_D60'].apply(lambda s: f'{s.notna().mean():.0%}').to_dict()}")
    print("plan flags (share of events):")
    print(events.groupby("side")[["plan_text", "plan_box", "plan_negated", "plan_10b5_1"]].mean().round(3).to_string())


if __name__ == "__main__":
    main()
