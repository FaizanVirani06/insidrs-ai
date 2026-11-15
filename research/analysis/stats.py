"""Small statistics helpers shared by the analysis scripts.

Design choices (explained once here):

* Insider trades are not independent: many are filed in the same weeks, in the
  same market, with overlapping 60/180-day windows.  Treating 70,000 trades as
  70,000 independent observations makes everything look "significant".
  So every confidence interval here comes from a CLUSTER bootstrap: we resample
  whole calendar months of filings, not individual trades.
* Returns have wild tails (and some bad prices), so means are computed on
  winsorized returns (extremes clipped to the 1st/99th percentile) and always
  reported next to the median and the hit rate.
* With many buckets and features some will look good by luck, so p-values are
  adjusted with Benjamini-Hochberg (false discovery rate).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def winsorize(x: pd.Series, p: float = 0.01) -> pd.Series:
    lo, hi = x.quantile(p), x.quantile(1 - p)
    return x.clip(lo, hi)


def normal_p(z: float) -> float:
    """Two-sided p-value for a z statistic."""
    return float("nan") if not np.isfinite(z) else math.erfc(abs(z) / math.sqrt(2))


def bh_adjust(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values (NaNs are left alone)."""
    out = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    if m == 0:
        return out
    adj = (v * m / np.arange(1, m + 1)).iloc[::-1].cummin().iloc[::-1].clip(upper=1.0)
    out.loc[adj.index] = adj
    return out


def cluster_bootstrap(values: np.ndarray, clusters: np.ndarray, stat, n_boot: int = 1000, seed: int = 0):
    """Bootstrap distribution of stat(values), resampling whole clusters.

    Returns (se, ci_low, ci_high, n_clusters). With fewer than ~10 clusters the
    interval is only a rough guide; n_clusters is returned so tables can show it.
    """
    rng = np.random.default_rng(seed)
    order = np.argsort(clusters, kind="stable")
    v, c = values[order], clusters[order]
    bounds = np.flatnonzero(np.r_[True, c[1:] != c[:-1], True])
    groups = [v[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
    k = len(groups)
    if k < 2:
        return np.nan, np.nan, np.nan, k
    draws = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(k, size=k)
        draws[i] = stat(np.concatenate([groups[j] for j in pick]))
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return float(np.nanstd(draws, ddof=1)), float(lo), float(hi), k


MIN_N_FOR_INFERENCE = 30       # below this, show the numbers but no interval or p-value


def summarize(df: pd.DataFrame, col: str, cluster_col: str = "month", n_boot: int = 1000) -> dict:
    """One row of a results table for the returns in df[col] (already winsorized)."""
    x = df[col].to_numpy(float)
    cl = df[cluster_col].to_numpy()
    n = len(x)
    if n == 0:
        return {"n": 0}
    if n < MIN_N_FOR_INFERENCE:
        return {"n": n, "months": len(set(cl)), "mean": float(x.mean()), "median": float(np.median(x)),
                "hit_rate": float((x > 0).mean())}
    se, lo, hi, k = cluster_bootstrap(x, cl, np.mean, n_boot)
    _, hlo, hhi, _ = cluster_bootstrap((x > 0).astype(float), cl, np.mean, n_boot)
    mean = float(x.mean())
    return {
        "n": n, "months": k,
        "mean": mean, "mean_lo": lo, "mean_hi": hi,
        "median": float(np.median(x)),
        "hit_rate": float((x > 0).mean()), "hit_lo": hlo, "hit_hi": hhi,
        "p10": float(np.percentile(x, 10)), "p25": float(np.percentile(x, 25)),
        "p75": float(np.percentile(x, 75)), "p90": float(np.percentile(x, 90)),
        "p_mean_ne_0": normal_p(mean / se) if se and se > 0 else np.nan,
    }


def spearman(a: pd.Series, b: pd.Series) -> float:
    ok = a.notna() & b.notna()
    if ok.sum() < 3 or a[ok].nunique() < 2 or b[ok].nunique() < 2:
        return np.nan
    return float(a[ok].rank().corr(b[ok].rank()))


def information_coefficient(df: pd.DataFrame, signal: str, ret: str, period: str = "month", min_n: int = 20) -> dict:
    """Rank correlation between a signal and the forward return.

    pooled        one Spearman correlation over all trades
    within-month  the same after subtracting each month's average return, so a
                  good or bad market month cannot create a fake correlation
    monthly       a separate correlation per month; the mean and its t-statistic
                  across months is the standard "IC" a quant will ask for.
                  (Monthly ICs of multi-month returns overlap, so the t-stat is
                  somewhat optimistic; n_months tells you how much to trust it.)
    """
    d = df[[signal, ret, period]].dropna()
    if len(d) < min_n:
        return {"n": len(d)}
    demeaned = d[ret] - d.groupby(period)[ret].transform("mean")
    monthly = d.groupby(period).apply(
        lambda g: spearman(g[signal], g[ret]) if len(g) >= min_n else np.nan, include_groups=False).dropna()
    m = len(monthly)
    t = monthly.mean() / (monthly.std(ddof=1) / math.sqrt(m)) if m >= 3 and monthly.std(ddof=1) > 0 else np.nan
    return {
        "n": len(d), "ic_pooled": spearman(d[signal], d[ret]), "ic_within_month": spearman(d[signal], demeaned),
        "ic_monthly_mean": float(monthly.mean()) if m else np.nan, "ic_monthly_t": t, "n_months": m,
        "share_months_positive": float((monthly > 0).mean()) if m else np.nan,
    }


def spread(df: pd.DataFrame, ret: str, top: pd.Series, bottom: pd.Series, cluster_col: str = "month",
           n_boot: int = 1000) -> dict:
    """Mean return of `top` rows minus `bottom` rows, with a cluster-bootstrap interval."""
    sub = df[top | bottom]
    flag = top[sub.index].to_numpy()
    x = sub[ret].to_numpy(float)
    if flag.sum() < MIN_N_FOR_INFERENCE or (~flag).sum() < MIN_N_FOR_INFERENCE:
        return {"n_top": int(flag.sum()), "n_bottom": int((~flag).sum())}
    packed = np.column_stack([x, flag.astype(float)])

    def diff(rows):
        f = rows[:, 1] > 0.5
        return rows[f, 0].mean() - rows[~f, 0].mean() if f.any() and (~f).any() else np.nan

    se, lo, hi, k = cluster_bootstrap(packed, sub[cluster_col].to_numpy(), diff, n_boot)
    d = float(diff(packed))
    return {"n_top": int(flag.sum()), "n_bottom": int((~flag).sum()), "spread": d, "lo": lo, "hi": hi,
            "months": k, "p": normal_p(d / se) if se and se > 0 else np.nan}
