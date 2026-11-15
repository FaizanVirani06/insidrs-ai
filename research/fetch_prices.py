"""Download daily prices from Yahoo Finance into the research folder.

Why: the production price table stops in May 2026, has ~13,500 bad one-day
jumps, and stores adjusted close only.  This fetches one consistent history
(adjusted close, raw close, volume) for every company in the extract, plus SPY.
Nothing is written to the production database.

    python -m research.fetch_prices            # resumable: rerun to continue
    python -m research.fetch_prices --refresh  # start over (use for the scheduled job)

Outputs in data_dir:
    yf_parts/part_*.parquet   one file per batch of tickers
    yf_state.json             which tickers succeeded / failed
    prices_yf.parquet         issuer_cik, date, adj_close, close, volume
    benchmark_yf.parquet      symbol, date, adj_close

Known limits of this source (state them in the write-up):
  - no delisted companies;  - unofficial API, can rate-limit or change;
  - licence is for personal/research use, not for a commercial product.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research.common import load_config

BENCH = "SPY"


def yahoo_symbol(ticker: str) -> str:
    """SEC/EODHD write share classes as BRK.B; Yahoo writes BRK-B."""
    # Some filings report several tickers in one field ("UHAL UHALB", "WLY, WLYB",
    # "Z AND ZG") or a placeholder ("[NONE]"): keep the first real token.
    tokens = [t for t in re.split(r"[\s,;]+", ticker.strip().upper()) if t]
    first = re.sub(r"[^A-Z0-9./-]", "", tokens[0]) if tokens else ""
    return "" if first in ("", "NONE", "NA") else first.replace(".", "-").replace("/", "-")


def download(symbols: list[str], start: str) -> pd.DataFrame:
    """Return long-format rows (symbol, date, adj_close, close, volume) for the symbols that worked."""
    import yfinance as yf

    raw = yf.download(symbols, start=start, auto_adjust=False, actions=False, progress=False,
                      group_by="ticker", threads=True)
    today = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date())
    frames = []
    for sym in symbols:
        if sym not in raw.columns.get_level_values(0):
            continue
        d = raw[sym][["Adj Close", "Close", "Volume"]].dropna(subset=["Adj Close", "Close"])
        d = d[(d["Adj Close"] > 0) & (d.index < today)]      # drop today's unfinished bar
        if d.empty:
            continue
        frames.append(pd.DataFrame({
            "symbol": sym, "date": d.index.date, "adj_close": d["Adj Close"].to_numpy(float),
            "close": d["Close"].to_numpy(float), "volume": d["Volume"].fillna(0).to_numpy(float)}))
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "adj_close", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def combine(parts_dir, sym_to_ciks: dict, out_path) -> int:
    """Stitch the batch files into one table keyed by issuer_cik."""
    tmp = out_path.with_suffix(".parquet.tmp")
    schema = pa.schema([("issuer_cik", pa.dictionary(pa.int32(), pa.string())), ("date", pa.date32()),
                        ("adj_close", pa.float64()), ("close", pa.float64()), ("volume", pa.float64())])
    n = 0
    with pq.ParquetWriter(tmp, schema, compression="zstd") as w:
        for part in sorted(parts_dir.glob("part_*.parquet")):
            d = pd.read_parquet(part)
            d = d[d["symbol"] != BENCH]
            if d.empty:
                continue
            # one ticker can belong to more than one CIK: repeat its rows for each
            d["issuer_cik"] = d["symbol"].map(sym_to_ciks)
            d = d.explode("issuer_cik").dropna(subset=["issuer_cik"]).sort_values(["issuer_cik", "date"])
            t = pa.Table.from_pandas(d[["issuer_cik", "date", "adj_close", "close", "volume"]], preserve_index=False)
            w.write_table(t.set_column(0, "issuer_cik", t["issuer_cik"].cast(pa.string()).dictionary_encode()).cast(schema))
            n += len(d)
    tmp.replace(out_path)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="discard earlier downloads and start over")
    ap.add_argument("--retry-failed", action="store_true", help="try the tickers that failed last time again")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--pause", type=float, default=2.0, help="seconds to wait between batches")
    args = ap.parse_args()

    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    parts, state_path = data / "yf_parts", data / "yf_state.json"
    if args.refresh:
        shutil.rmtree(parts, ignore_errors=True)
        state_path.unlink(missing_ok=True)
    parts.mkdir(exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"ok": [], "failed": [], "next_part": 0}

    if args.retry_failed:
        state["failed"] = []

    ev = pd.read_parquet(data / "events.parquet", columns=["issuer_cik", "ticker"]).dropna().drop_duplicates()
    ev = ev[ev["ticker"].str.strip() != ""]
    ev["symbol"] = ev["ticker"].map(yahoo_symbol)
    ev = ev[ev["symbol"] != ""]
    sym_to_ciks = ev.groupby("symbol")["issuer_cik"].agg(lambda s: sorted(set(s))).to_dict()
    done = set(state["ok"]) | set(state["failed"])
    todo = [s for s in [BENCH] + sorted(sym_to_ciks) if s not in done]
    print(f"[prices] {len(sym_to_ciks):,} tickers, {len(todo):,} still to download")

    start = cfg["yfinance"]["start"]
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        for attempt in range(3):
            try:
                df = download(batch, start)
                break
            except Exception as e:                       # network / rate limit: back off and retry
                print(f"[prices] batch failed ({type(e).__name__}: {e}); retrying in {30 * (attempt + 1)}s")
                time.sleep(30 * (attempt + 1))
        else:
            raise SystemExit("[prices] giving up for now; rerun the command to resume where it stopped.")
        got = set(df["symbol"].unique())
        if got:
            df.to_parquet(parts / f"part_{state['next_part']:05d}.parquet", index=False)
            state["next_part"] += 1
        state["ok"] += sorted(got)
        state["failed"] += [s for s in batch if s not in got]
        state_path.write_text(json.dumps(state))
        print(f"[prices] {min(i + args.batch, len(todo)):,}/{len(todo):,}  ok={len(state['ok']):,} failed={len(state['failed']):,}")
        time.sleep(args.pause)

    n = combine(parts, sym_to_ciks, data / "prices_yf.parquet")
    bench = pd.concat([pd.read_parquet(p) for p in sorted(parts.glob("part_*.parquet"))
                       if BENCH in set(pd.read_parquet(p, columns=["symbol"])["symbol"])])
    bench = bench.loc[bench["symbol"] == BENCH, ["symbol", "date", "adj_close"]].sort_values("date")
    if bench.empty:
        raise SystemExit("[prices] SPY download failed; rerun.")
    bench.to_parquet(data / "benchmark_yf.parquet", index=False)

    (cfg["paths"]["output_dir"] / "tables").mkdir(exist_ok=True)
    failed = ev[ev["symbol"].isin(state["failed"])].sort_values("symbol")
    failed.to_csv(cfg["paths"]["output_dir"] / "tables" / "price_fetch_failed.csv", index=False)
    print(f"[prices] wrote {n:,} price rows; SPY through {bench['date'].max()}; "
          f"{len(state['failed']):,} tickers had no data (see output/tables/price_fetch_failed.csv)")


if __name__ == "__main__":
    main()
