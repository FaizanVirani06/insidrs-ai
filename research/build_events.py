"""Event-time returns and pre-registered features for qualifying insider buys.

    python -m research.build_events

Definitions are fixed in research/PREREGISTRATION.md.  Reads analysis.parquet,
the price download, IWM, factors.parquet and shares.parquet; writes
data/events_v2.parquet (one row per qualifying buy).

Window notation: (a, b] on the stock's trading-day index, i.e. the return from
the close of day a to the close of day b.
    pre20  (trade - 20, trade]          the "dip"
    B      (trade, day before filing]   only the insider could earn this
    C      (day before filing, entry]   disclosure reaction
    D{h}   (entry, entry + h]           tradeable; entry = first trading day after filing
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.build_dataset import D, PriceIndex
from research.common import load_benchmark, load_config, price_paths

KEYS = ["issuer_cik", "owner_key", "accession_number", "side"]
FACTORS = ["mkt_rf", "smb", "hml", "rmw", "cma", "mom"]
WINDOWS = ["pre20", "B", "C", "D5", "D20", "D60", "D180"]
EST_LEN, EST_GAP, EST_MIN = 250, 20, 120


def window_bounds(it, ipre, ient, m):
    """(start, end) close indices for every window, or None if it does not fit the series."""
    w = {"pre20": (it - 20, it) if it >= 20 else None,
         "B": (it, max(ipre, it)),                       # zero-length when filed the day of / after the trade
         "C": (ipre, ient) if ipre >= 0 else None}
    for h in (5, 20, 60, 180):
        w[f"D{h}"] = (ient, ient + h) if ient + h < m else None
    return w


def issuer_windows(dates, closes, factors, bench, events):
    """CARs and benchmark excess returns for one issuer's events.

    events: DataFrame with trade_date, filing_date (datetime64). Returns a DataFrame aligned to it.
    """
    n, m = len(events), len(dates)
    out = {f"{k}_{w}": np.full(n, np.nan) for k in ("car_ff6", "car_mkt", "bhar_ff6", "ex_iwm") for w in WINDOWS}
    out["betas_ok"] = np.zeros(n, dtype=bool)
    out["vol_est"] = np.full(n, np.nan)          # daily return volatility in the beta-estimation window
    if m < 30:
        return pd.DataFrame(out, index=events.index)

    f = factors.reindex(pd.DatetimeIndex(dates.astype("datetime64[ns]")))
    r = np.r_[np.nan, closes[1:] / closes[:-1] - 1.0]
    rf = f["rf"].to_numpy()
    y = r - rf
    X = f[FACTORS].to_numpy()
    valid = np.isfinite(y) & np.isfinite(X).all(1)
    valid[0] = False
    y0, X0 = np.where(valid, y, 0.0), np.where(valid[:, None], X, 0.0)
    cy, cX = np.r_[0.0, np.cumsum(y0)], np.vstack([np.zeros(6), np.cumsum(X0, 0)])
    cbad = np.r_[0, np.cumsum(~valid)]

    bd, bc = bench
    bidx = np.searchsorted(bd, dates, side="right") - 1
    bclose = np.where(bidx >= 0, bc[np.maximum(bidx, 0)], np.nan)

    td = events["trade_date"].to_numpy().astype(D)
    fd = events["filing_date"].to_numpy().astype(D)
    it = np.searchsorted(dates, td, side="left")
    ient = np.searchsorted(dates, fd, side="right")
    ipre = np.searchsorted(dates, fd, side="left") - 1
    beta_cache = {}
    for k in range(n):
        a, e, p = it[k], ient[k], ipre[k]
        if a >= m or e >= m or (dates[a] - td[k]).astype(int) > 7 or (dates[e] - fd[k]).astype(int) > 7:
            continue
        if a not in beta_cache:
            lo, hi = max(1, a - EST_LEN - EST_GAP + 1), a - EST_GAP + 1
            sel = np.arange(lo, hi) if hi > lo else np.array([], dtype=int)
            sel = sel[valid[sel]] if len(sel) else sel
            if len(sel) >= EST_MIN:
                A = np.column_stack([np.ones(len(sel)), X[sel]])
                b_ff = np.linalg.lstsq(A, y[sel], rcond=None)[0][1:]
                b_m = np.linalg.lstsq(A[:, :2], y[sel], rcond=None)[0][1]
                beta_cache[a] = (b_ff, b_m, float(np.std(y[sel], ddof=1)))
            else:
                beta_cache[a] = None
        betas = beta_cache[a]
        out["betas_ok"][k] = betas is not None
        if betas is not None:
            out["vol_est"][k] = betas[2]
        for w, bnd in window_bounds(a, p, e, m).items():
            if bnd is None:
                continue
            s, t = bnd
            out[f"ex_iwm_{w}"][k] = closes[t] / closes[s] - bclose[t] / bclose[s]
            if betas is None or cbad[t + 1] - cbad[s + 1] > 0:      # any day without factor data -> no CAR
                continue
            sy, sX = cy[t + 1] - cy[s + 1], cX[t + 1] - cX[s + 1]
            out[f"car_ff6_{w}"][k] = sy - sX @ betas[0]
            out[f"car_mkt_{w}"][k] = sy - sX[0] * betas[1]
            # Buy-and-hold version: compound the stock and the factor-predicted return separately.
            # (Summing daily returns, as a CAR does, overstates long-horizon returns of volatile stocks.)
            seg = slice(s + 1, t + 1)
            out[f"bhar_ff6_{w}"][k] = closes[t] / closes[s] - np.prod(1 + rf[seg] + X[seg] @ betas[0])
    return pd.DataFrame(out, index=events.index)


def classify_traders(history: pd.DataFrame, targets: pd.DataFrame, infrequent_months: int) -> pd.DataFrame:
    """Trader type and infrequent-buyer flag for each target buy (definitions in PREREGISTRATION.md §5).

    history: every open-market trade (both sides): insider_id, side, trade_date, filing_date.
    Only trades FILED BEFORE the target's filing date are used.
    """
    trader_type = pd.Series("insufficient history", index=targets.index, dtype=object)
    prior_buy = pd.Series(False, index=targets.index)
    window = np.timedelta64(int(infrequent_months * 30.44), "D")
    groups = dict(tuple(history.groupby("insider_id")))
    for ins, t in targets.groupby("insider_id"):
        h = groups.get(ins)
        if h is None:
            continue
        hy, hm = h["trade_date"].dt.year.to_numpy(), h["trade_date"].dt.month.to_numpy()
        hf, ht = h["filing_date"].to_numpy(), h["trade_date"].to_numpy()
        hbuy = (h["side"] == "buy").to_numpy()
        for idx, ty, tt, tf in zip(t.index, t["trade_date"].dt.year, t["trade_date"].to_numpy(), t["filing_date"].to_numpy()):
            known = hf < tf
            months = [set(hm[known & (hy == ty - k)]) for k in (1, 2, 3)]
            if all(months):
                trader_type[idx] = "routine" if months[0] & months[1] & months[2] else "opportunistic"
            prior_buy[idx] = bool((known & hbuy & (ht < tt) & (ht >= tt - window)).any())
    return pd.DataFrame({"trader_type": trader_type, "bought_in_prior_window": prior_buy})


def main() -> None:
    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    pre = cfg["preregistered"]
    df = pd.read_parquet(data / "analysis.parquet")
    targets = df[(df["side"] == "buy") & df["qualifies"]].copy()
    print(f"[events] {len(targets):,} qualifying buys")

    # ---- trader type and infrequent-buyer flag (history = all open-market trades, both sides)
    hist = df[~df["exclude_reason"].isin(["amendment", "duplicate"]) & df["trade_date"].notna()
              & df["filing_date"].notna()][["insider_id", "side", "trade_date", "filing_date"]]
    feats = classify_traders(hist, targets, pre["infrequent_months"])

    # ---- post-report proxy: days since the latest 10-Q/10-K filed before the trade
    shares_path = data / "shares.parquet"
    feats["post_report_days"] = np.nan
    if shares_path.exists():
        sh = pd.read_parquet(shares_path, columns=["issuer_cik", "filed"]).drop_duplicates().sort_values("filed")
        sh["filed"] = sh["filed"].astype(targets["trade_date"].dtype)
        left = targets[["issuer_cik", "trade_date"]].dropna().sort_values("trade_date")
        m = pd.merge_asof(left.reset_index(), sh, left_on="trade_date", right_on="filed", by="issuer_cik",
                          direction="backward", allow_exact_matches=False).set_index("index")
        feats.loc[m.index, "post_report_days"] = (m["trade_date"] - m["filed"]).dt.days

    # ---- event-time returns
    factors = pd.read_parquet(data / "factors.parquet")
    factors = factors.set_index(pd.DatetimeIndex(pd.to_datetime(factors["date"]).astype("datetime64[ns]")))
    bench = load_benchmark(cfg, cfg["small_cap_benchmark"])
    if bench is None:
        raise SystemExit("IWM benchmark missing; run research.fetch_prices")
    prices = PriceIndex(price_paths(cfg)[0])
    parts = []
    for cik, ev in targets.groupby("issuer_cik"):
        dates, closes = prices.get(cik)
        parts.append(issuer_windows(dates, closes, factors, bench, ev[["trade_date", "filing_date"]]))
    windows = pd.concat(parts)

    out = targets[KEYS].join(feats).join(windows)
    out["dip_ex20"] = out["ex_iwm_pre20"]
    out.to_parquet(data / "events_v2.parquet", index=False)
    print(f"[events] wrote {len(out):,} rows; betas estimated for {out['betas_ok'].mean():.0%}; "
          f"60-day factor CAR for {out['car_ff6_D60'].notna().mean():.0%}")
    print(out["trader_type"].value_counts().to_string())
    print(f"factor data through {factors.index.max().date()}")


if __name__ == "__main__":
    main()
