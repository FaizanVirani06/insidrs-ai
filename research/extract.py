"""Step 1: copy what the study needs out of Postgres into Parquet files.

Read-only: the connection is opened in read-only mode and only SELECTs run.
Nothing from users / billing / support tables is read.

    python -m research.extract
"""
from __future__ import annotations

import time

import pyarrow as pa
import pyarrow.parquet as pq

from research.common import connect_readonly, load_config

# One row per insider event, with the filing's form type, sector, and the
# returns production already computed (kept only to compare against ours).
EVENTS_SQL = """
SELECT e.issuer_cik, e.owner_key, e.accession_number, e.ticker,
       e.filing_date::date AS filing_date,
       f.form_type,
       e.owner_cik, e.owner_name_display, e.owner_title,
       e.is_officer, e.is_director, e.is_ten_percent_owner,
       e.has_buy, e.buy_trade_date::date AS buy_trade_date, e.buy_shares_total, e.buy_dollars_total,
       e.buy_vwap_price, e.buy_shares_owned_following, e.buy_pct_holdings_change,
       e.has_sell, e.sell_trade_date::date AS sell_trade_date, e.sell_shares_total, e.sell_dollars_total,
       e.sell_vwap_price, e.sell_shares_owned_following, e.sell_pct_holdings_change,
       e.non_open_market_row_count, e.derivative_row_count,
       e.trend_ret_20d, e.trend_ret_60d, e.trend_dist_52w_high, e.trend_dist_52w_low,
       e.trend_above_sma_50, e.trend_above_sma_200,
       e.cluster_flag_buy AS prod_cluster_flag_buy, e.cluster_flag_sell AS prod_cluster_flag_sell,
       e.market_cap, LEFT(e.market_cap_updated_at, 10)::date AS market_cap_date,
       e.ai_computed_at,
       fc.sector,
       ob.excess_return_60d  AS prod_buy_ex_60,  ob.excess_return_180d AS prod_buy_ex_180,
       os.excess_return_60d  AS prod_sell_ex_60, os.excess_return_180d AS prod_sell_ex_180
FROM insider_events e
LEFT JOIN filings f ON f.accession_number = e.accession_number
LEFT JOIN issuer_fundamentals_cache fc ON fc.ticker = e.ticker
LEFT JOIN event_outcomes ob ON ob.issuer_cik = e.issuer_cik AND ob.owner_key = e.owner_key
      AND ob.accession_number = e.accession_number AND ob.side = 'buy'
LEFT JOIN event_outcomes os ON os.issuer_cik = e.issuer_cik AND os.owner_key = e.owner_key
      AND os.accession_number = e.accession_number AND os.side = 'sell'
WHERE e.has_buy = 1 OR e.has_sell = 1
"""

# Sorted by (issuer, date) so the build step can slice each issuer's series.
PRICES_SQL = """
SELECT issuer_cik, date::date AS date, adj_close
FROM issuer_prices_daily
WHERE adj_close > 0
ORDER BY issuer_cik, date
"""

BENCH_SQL = """
SELECT symbol, date::date AS date, adj_close
FROM benchmark_prices_daily
WHERE adj_close > 0
ORDER BY symbol, date
"""

# Every rating ever stored (an event can have several). We pull the few fields
# of input_json that matter for leakage checks instead of the whole blob.
RATINGS_SQL = r"""
SELECT ai_output_id, issuer_cik, owner_key, accession_number,
       model_id, prompt_version, buy_rating, sell_rating, confidence,
       generated_at AS model_generated_at,
       (input_json::jsonb #>> '{baseline,buy,rating}')::float  AS baseline_buy,
       (input_json::jsonb #>> '{baseline,sell,rating}')::float AS baseline_sell,
       input_json::jsonb #>> '{issuer_context,market_cap_updated_at}' AS input_mcap_ts,
       (input_json::jsonb #>> '{insider_stats,buy,eligible_n_60d}')::float  AS shown_buy_n_60,
       (input_json::jsonb #>> '{insider_stats,buy,win_rate_60d}')::float    AS shown_buy_win_60,
       (input_json::jsonb #>> '{insider_stats,buy,eligible_n_180d}')::float AS shown_buy_n_180,
       (input_json::jsonb #>> '{insider_stats,sell,eligible_n_60d}')::float AS shown_sell_n_60
FROM ai_outputs
ORDER BY ai_output_id
"""


def dump(conn, name: str, sql: str, out_dir, dictionary_cols=(), chunk: int = 200_000) -> int:
    """Stream a query to a Parquet file without loading it all into memory."""
    path = out_dir / f"{name}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    cur = conn.cursor(name=f"research_{name}")   # server-side cursor
    cur.itersize = chunk
    cur.execute(sql)
    writer, n, t0 = None, 0, time.time()
    while True:
        rows = cur.fetchmany(chunk)
        if not rows:
            break
        cols = [d[0] for d in cur.description]
        arrays = {c: pa.array([r[i] for r in rows]) for i, c in enumerate(cols)}
        for c in dictionary_cols:
            arrays[c] = arrays[c].dictionary_encode()
        table = pa.table(arrays)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(tmp, schema, compression="zstd")
        writer.write_table(table.cast(schema))
        n += len(rows)
    cur.close()
    if writer is None:
        raise SystemExit(f"{name}: query returned no rows")
    writer.close()
    tmp.replace(path)                             # atomic: never leave a half-written file
    print(f"[extract] {name}: {n:,} rows -> {path.name} ({time.time() - t0:.0f}s)")
    return n


def main() -> None:
    cfg = load_config()
    out = cfg["paths"]["data_dir"]
    conn = connect_readonly()
    try:
        dump(conn, "events", EVENTS_SQL, out)
        dump(conn, "ratings", RATINGS_SQL, out)
        dump(conn, "benchmark", BENCH_SQL, out)
        dump(conn, "prices", PRICES_SQL, out, dictionary_cols=("issuer_cik",), chunk=500_000)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
