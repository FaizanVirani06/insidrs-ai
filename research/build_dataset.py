"""Step 2: turn the raw extracts into one clean analysis table.

One row per (insider event, side).  Everything here is recomputed from raw
prices under point-in-time rules; production's own outcome/stat columns are
carried along only for comparison.

    python -m research.build_dataset

Core functions are pure (numpy in, numpy out) so they can be unit-tested
without a database: see research/tests/test_build.py.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from research.common import load_config, price_paths

D = "datetime64[D]"


# --------------------------------------------------------------------------- #
# Forward returns
# --------------------------------------------------------------------------- #
def forward_returns(dates, closes, bench_dates, bench_closes, filing_dates, horizon, *,
                    entry="next_day", max_entry_gap_days=7, global_last=None, delist_gap_days=10,
                    suspect_up=1.5, suspect_down=-0.6):
    """Forward return of one issuer's stock for many filings at once.

    dates/closes        the issuer's daily adjusted closes, sorted by date
    bench_dates/closes  the benchmark (SPY) series
    filing_dates        when each filing became public
    horizon             holding period in trading days

    Returns a dict of arrays (one element per filing):
      entry_date, exit_date, ret, bench_ret, excess, suspect, status
    status is one of
      ok            full holding period observed
      delisted      series ended before the horizon AND long before the newest
                    price in the database -> exit at the last price (kept, not dropped)
      not_matured   series is still live but the horizon has not elapsed yet
      no_entry      no price shortly after the filing (no series / already delisted / gap)
    The benchmark is measured over the SAME calendar dates as the stock.
    """
    filing_dates = np.asarray(filing_dates, dtype=D)
    n = len(filing_dates)
    out = {
        "entry_date": np.full(n, np.datetime64("NaT", "D")),
        "exit_date": np.full(n, np.datetime64("NaT", "D")),
        "ret": np.full(n, np.nan), "bench_ret": np.full(n, np.nan), "excess": np.full(n, np.nan),
        "suspect": np.zeros(n, dtype=bool),
        "status": np.full(n, "no_entry", dtype=object),
    }
    m = len(dates)
    if m == 0 or n == 0:
        return out
    dates = np.asarray(dates, dtype=D)
    closes = np.asarray(closes, dtype=float)

    # Entry: first trading day strictly after the filing (or on/after for same_day).
    side = "right" if entry == "next_day" else "left"
    ei = np.searchsorted(dates, filing_dates, side=side)
    has_entry = ei < m
    ei_safe = np.minimum(ei, m - 1)
    gap = (dates[ei_safe] - filing_dates).astype(int)
    has_entry &= gap <= max_entry_gap_days

    xi = ei_safe + horizon
    full = has_entry & (xi < m)
    series_ended = (global_last is not None) and (
        (np.datetime64(global_last, "D") - dates[-1]).astype(int) > delist_gap_days)
    short = has_entry & ~full
    status = out["status"]
    status[full] = "ok"
    status[short] = "delisted" if series_ended else "not_matured"
    use = full | (short & series_ended)
    xi = np.minimum(xi, m - 1)

    ret = closes[xi] / closes[ei_safe] - 1.0

    # Benchmark at the last benchmark date on or before each stock date.
    bench_dates = np.asarray(bench_dates, dtype=D)
    bench_closes = np.asarray(bench_closes, dtype=float)
    b0 = np.searchsorted(bench_dates, dates[ei_safe], side="right") - 1
    b1 = np.searchsorted(bench_dates, dates[xi], side="right") - 1
    bench_ok = (b0 >= 0) & (b1 >= 0)
    bret = np.where(bench_ok, bench_closes[np.maximum(b1, 0)] / bench_closes[np.maximum(b0, 0)] - 1.0, np.nan)

    # Flag windows containing an implausible one-day move (split/adjustment break).
    daily = np.zeros(m)
    daily[1:] = closes[1:] / closes[:-1] - 1.0
    bad_cum = np.cumsum((daily > suspect_up) | (daily < suspect_down))
    suspect = (bad_cum[xi] - bad_cum[ei_safe]) > 0

    out["entry_date"][has_entry] = dates[ei_safe][has_entry]
    out["exit_date"][use] = dates[xi][use]
    out["ret"][use] = ret[use]
    out["bench_ret"][use] = bret[use]
    out["excess"][use] = (ret - bret)[use]
    out["suspect"][use] = suspect[use]
    return out


# --------------------------------------------------------------------------- #
# Point-in-time features
# --------------------------------------------------------------------------- #
def prior_track_record(owner, filing_date, exit_date, excess):
    """Each trade's track record from the SAME insider's EARLIER trades only.

    A past trade counts only if its holding period had already finished
    (exit_date < this filing_date): on the filing date nobody could have known
    the outcome of a trade that was still open.

    Returns (prior_n, prior_wins, prior_sum_excess) arrays aligned to the input.
    """
    owner = np.asarray(owner)
    fd = np.asarray(filing_date, dtype=D)
    xd = np.asarray(exit_date, dtype=D)
    ex = np.asarray(excess, dtype=float)
    n = len(owner)
    prior_n = np.zeros(n, dtype=int)
    prior_w = np.zeros(n, dtype=int)
    prior_s = np.zeros(n)
    order = np.argsort(owner, kind="stable")
    bounds = np.flatnonzero(np.r_[True, owner[order][1:] != owner[order][:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        idx = order[a:b]
        done = idx[~np.isnan(ex[idx]) & ~np.isnat(xd[idx])]
        if len(done) == 0:
            continue
        done = done[np.argsort(xd[done], kind="stable")]
        cw = np.r_[0, np.cumsum(ex[done] > 0)]
        cs = np.r_[0.0, np.cumsum(ex[done])]
        k = np.searchsorted(xd[done], fd[idx], side="left")   # exits strictly before filing
        prior_n[idx], prior_w[idx], prior_s[idx] = k, cw[k], cs[k]
    return prior_n, prior_w, prior_s


def cluster_pit(issuer, owner, filing_date, window_days=14):
    """Number of OTHER insiders at the same company whose trade (same side) was
    filed in the previous `window_days` days, up to and including this filing date.

    Unlike production's cluster flag this never looks at later filings.
    """
    issuer = np.asarray(issuer)
    owner = np.asarray(owner)
    fd = np.asarray(filing_date, dtype=D)
    out = np.zeros(len(issuer), dtype=int)
    order = np.lexsort((fd, issuer))
    bounds = np.flatnonzero(np.r_[True, issuer[order][1:] != issuer[order][:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        idx = order[a:b]
        if len(idx) < 2:
            continue
        d, o = fd[idx], owner[idx]
        lo = np.searchsorted(d, d - np.timedelta64(window_days, "D"), side="left")
        hi = np.searchsorted(d, d, side="right")
        for j in range(len(idx)):
            others = set(o[lo[j]:hi[j]])
            others.discard(o[j])
            out[idx[j]] = len(others)
    return out


_CEO = re.compile(r"\b(ceo|chief executive)\b", re.I)
_CFO = re.compile(r"\b(cfo|chief financial)\b", re.I)


def role_of(title, is_officer, is_director, is_ten) -> str:
    t = title if isinstance(title, str) else ""
    if _CEO.search(t):
        return "ceo"
    if _CFO.search(t):
        return "cfo"
    if is_officer == 1:
        return "other_officer"
    if is_director == 1:
        return "director"
    if is_ten == 1:
        return "ten_pct_owner"      # 10% holder with no officer/director role: mostly funds
    return "other"


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
class PriceIndex:
    """All issuers' price series in three flat arrays (small enough for a 4 GB server).

    get(cik) returns that issuer's (dates, closes), or empty arrays if it has none.
    """

    def __init__(self, path):
        t = pq.read_table(path, read_dictionary=["issuer_cik"])
        cik = t["issuer_cik"].combine_chunks()
        codes = cik.indices.to_numpy(zero_copy_only=False).astype(np.int32)
        names = cik.dictionary.to_pylist()
        days = t["date"].combine_chunks().cast("int32").to_numpy(zero_copy_only=False)  # days since 1970
        closes = t["adj_close"].combine_chunks().to_numpy(zero_copy_only=False)
        del t, cik
        # The extract is written sorted by (issuer, date); only re-sort if it is not.
        same = codes[1:] == codes[:-1]
        if not (np.all(codes[1:] >= codes[:-1]) and np.all(days[1:][same] > days[:-1][same])):
            order = np.lexsort((days, codes))
            codes, days, closes = codes[order], days[order], closes[order]
        bounds = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1], True])
        self._days, self._closes = days, closes
        self._span = {names[codes[a]]: (a, b) for a, b in zip(bounds[:-1], bounds[1:])}
        self.global_last = days.max().astype(D)

    def __len__(self):
        return len(self._span)

    def get(self, cik):
        span = self._span.get(cik)
        if span is None:
            return np.array([], dtype=D), np.array([])
        a, b = span
        return self._days[a:b].astype(D), self._closes[a:b]


def stack_sides(ev: pd.DataFrame) -> pd.DataFrame:
    """One row per (event, side). An event with both a buy and a sell gives two rows."""
    common = ["issuer_cik", "owner_key", "accession_number", "ticker", "filing_date", "form_type",
              "owner_cik", "owner_name_display", "owner_title", "is_officer", "is_director",
              "is_ten_percent_owner", "non_open_market_row_count", "derivative_row_count",
              "trend_ret_20d", "trend_ret_60d", "trend_dist_52w_high", "trend_dist_52w_low",
              "trend_above_sma_50", "trend_above_sma_200", "market_cap", "market_cap_date",
              "ai_computed_at", "sector", "has_buy", "has_sell"]
    parts = []
    for side in ("buy", "sell"):
        s = ev.loc[ev[f"has_{side}"] == 1, common].copy()
        src = ev.loc[s.index]
        s["side"] = side
        for col in ("trade_date", "shares_total", "dollars_total", "vwap_price",
                    "shares_owned_following", "pct_holdings_change"):
            s[col] = src[f"{side}_{col}"].to_numpy()
        s["prod_cluster_flag"] = src[f"prod_cluster_flag_{side}"].to_numpy()
        for h in (60, 180):
            s[f"prod_ex_{h}"] = src[f"prod_{side}_ex_{h}"].to_numpy()
        parts.append(s)
    return pd.concat(parts, ignore_index=True)


def attach_ratings(df: pd.DataFrame, ratings: pd.DataFrame, rcfg: dict) -> pd.DataFrame:
    """Join the FIRST rating each event received and classify it live vs backfill."""
    keys = ["issuer_cik", "owner_key", "accession_number"]
    r = ratings.sort_values("ai_output_id")
    first = r.groupby(keys, as_index=False).first()
    first["n_ratings"] = r.groupby(keys).size().to_numpy()
    df = df.merge(first, on=keys, how="left")
    buy = df["side"] == "buy"
    df["rating"] = np.where(buy, df["buy_rating"], df["sell_rating"])
    df["baseline_rating"] = np.where(buy, df["baseline_buy"], df["baseline_sell"])
    df["rating_minus_baseline"] = df["rating"] - df["baseline_rating"]
    # The model saw this insider's stored win rate. For a backfilled filing that
    # stat can include the filing's own outcome, i.e. the answer.
    df["shown_stats_n_60"] = np.where(buy, df["shown_buy_n_60"], df["shown_sell_n_60"])

    fd = pd.to_datetime(df["filing_date"])
    def lag(col):
        ts = pd.to_datetime(df[col].astype("string").str.slice(0, 10), errors="coerce")
        return (ts - fd).dt.days
    df["lag_model_clock"] = lag("model_generated_at")     # written by the model: may be wrong
    df["lag_input_clock"] = lag("input_mcap_ts")          # server time, lower bound on rating time
    df["lag_server_clock"] = lag("ai_computed_at")        # server time of the LATEST rating

    # Best clock for "when was this rated": the server's, falling back to the model's.
    # (They agree within a day for ~99% of ratings; only 15 events were ever re-rated.)
    lag_days = df["lag_server_clock"].fillna(df["lag_model_clock"])
    df["rating_lag_days"] = lag_days
    # live      rated within a few days of the filing: a genuine forecast
    # late      rated weeks later: part of the outcome was already observable
    # backfill  rated after the 60-day outcome was known; the model was also shown
    #           this insider's stored win rate, which can contain the answer
    cls = np.where(df["rating"].isna(), "unrated",
          np.where(lag_days.between(0, rcfg["live_max_lag_days"]), "live",
          np.where(lag_days > rcfg["backfill_min_lag_days"], "backfill", "late")))
    # Filings from before the model's knowledge cutoff may be in its training data.
    df["in_model_training_window"] = fd <= pd.Timestamp(rcfg["model_knowledge_cutoff"])
    df["rating_class"] = cls
    return df.drop(columns=["buy_rating", "sell_rating", "baseline_buy", "baseline_sell",
                            "shown_buy_n_60", "shown_sell_n_60", "shown_buy_win_60", "shown_buy_n_180"])


def build(events: pd.DataFrame, ratings: pd.DataFrame, price_index, global_last,
          bench_dates, bench_closes, cfg: dict) -> pd.DataFrame:
    df = stack_sides(events)
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce").dt.normalize()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.normalize()
    fd = df["filing_date"].to_numpy().astype(D)

    # ---- forward returns, issuer by issuer --------------------------------
    horizons = cfg["horizons"]
    cols = {}
    for h in horizons:
        cols[h] = {
            "exit_date": np.full(len(df), np.datetime64("NaT", "D")),
            "ret": np.full(len(df), np.nan), "bench_ret": np.full(len(df), np.nan),
            "excess": np.full(len(df), np.nan), "suspect": np.zeros(len(df), dtype=bool),
            "status": np.full(len(df), "no_entry", dtype=object),
        }
    entry_date = np.full(len(df), np.datetime64("NaT", "D"))
    entry_px = np.full(len(df), np.nan)
    mcap_px = np.full(len(df), np.nan)
    mcap_date = pd.to_datetime(df["market_cap_date"], errors="coerce").to_numpy().astype(D)
    for cik, pos in df.groupby("issuer_cik", sort=False).indices.items():
        dates, closes = price_index.get(cik)
        for h in horizons:
            r = forward_returns(dates, closes, bench_dates, bench_closes, fd[pos], h,
                                entry=cfg["entry"], max_entry_gap_days=cfg["max_entry_gap_days"],
                                global_last=global_last, delist_gap_days=cfg["delist_gap_days"],
                                suspect_up=cfg["suspect_daily_up"], suspect_down=cfg["suspect_daily_down"])
            for k in cols[h]:
                cols[h][k][pos] = r[k]
        entry_date[pos] = r["entry_date"]
        if len(dates):
            ok = ~np.isnat(r["entry_date"])
            i = np.searchsorted(dates, r["entry_date"][ok])
            entry_px[pos[ok]] = closes[i]
            # price on the day the market-cap snapshot was taken (for the rescale below)
            j = np.searchsorted(dates, mcap_date[pos], side="right") - 1
            good = (j >= 0) & ~np.isnat(mcap_date[pos])
            mcap_px[pos[good]] = closes[j[good]]
    df["entry_date"] = entry_date
    df["entry_px_adj"] = entry_px
    for h in horizons:
        for k, v in cols[h].items():
            df[f"{k}_{h}"] = v
        df[f"win_{h}"] = np.where(df[f"excess_{h}"].isna(), np.nan, (df[f"excess_{h}"] > 0).astype(float))

    # ---- point-in-time features --------------------------------------------
    df["year"] = df["filing_date"].dt.year
    df["filing_delay_days"] = (df["filing_date"] - df["trade_date"]).dt.days
    df["role"] = [role_of(t, o, d, x) for t, o, d, x in
                  zip(df["owner_title"], df["is_officer"], df["is_director"], df["is_ten_percent_owner"])]
    df["log_dollars"] = np.log10(df["dollars_total"].where(df["dollars_total"] > 0))
    # Stored market cap is TODAY's value. Rescale by the price change since the
    # filing to approximate market cap at the time (ignores share-count changes).
    df["mcap_pit_approx"] = df["market_cap"] * df["entry_px_adj"] / mcap_px
    df["mcap_bucket_pit"] = pd.cut(df["mcap_pit_approx"], [0, 3e8, 2e9, 1e10, np.inf],
                                   labels=["micro", "small", "mid", "large"]).astype("string")
    df["dollars_pct_mcap"] = df["dollars_total"] / df["mcap_pit_approx"]

    # Follow a person across companies when the SEC gave us their CIK.
    df["insider_id"] = df["owner_cik"].where(df["owner_cik"].notna() & (df["owner_cik"] != ""), df["owner_key"])

    df["is_amendment"] = df["form_type"].fillna("").str.upper().str.startswith("4/A")
    df = df.sort_values(["filing_date", "accession_number"], kind="stable").reset_index(drop=True)
    df["is_duplicate"] = df.duplicated(["issuer_cik", "owner_key", "side", "trade_date", "shares_total"], keep="first")

    f = cfg["filters"]
    reason = np.full(len(df), "", dtype=object)
    def mark(mask, text):
        reason[(reason == "") & mask.to_numpy()] = text
    mark(df["is_amendment"] & f["exclude_amendments"], "amendment")
    mark(df["is_duplicate"] & f["exclude_duplicates"], "duplicate")
    mark(df["filing_date"].isna() | df["trade_date"].isna(), "bad_date")
    mark(~(df["dollars_total"] >= f["min_dollars"]), "small_or_unpriced")
    mark(df["dollars_total"] > f["max_dollars"], "implausible_dollars")
    mark(df["vwap_price"] < f["min_trade_price"], "penny_stock")
    mark(df["vwap_price"] > f["max_trade_price"], "implausible_price")
    mark(df["filing_delay_days"] < 0, "filed_before_trade")
    mark(df["filing_delay_days"] > f["max_filing_delay_days"], "stale_filing")
    mark(df["entry_date"].isna(), "no_entry_price")
    if f["exclude_suspect_prices"]:
        mark(df[[f"suspect_{h}" for h in horizons]].any(axis=1), "suspect_price")
    df["exclude_reason"] = reason
    df["qualifies"] = reason == ""

    # Track records and clusters are computed on qualifying trades only, per side.
    for side in ("buy", "sell"):
        m = ((df["side"] == side) & df["qualifies"]).to_numpy()
        sub = df.loc[m]
        df.loc[m, "cluster_n_other"] = cluster_pit(sub["issuer_cik"].to_numpy(), sub["insider_id"].to_numpy(),
                                                   sub["filing_date"].to_numpy(), cfg["cluster_window_days"])
        for h in horizons:
            n, w, s = prior_track_record(sub["insider_id"].to_numpy(), sub["filing_date"].to_numpy(),
                                         sub[f"exit_date_{h}"].to_numpy(), sub[f"excess_{h}"].to_numpy())
            df.loc[m, f"prior_n_{h}"], df.loc[m, f"prior_wins_{h}"], df.loc[m, f"prior_sum_ex_{h}"] = n, w, s

    # Market regime: SPY's return over the ~6 months before entry.
    bi = np.searchsorted(bench_dates, df["entry_date"].to_numpy().astype(D), side="right") - 1
    ok = (bi >= 126) & df["entry_date"].notna().to_numpy()
    spy6 = np.full(len(df), np.nan)
    spy6[ok] = bench_closes[bi[ok]] / bench_closes[bi[ok] - 126] - 1.0
    df["spy_ret_126d"] = spy6

    df = attach_ratings(df, ratings, cfg["ratings"])
    for c in ["entry_date"] + [f"exit_date_{h}" for h in horizons]:
        df[c] = pd.to_datetime(df[c])
    return df


def build_report(df: pd.DataFrame, horizons) -> pd.DataFrame:
    """Counts that show where rows are lost, by side and year."""
    g = df.groupby(["side", "year"])
    rep = pd.DataFrame({"events": g.size(), "qualifying": g["qualifies"].sum()})
    q = df[df["qualifies"]]
    for h in horizons:
        st = q.groupby(["side", "year"])[f"status_{h}"].value_counts().unstack(fill_value=0)
        rep = rep.join(st.add_prefix(f"h{h}_"))
    return rep.fillna(0).astype(int).reset_index()


def main() -> None:
    cfg = load_config()
    data, out = cfg["paths"]["data_dir"], cfg["paths"]["output_dir"]
    events = pd.read_parquet(data / "events.parquet")
    ratings = pd.read_parquet(data / "ratings.parquet")
    prices_path, bench_path = price_paths(cfg)
    bench = pd.read_parquet(bench_path)
    sym = bench["symbol"].value_counts().idxmax()
    bench = bench[bench["symbol"] == sym].sort_values("date")
    price_index = PriceIndex(prices_path)
    global_last = price_index.global_last
    print(f"[build] prices from {prices_path.name}; {len(events):,} events, {len(price_index):,} price series, "
          f"benchmark {sym}, newest price {global_last}")

    df = build(events, ratings, price_index, global_last,
               bench["date"].to_numpy().astype(D), bench["adj_close"].to_numpy(), cfg)
    df.to_parquet(data / "analysis.parquet", index=False)

    (out / "tables").mkdir(exist_ok=True)
    rep = build_report(df, cfg["horizons"])
    rep.to_csv(out / "tables" / "build_report.csv", index=False)
    excl = df.groupby(["side", "exclude_reason"]).size().rename("n").reset_index()
    excl.to_csv(out / "tables" / "exclusions.csv", index=False)
    print(f"[build] analysis table: {len(df):,} rows, {int(df['qualifies'].sum()):,} qualifying")
    print(excl.to_string(index=False))
    print(rep.groupby("side").sum(numeric_only=True).drop(columns="year").T.to_string())
    print(df.loc[df["rating"].notna()].groupby(["side", "rating_class"]).size().to_string())


if __name__ == "__main__":
    main()
