from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from insider_platform.config import Config
from insider_platform.eodhd.client import fetch_fundamentals, resolve_symbol
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[mcap] {msg}")


def _bucket_market_cap(mcap: Optional[int]) -> str:
    if mcap is None:
        return "unknown"
    # Simple buckets; tweak as needed
    if mcap < 300_000_000:
        return "micro"
    if mcap < 2_000_000_000:
        return "small"
    if mcap < 10_000_000_000:
        return "mid"
    if mcap < 200_000_000_000:
        return "large"
    return "mega"


def _to_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        # sometimes strings, sometimes floats
        return int(float(x))
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _is_stale(ts: Optional[str], *, max_age_days: int) -> bool:
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return True
    return (datetime.now(timezone.utc) - dt) > timedelta(days=max_age_days)


def fetch_and_store_market_cap(conn: Any, cfg: Config, ticker: str) -> None:
    """Fetch market cap + key fundamentals from EODHD and store locally.

    We *do not* depend on EODHD at runtime beyond this fetch step; results are cached in DB:
      - market_cap_cache (for quick access)
      - issuer_fundamentals_cache (raw payload + extracted highlights)

    Data source:
      GET https://eodhd.com/api/fundamentals/{symbol}?api_token=...&fmt=json
    """
    t = (ticker or "").strip().upper()
    if not t:
        raise RuntimeError("Ticker is blank")

    # Skip if fresh in cache
    cached = conn.execute(
        "SELECT market_cap_updated_at FROM market_cap_cache WHERE ticker=?",
        (t,),
    ).fetchone()
    if cached is not None:
        ts = cached["market_cap_updated_at"]
        if ts and not _is_stale(ts, max_age_days=cfg.MARKET_CAP_MAX_AGE_DAYS):
            _debug(f"Market cap cache hit ticker={t} updated_at={ts}")
            return

    # Resolve to EODHD symbol and fetch fundamentals
    symbol = resolve_symbol(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, t)
    payload = fetch_fundamentals(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, symbol)

    # Extract common highlight fields (best-effort; payload shape can vary by instrument)
    highlights = payload.get("Highlights") or {}
    shares_stats = payload.get("SharesStats") or {}

    general = payload.get("General") or {}
    technicals = payload.get("Technicals") or {}

    market_cap = _to_int(highlights.get("MarketCapitalization") or highlights.get("MarketCapitalizationUSD") or highlights.get("MarketCapitalizationUsd"))
    pe_ratio = _to_float(highlights.get("PERatio") or highlights.get("PeRatio") or highlights.get("peRatio"))
    eps = _to_float(highlights.get("EarningsShare") or highlights.get("EPS") or highlights.get("Eps") or highlights.get("eps"))
    shares_outstanding = _to_float(
        shares_stats.get("SharesOutstanding")
        or highlights.get("SharesOutstanding")
        or payload.get("SharesOutstanding")
    )

    sector = (general.get("Sector") or general.get("sector"))
    beta = _to_float(technicals.get("Beta") or technicals.get("beta"))

    now = utcnow_iso()
    bucket = _bucket_market_cap(market_cap)

    # Store full fundamentals payload (so we can add more fields later without refetching)
    conn.execute(
        """
        INSERT INTO issuer_fundamentals_cache
            (ticker, eodhd_symbol, market_cap, pe_ratio, eps, shares_outstanding, sector, beta, fundamentals_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            eodhd_symbol=excluded.eodhd_symbol,
            market_cap=excluded.market_cap,
            pe_ratio=excluded.pe_ratio,
            eps=excluded.eps,
            shares_outstanding=excluded.shares_outstanding,
            sector=excluded.sector,
            beta=excluded.beta,
            fundamentals_json=excluded.fundamentals_json,
            updated_at=excluded.updated_at
        """,
        (t, symbol, market_cap, pe_ratio, eps, shares_outstanding, sector, beta, json.dumps(payload), now),
    )

    # Keep the existing market_cap_cache table in sync (for any legacy code paths)
    conn.execute(
        """
        INSERT INTO market_cap_cache (ticker, market_cap, market_cap_bucket, market_cap_source, market_cap_updated_at)
        VALUES (?, ?, ?, 'eodhd', ?)
        ON CONFLICT(ticker) DO UPDATE SET
            market_cap=excluded.market_cap,
            market_cap_bucket=excluded.market_cap_bucket,
            market_cap_source=excluded.market_cap_source,
            market_cap_updated_at=excluded.market_cap_updated_at
        """,
        (t, market_cap, bucket, now),
    )

    # NOTE: this is a current snapshot. It is NOT copied onto insider_events: event market cap is
    # point-in-time (see compute/market_cap_pit.py).

    _debug(f"Updated fundamentals ticker={t} symbol={symbol} mcap={market_cap} bucket={bucket} sector={sector} beta={beta} pe={pe_ratio} shares_out={shares_outstanding}")
