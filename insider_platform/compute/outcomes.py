from __future__ import annotations

from typing import Any, List, Tuple, Optional

from insider_platform.config import Config
from insider_platform.db import get_app_config
from insider_platform.jobs.queue import enqueue_job
from insider_platform.models import EventKey
from insider_platform.compute.ticker_validation import get_validation_status
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[outcomes] {msg}")


def compute_outcomes_for_event(conn: Any, cfg: Config, event_key: EventKey) -> None:
    """Compute +60/+180 trading-day forward returns for buy and sell sides.

    **Anchor convention (tradeable):**
    - We anchor on the first trading day on/after the *filing_date* (not the transaction date).
      This makes outcomes representative of what a user could have traded after the filing became public.
    - We store p0 as the issuer's adjusted close on that anchor date. This keeps the return series
      internally consistent (important around splits, dividends, etc.).

    outcomes_v3 adds a benchmark series (default: SPY.US) so we can compute:
      excess_return = trade_return - benchmark_return

    Benchmark returns use the SAME sign convention as the trade side:
      - buy:  (bench_future / bench_anchor) - 1
      - sell: (bench_anchor - bench_future) / bench_anchor
    """
    ev = conn.execute(
        """
        SELECT issuer_cik, ticker, filing_date,
               buy_trade_date, sell_trade_date,
               buy_vwap_price, sell_vwap_price,
               has_buy, has_sell
        FROM insider_events
        WHERE issuer_cik=? AND owner_key=? AND accession_number=?
        """,
        (event_key.issuer_cik, event_key.owner_key, event_key.accession_number),
    ).fetchone()
    if ev is None:
        raise RuntimeError(f"Event not found: {event_key}")

    if get_validation_status(conn, event_key.issuer_cik, ev.get("ticker")) == "invalid":
        if int(ev["has_buy"]) == 1:
            _upsert_missing(
                conn,
                cfg,
                event_key,
                side="buy",
                trade_date=ev["buy_trade_date"],
                p0=None,
                reason="ticker_validation_failed",
                bench_symbol=(get_app_config(conn, "benchmark_symbol_resolved") or cfg.BENCHMARK_SYMBOL or "").strip() or "SPY.US",
                bench_missing_reason=None,
            )
        if int(ev["has_sell"]) == 1:
            _upsert_missing(
                conn,
                cfg,
                event_key,
                side="sell",
                trade_date=ev["sell_trade_date"],
                p0=None,
                reason="ticker_validation_failed",
                bench_symbol=(get_app_config(conn, "benchmark_symbol_resolved") or cfg.BENCHMARK_SYMBOL or "").strip() or "SPY.US",
                bench_missing_reason=None,
            )
        _touch_event(conn, event_key)
        return

    # Issuer price series (required for trade returns).
    issuer_series = _load_prices(conn, event_key.issuer_cik)

    # Benchmark series (optional). Use resolved symbol if available.
    bench_symbol = (get_app_config(conn, "benchmark_symbol_resolved") or cfg.BENCHMARK_SYMBOL or "").strip() or "SPY.US"
    bench_series = _load_benchmark_prices(conn, bench_symbol)

    # Self-heal: if benchmark series is missing, enqueue a fetch job once.
    if not bench_series:
        enqueue_job(
            conn,
            job_type="FETCH_BENCHMARK_PRICES",
            dedupe_key=f"BENCH|{bench_symbol}",
            payload={"symbol": bench_symbol},
            priority=120,
        )


    # Pre-split for fast indexing.
    issuer_dates = [d for d, _ in issuer_series]
    issuer_closes = [c for _, c in issuer_series]
    bench_dates = [d for d, _ in bench_series]
    bench_closes = [c for _, c in bench_series]

    if not issuer_series:
        # Write missing outcomes for sides present.
        if int(ev["has_buy"]) == 1:
            _upsert_missing(
                conn,
                cfg,
                event_key,
                side="buy",
                trade_date=ev["buy_trade_date"],
                p0=None,
                reason="missing_price_series",
                bench_symbol=bench_symbol,
                bench_missing_reason="missing_benchmark_series" if not bench_series else None,
            )
        if int(ev["has_sell"]) == 1:
            _upsert_missing(
                conn,
                cfg,
                event_key,
                side="sell",
                trade_date=ev["sell_trade_date"],
                p0=None,
                reason="missing_price_series",
                bench_symbol=bench_symbol,
                bench_missing_reason="missing_benchmark_series" if not bench_series else None,
            )
        _touch_event(conn, event_key)
        return

    if int(ev["has_buy"]) == 1:
        _compute_side(
            conn,
            cfg,
            event_key,
            side="buy",
            trade_date=ev["buy_trade_date"],
            filing_date=ev["filing_date"],
            dates=issuer_dates,
            closes=issuer_closes,
            bench_symbol=bench_symbol,
            bench_dates=bench_dates,
            bench_closes=bench_closes,
        )
    else:
        _delete_outcomes(conn, event_key, side="buy")

    if int(ev["has_sell"]) == 1:
        _compute_side(
            conn,
            cfg,
            event_key,
            side="sell",
            trade_date=ev["sell_trade_date"],
            filing_date=ev["filing_date"],
            dates=issuer_dates,
            closes=issuer_closes,
            bench_symbol=bench_symbol,
            bench_dates=bench_dates,
            bench_closes=bench_closes,
        )
    else:
        _delete_outcomes(conn, event_key, side="sell")

    _touch_event(conn, event_key)


def _load_prices(conn: Any, issuer_cik: str) -> List[Tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, adj_close FROM issuer_prices_daily WHERE issuer_cik=? ORDER BY date ASC",
        (issuer_cik,),
    ).fetchall()
    return [(str(r["date"]), float(r["adj_close"])) for r in rows]


def _load_benchmark_prices(conn: Any, symbol: str) -> List[Tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, adj_close FROM benchmark_prices_daily WHERE symbol=? ORDER BY date ASC",
        (symbol,),
    ).fetchall()
    return [(str(r["date"]), float(r["adj_close"])) for r in rows]


def _find_anchor_index(dates: List[str], trade_date: Any) -> Optional[int]:
    if not trade_date:
        return None
    td = str(trade_date)
    for idx, d in enumerate(dates):
        if d >= td:
            return idx
    return None


def _bench_return(b0: float, bf: float, side: str) -> float:
    if side == "buy":
        return (bf / b0) - 1.0
    # sell side: treat benchmark as the reference the same way we treat the trade (short bias)
    return (b0 - bf) / b0


def _compute_side(
    conn: Any,
    cfg: Config,
    event_key: EventKey,
    side: str,
    trade_date: Any,
    filing_date: Any,
    dates: List[str],
    closes: List[float],
    bench_symbol: str,
    bench_dates: List[str],
    bench_closes: List[float],
) -> None:
    if not trade_date:
        _upsert_missing(
            conn,
            cfg,
            event_key,
            side=side,
            trade_date=None,
            p0=None,
            reason="missing_trade_date",
            bench_symbol=bench_symbol,
            bench_missing_reason="missing_benchmark_series" if not bench_dates else None,
        )
        return

    # Anchor index = first trading day on/after filing_date (tradeable),
    # falling back to trade_date when filing_date is missing.
    anchor_source_date = filing_date or trade_date
    i = _find_anchor_index(dates, anchor_source_date)
    if i is None:
        _upsert_missing(
            conn,
            cfg,
            event_key,
            side=side,
            trade_date=trade_date,
            p0=None,
            reason="anchor_not_found",
            bench_symbol=bench_symbol,
            bench_missing_reason="missing_benchmark_series" if not bench_dates else None,
        )
        return

    anchor_date = dates[i]
    p0f = float(closes[i])
    if p0f <= 0:
        _upsert_missing(
            conn,
            cfg,
            event_key,
            side=side,
            trade_date=trade_date,
            p0=None,
            reason="bad_anchor_price",
            bench_symbol=bench_symbol,
            bench_missing_reason="missing_benchmark_series" if not bench_dates else None,
        )
        return

    # Trade-side forward returns (issuer)
    out = {
        "future_date_60d": None,
        "future_price_60d": None,
        "return_60d": None,
        "missing_reason_60d": None,
        "future_date_180d": None,
        "future_price_180d": None,
        "return_180d": None,
        "missing_reason_180d": None,
    }

    # +60 trading days
    if i + 60 < len(dates):
        fd = dates[i + 60]
        fp = closes[i + 60]
        out["future_date_60d"] = fd
        out["future_price_60d"] = fp
        if side == "buy":
            out["return_60d"] = (fp / p0f) - 1.0
        else:
            out["return_60d"] = (p0f - fp) / p0f
    else:
        out["missing_reason_60d"] = "insufficient_future_data"

    # +180 trading days
    if i + 180 < len(dates):
        fd = dates[i + 180]
        fp = closes[i + 180]
        out["future_date_180d"] = fd
        out["future_price_180d"] = fp
        if side == "buy":
            out["return_180d"] = (fp / p0f) - 1.0
        else:
            out["return_180d"] = (p0f - fp) / p0f
    else:
        out["missing_reason_180d"] = "insufficient_future_data"

    # Benchmark forward returns (optional)
    bench_return_60 = None
    bench_reason_60 = None
    bench_return_180 = None
    bench_reason_180 = None

    if not bench_dates:
        bench_reason_60 = "missing_benchmark_series"
        bench_reason_180 = "missing_benchmark_series"
    else:
        bi = _find_anchor_index(bench_dates, anchor_source_date)
        if bi is None:
            bench_reason_60 = "benchmark_anchor_not_found"
            bench_reason_180 = "benchmark_anchor_not_found"
        else:
            b0 = bench_closes[bi]
            if b0 <= 0:
                bench_reason_60 = "benchmark_bad_p0"
                bench_reason_180 = "benchmark_bad_p0"
            else:
                if bi + 60 < len(bench_dates):
                    bf = bench_closes[bi + 60]
                    bench_return_60 = _bench_return(b0, bf, side)
                else:
                    bench_reason_60 = "insufficient_benchmark_future_data"

                if bi + 180 < len(bench_dates):
                    bf = bench_closes[bi + 180]
                    bench_return_180 = _bench_return(b0, bf, side)
                else:
                    bench_reason_180 = "insufficient_benchmark_future_data"

    # Excess returns only when both are available.
    excess_60 = None
    if out["return_60d"] is not None and bench_return_60 is not None:
        excess_60 = float(out["return_60d"]) - float(bench_return_60)

    excess_180 = None
    if out["return_180d"] is not None and bench_return_180 is not None:
        excess_180 = float(out["return_180d"]) - float(bench_return_180)

    now = utcnow_iso()
    conn.execute(
        """
        INSERT INTO event_outcomes (
            issuer_cik, owner_key, accession_number, side,
            trade_date, anchor_trading_date, p0,
            future_date_60d, future_price_60d, return_60d, missing_reason_60d,
            bench_symbol, bench_return_60d, bench_missing_reason_60d, excess_return_60d,
            future_date_180d, future_price_180d, return_180d, missing_reason_180d,
            bench_return_180d, bench_missing_reason_180d, excess_return_180d,
            outcomes_version, computed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(issuer_cik, owner_key, accession_number, side) DO UPDATE SET
            trade_date=excluded.trade_date,
            anchor_trading_date=excluded.anchor_trading_date,
            p0=excluded.p0,
            future_date_60d=excluded.future_date_60d,
            future_price_60d=excluded.future_price_60d,
            return_60d=excluded.return_60d,
            missing_reason_60d=excluded.missing_reason_60d,
            bench_symbol=excluded.bench_symbol,
            bench_return_60d=excluded.bench_return_60d,
            bench_missing_reason_60d=excluded.bench_missing_reason_60d,
            excess_return_60d=excluded.excess_return_60d,
            future_date_180d=excluded.future_date_180d,
            future_price_180d=excluded.future_price_180d,
            return_180d=excluded.return_180d,
            missing_reason_180d=excluded.missing_reason_180d,
            bench_return_180d=excluded.bench_return_180d,
            bench_missing_reason_180d=excluded.bench_missing_reason_180d,
            excess_return_180d=excluded.excess_return_180d,
            outcomes_version=excluded.outcomes_version,
            computed_at=excluded.computed_at
        """,
        (
            event_key.issuer_cik,
            event_key.owner_key,
            event_key.accession_number,
            side,
            trade_date,
            anchor_date,
            p0f,
            out["future_date_60d"],
            out["future_price_60d"],
            out["return_60d"],
            out["missing_reason_60d"],
            bench_symbol,
            bench_return_60,
            bench_reason_60,
            excess_60,
            out["future_date_180d"],
            out["future_price_180d"],
            out["return_180d"],
            out["missing_reason_180d"],
            bench_return_180,
            bench_reason_180,
            excess_180,
            cfg.CURRENT_OUTCOMES_VERSION,
            now,
        ),
    )

    _debug(
        f"Outcomes computed for {event_key} side={side} anchor={anchor_date} "
        f"r60={out['return_60d']} br60={bench_return_60} ex60={excess_60} "
        f"r180={out['return_180d']} br180={bench_return_180} ex180={excess_180}"
    )


def _upsert_missing(
    conn: Any,
    cfg: Config,
    event_key: EventKey,
    side: str,
    trade_date: Any,
    p0: Any,
    reason: str,
    *,
    bench_symbol: str,
    bench_missing_reason: Optional[str] = None,
) -> None:
    """Upsert a row where trade returns are missing (still records benchmark missing reason if known)."""
    now = utcnow_iso()
    conn.execute(
        """
        INSERT INTO event_outcomes (
            issuer_cik, owner_key, accession_number, side,
            trade_date, anchor_trading_date, p0,
            future_date_60d, future_price_60d, return_60d, missing_reason_60d,
            bench_symbol, bench_return_60d, bench_missing_reason_60d, excess_return_60d,
            future_date_180d, future_price_180d, return_180d, missing_reason_180d,
            bench_return_180d, bench_missing_reason_180d, excess_return_180d,
            outcomes_version, computed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(issuer_cik, owner_key, accession_number, side) DO UPDATE SET
            trade_date=excluded.trade_date,
            anchor_trading_date=excluded.anchor_trading_date,
            p0=excluded.p0,
            future_date_60d=NULL,
            future_price_60d=NULL,
            return_60d=NULL,
            missing_reason_60d=excluded.missing_reason_60d,
            bench_symbol=excluded.bench_symbol,
            bench_return_60d=NULL,
            bench_missing_reason_60d=excluded.bench_missing_reason_60d,
            excess_return_60d=NULL,
            future_date_180d=NULL,
            future_price_180d=NULL,
            return_180d=NULL,
            missing_reason_180d=excluded.missing_reason_180d,
            bench_return_180d=NULL,
            bench_missing_reason_180d=excluded.bench_missing_reason_180d,
            excess_return_180d=NULL,
            outcomes_version=excluded.outcomes_version,
            computed_at=excluded.computed_at
        """,
        (
            event_key.issuer_cik,
            event_key.owner_key,
            event_key.accession_number,
            side,
            trade_date,
            None,
            float(p0) if isinstance(p0, (int, float)) else None,
            None,
            None,
            None,
            reason,
            bench_symbol,
            None,
            bench_missing_reason,
            None,
            None,
            None,
            None,
            reason,
            None,
            bench_missing_reason,
            None,
            cfg.CURRENT_OUTCOMES_VERSION,
            now,
        ),
    )

    _debug(f"Outcomes missing for {event_key} side={side}: {reason}")


def _delete_outcomes(conn: Any, event_key: EventKey, side: str) -> None:
    conn.execute(
        "DELETE FROM event_outcomes WHERE issuer_cik=? AND owner_key=? AND accession_number=? AND side=?",
        (event_key.issuer_cik, event_key.owner_key, event_key.accession_number, side),
    )


def _touch_event(conn: Any, event_key: EventKey) -> None:
    conn.execute(
        """
        UPDATE insider_events
        SET outcomes_computed_at=?
        WHERE issuer_cik=? AND owner_key=? AND accession_number=?
        """,
        (utcnow_iso(), event_key.issuer_cik, event_key.owner_key, event_key.accession_number),
    )
