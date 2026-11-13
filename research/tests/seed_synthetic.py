"""Fill an EMPTY test database with synthetic data shaped like production.

Used only to exercise the research pipeline end to end without touching the
real database.  Refuses to run unless the database name contains "test".

    python -m research.tests.seed_synthetic postgresql://postgres:postgres@localhost/research_test
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from insider_platform.schema import get_schema_sql

N_ISSUERS = 60
N_OWNERS = 400
N_EVENTS = 6000
START, END = "2014-01-01", "2026-07-31"   # prices stop here (enrichment paused)


def main(dsn: str) -> None:
    if "test" not in dsn.rsplit("/", 1)[-1]:
        raise SystemExit("Refusing to seed: database name must contain 'test'.")
    rng = np.random.default_rng(7)
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(get_schema_sql())
    for t in ("insider_events", "event_outcomes", "issuer_prices_daily", "benchmark_prices_daily",
              "ai_outputs", "filings", "issuer_master", "issuer_fundamentals_cache", "market_cap_cache"):
        cur.execute(f"TRUNCATE {t}")

    days = pd.bdate_range(START, END)
    dstr = days.strftime("%Y-%m-%d").to_numpy()
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(days))))
    execute_values(cur, "INSERT INTO benchmark_prices_daily VALUES %s",
                   [("SPY.US", d, float(p), "2026-07-31T00:00:00Z") for d, p in zip(dstr, spy)])

    issuers = []
    for i in range(N_ISSUERS):
        cik = f"{1000000 + i:010d}"
        tkr = f"T{i:03d}"
        px = 20 * np.exp(np.cumsum(rng.normal(0.0003, 0.025, len(days))))
        first, last = 0, len(days)
        if i % 6 == 0:                       # delisted / acquired: series ends early
            last = int(rng.integers(600, len(days) - 300))
        if i % 10 == 3:                      # IPO: series starts late
            first = int(rng.integers(300, 1500))
        if i % 15 == 7:                      # stale split adjustment: a fake 4-for-1 break
            k = int(rng.integers(first + 400, last - 400))
            px[k:] = px[k:] / 4
        rows = [(cik, dstr[j], float(px[j]), f"{tkr}.US", "2026-07-31T00:00:00Z") for j in range(first, last)]
        if i % 20 == 11:                     # a gappy series (missing 30 days)
            del rows[500:530]
        execute_values(cur, "INSERT INTO issuer_prices_daily VALUES %s", rows, page_size=5000)
        mcap = int(10 ** rng.uniform(7.5, 11))
        cur.execute("INSERT INTO issuer_master VALUES (%s,%s,%s,%s,%s)", (cik, tkr, None, f"Issuer {i}", None))
        cur.execute("INSERT INTO issuer_fundamentals_cache (ticker, market_cap, shares_outstanding, sector, beta, fundamentals_json, updated_at)"
                    " VALUES (%s,%s,%s,%s,%s,'{}',%s)",
                    (tkr, mcap, mcap / float(px[last - 1]), ["Tech", "Health", "Energy", "Financials"][i % 4], 1.1,
                     "2026-06-15T00:00:00Z"))
        issuers.append((cik, tkr, first, last, mcap))

    skill = rng.normal(0, 0.03, N_OWNERS)            # persistent per-insider edge (planted signal)
    events, outcomes, filings, ai = [], [], [], []
    for n in range(N_EVENTS):
        cik, tkr, first, last, mcap = issuers[int(rng.integers(N_ISSUERS))]
        o = int(rng.integers(N_OWNERS))
        owner_key = f"{2000000 + o:010d}"
        k = int(rng.integers(first + 260, min(last + 150, len(days) - 1)))  # some filed after delisting
        k = min(k, len(days) - 1)
        filing_date = dstr[k]
        trade_date = dstr[max(k - int(rng.integers(1, 4)), 0)]
        acc = f"0001-{n:08d}"
        is_buy = rng.random() < 0.45
        form = "4/A" if rng.random() < 0.03 else "4"
        dollars = float(10 ** rng.uniform(3, 6.5))
        price = 20.0
        shares = dollars / price
        officer, director, ten = int(rng.random() < .4), int(rng.random() < .5), int(rng.random() < .15)
        title = rng.choice(["Chief Executive Officer", "CFO", "VP Sales", "", "General Counsel"]) if officer else None
        rated = filing_date >= "2025-01-01" and rng.random() < 0.6
        rating = round(float(np.clip(5.5 + 30 * skill[o] + rng.normal(0, 1), 1, 10)), 1) if rated else None
        live = filing_date >= "2026-03-01"
        gen_at = (filing_date if live else "2026-04-10") + "T12:00:00Z"
        events.append((cik, owner_key, acc, tkr, filing_date, trade_date, owner_key, f"Owner {o}", title,
                       officer, director, ten,
                       int(is_buy), trade_date if is_buy else None, shares if is_buy else None,
                       dollars if is_buy else None, price if is_buy else None,
                       shares * 5 if is_buy else None, 25.0 if is_buy else None,
                       int(not is_buy), trade_date if not is_buy else None, shares if not is_buy else None,
                       dollars if not is_buy else None, price if not is_buy else None,
                       float(rng.normal(0, .1)), float(rng.normal(0, .2)), float(-abs(rng.normal(0, .2))),
                       float(abs(rng.normal(0, .3))), int(rng.random() < .5), int(rng.random() < .5),
                       int(rng.random() < .2), mcap, "small", "2026-06-15T00:00:00Z",
                       rating if is_buy else None, None if is_buy else rating, gen_at if rated else None,
                       gen_at if rated else None, "v1", "2026-01-01T00:00:00Z"))
        filings.append((acc, cik, tkr, form, filing_date, None, "v1", "2026-01-01T00:00:00Z"))
        outcomes.append((cik, owner_key, acc, "buy" if is_buy else "sell", trade_date, filing_date, 20.0,
                         float(rng.normal(0, .2)), float(rng.normal(0, .2)), "SPY.US", "outcomes_v3", "x"))
        if rated:
            inp = {"baseline": {"buy": {"rating": 5.5}}, "issuer_context": {"market_cap_updated_at": gen_at},
                   "insider_stats": {"buy": {"eligible_n_60d": int(rng.integers(0, 5)), "win_rate_60d": 0.5,
                                             "eligible_n_180d": 0}}}
            ai.append((cik, owner_key, acc, "gemini-2.5-flash-lite", "prompt_ai_v5", "ai_input_v2", "ai_output_v1",
                       "h", rating if is_buy else None, None if is_buy else rating, 0.5, json.dumps(inp), "{}", gen_at))

    execute_values(cur, """INSERT INTO insider_events (issuer_cik, owner_key, accession_number, ticker, filing_date,
        event_trade_date, owner_cik, owner_name_display, owner_title, is_officer, is_director, is_ten_percent_owner,
        has_buy, buy_trade_date, buy_shares_total, buy_dollars_total, buy_vwap_price, buy_shares_owned_following,
        buy_pct_holdings_change, has_sell, sell_trade_date, sell_shares_total, sell_dollars_total, sell_vwap_price,
        trend_ret_20d, trend_ret_60d, trend_dist_52w_high, trend_dist_52w_low, trend_above_sma_50,
        trend_above_sma_200, cluster_flag_buy, market_cap, market_cap_bucket, market_cap_updated_at,
        ai_buy_rating, ai_sell_rating, ai_generated_at, ai_computed_at, parse_version, event_computed_at)
        VALUES %s""", events, page_size=2000)
    execute_values(cur, "INSERT INTO filings VALUES %s", filings, page_size=2000)
    execute_values(cur, """INSERT INTO event_outcomes (issuer_cik, owner_key, accession_number, side, trade_date,
        anchor_trading_date, p0, excess_return_60d, excess_return_180d, bench_symbol, outcomes_version, computed_at)
        VALUES %s""", outcomes, page_size=2000)
    execute_values(cur, """INSERT INTO ai_outputs (issuer_cik, owner_key, accession_number, model_id, prompt_version,
        input_schema_version, output_schema_version, inputs_hash, buy_rating, sell_rating, confidence, input_json,
        output_json, generated_at) VALUES %s""", ai, page_size=2000)
    conn.commit()
    print(f"seeded: {N_ISSUERS} issuers, {N_EVENTS} events, {len(ai)} ratings")


if __name__ == "__main__":
    main(sys.argv[1])
