from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from insider_platform.config import Config
from insider_platform.eodhd.client import fetch_eod_prices, resolve_symbol
from insider_platform.compute.ticker_validation import validate_issuer_ticker
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[prices] {msg}")


def fetch_and_store_prices_for_issuer(conn: Any, cfg: Config, issuer_cik: str) -> None:
    if not cfg.EODHD_API_KEY:
        raise RuntimeError("EODHD_API_KEY is not set")

    row = conn.execute("SELECT current_ticker FROM issuer_master WHERE issuer_cik=?", (issuer_cik,)).fetchone()
    if row is None or not row["current_ticker"]:
        raise RuntimeError(f"No current_ticker for issuer_cik={issuer_cik}; cannot fetch prices")

    ticker = row["current_ticker"]
    symbol = resolve_symbol(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, ticker)
    validation = validate_issuer_ticker(conn, cfg, issuer_cik=issuer_cik, ticker=ticker, eodhd_symbol=symbol)
    if validation.status == "invalid":
        _debug(
            "Skipping price fetch because ticker validation failed: "
            f"issuer_cik={issuer_cik} ticker={ticker} symbol={symbol} reason={validation.reason}"
        )
        return

    end = datetime.now(timezone.utc).date().isoformat()

    # Incremental refresh: if we already have prices, only re-fetch a recent window.
    # (We still upsert, so overlaps are safe.)
    r = conn.execute(
        "SELECT MAX(date) AS max_date FROM issuer_prices_daily WHERE issuer_cik=?",
        (issuer_cik,),
    ).fetchone()

    if r is not None and r["max_date"]:
        try:
            max_dt = datetime.fromisoformat(str(r["max_date"])).date()
            start = (max_dt - timedelta(days=30)).isoformat()
        except Exception:
            start = "2000-01-01"
    else:
        start = "2000-01-01"

    _debug(f"Fetching prices for issuer_cik={issuer_cik} ticker={ticker} symbol={symbol}")
    prices = fetch_eod_prices(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, symbol, start, end)

    updated_at = utcnow_iso()
    cur = conn.cursor()
    n = 0
    for p in prices:
        cur.execute(
            """
            INSERT INTO issuer_prices_daily (issuer_cik, date, adj_close, source_ticker, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(issuer_cik, date) DO UPDATE SET
                adj_close=excluded.adj_close,
                source_ticker=excluded.source_ticker,
                updated_at=excluded.updated_at
            """,
            (issuer_cik, p.date, p.adj_close, symbol, updated_at),
        )
        n += 1

    _debug(f"Upserted {n} price rows for issuer_cik={issuer_cik}")


def fetch_and_store_benchmark_prices(conn: Any, cfg: Config, symbol: str | None = None) -> str:
    """Fetch and store benchmark daily adjusted close series.

    Used for excess-return calculations (insider performance vs S&P500 proxy).
    Returns the resolved EODHD symbol used.
    """
    if not cfg.EODHD_API_KEY:
        raise RuntimeError("EODHD_API_KEY is not set")

    sym_in = (symbol or cfg.BENCHMARK_SYMBOL or "").strip()
    if not sym_in:
        raise RuntimeError("BENCHMARK_SYMBOL is blank")

    sym = resolve_symbol(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, sym_in)

    end = datetime.now(timezone.utc).date().isoformat()

    r = conn.execute(
        "SELECT MAX(date) AS max_date FROM benchmark_prices_daily WHERE symbol=?",
        (sym,),
    ).fetchone()

    if r is not None and r["max_date"]:
        try:
            max_dt = datetime.fromisoformat(str(r["max_date"])).date()
            start = (max_dt - timedelta(days=30)).isoformat()
        except Exception:
            start = "2000-01-01"
    else:
        start = "2000-01-01"

    _debug(f"Fetching benchmark prices symbol={sym} from={start} to={end}")
    prices = fetch_eod_prices(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, sym, start, end)

    updated_at = utcnow_iso()
    cur = conn.cursor()
    n = 0
    for p in prices:
        cur.execute(
            """
            INSERT INTO benchmark_prices_daily (symbol, date, adj_close, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                adj_close=excluded.adj_close,
                updated_at=excluded.updated_at
            """,
            (sym, p.date, p.adj_close, updated_at),
        )
        n += 1

    _debug(f"Upserted {n} benchmark price rows symbol={sym}")
    return sym
