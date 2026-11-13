"""Print a few qualifying buys with every number needed to verify them by hand.

For each one, open the EDGAR link and a price chart and check:
  1. the filing date, trade date, insider and dollar amount match the Form 4;
  2. entry_date is the first trading day AFTER the filing date;
  3. exit is `horizon` trading days later;
  4. (exit price / entry price - 1) minus the same for SPY equals our excess.

    python -m research.sanity_check            # 10 random buys
    python -m research.sanity_check --n 5 --seed 3
"""
from __future__ import annotations

import argparse

import pandas as pd

from research.common import load_config, price_paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    df = pd.read_parquet(data / "analysis.parquet")
    prices_path, bench_path = price_paths(cfg)
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"])
    bench = bench[bench["symbol"] == bench["symbol"].value_counts().idxmax()].set_index("date")["adj_close"]

    h = cfg["horizons"][0]
    pool = df[(df["side"] == "buy") & df["qualifies"] & df[f"excess_{h}"].notna()]
    sample = pool.sample(min(args.n, len(pool)), random_state=args.seed)
    worst = 0.0
    for _, r in sample.iterrows():
        # Read only this issuer's rows (the full price table is too big to load on a small server).
        one = pd.read_parquet(prices_path, filters=[("issuer_cik", "==", r["issuer_cik"])])
        px = one.set_index(pd.to_datetime(one["date"]))["adj_close"].sort_index()
        # Independent recomputation, written the slow obvious way on purpose.
        after = px[px.index > r["filing_date"]] if cfg["entry"] == "next_day" else px[px.index >= r["filing_date"]]
        p0, d0 = after.iloc[0], after.index[0]
        p1, d1 = (after.iloc[h], after.index[h]) if len(after) > h else (after.iloc[-1], after.index[-1])
        b0, b1 = bench[:d0].iloc[-1], bench[:d1].iloc[-1]
        check = (p1 / p0 - 1) - (b1 / b0 - 1)
        worst = max(worst, abs(check - r[f"excess_{h}"]))
        acc = r["accession_number"]
        print(f"\n{r['ticker']}  {r['owner_name_display']}  ({r['role']})   status={r[f'status_{h}']}")
        print(f"  https://www.sec.gov/Archives/edgar/data/{int(r['issuer_cik'])}/{acc.replace('-', '')}/")
        print(f"  trade {r['trade_date']:%Y-%m-%d}   filed {r['filing_date']:%Y-%m-%d}   ${r['dollars_total']:,.0f}")
        print(f"  entry {d0:%Y-%m-%d} @ {p0:.4f}   exit(+{h}d) {d1:%Y-%m-%d} @ {p1:.4f}   stock {p1 / p0 - 1:+.2%}")
        print(f"  SPY   {b0:.2f} -> {b1:.2f}   {b1 / b0 - 1:+.2%}")
        print(f"  excess: ours {r[f'excess_{h}']:+.4f}   recomputed {check:+.4f}   production {r[f'prod_ex_{h}']:+.4f}"
              "   (production enters on the filing day, so a small difference is expected)")
    print(f"\nLargest difference between pipeline and independent recomputation: {worst:.2e}")
    if worst > 1e-9:
        raise SystemExit("MISMATCH: the pipeline and the independent recomputation disagree.")


if __name__ == "__main__":
    main()
