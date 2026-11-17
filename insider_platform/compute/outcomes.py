from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

    outcomes_v4 (point-in-time entry; matches research/build_dataset.py `forward_returns`):
    - **Entry** is the close of the first trading day *strictly after* the filing date. Most Form 4s
      are accepted after the market close, so the filing-day close was usually not tradeable.
      If that day is more than MAX_ENTRY_GAP_DAYS calendar days after the filing, there is no entry.
    - **Exit** is the close `horizon` trading days (rows in the issuer's series) after entry.
    - **Benchmark** is measured over the SAME calendar dates as the stock: its last close on or
      before the entry date to its last close on or before the exit date. (Before v4 it counted
      +60/+180 rows in its own series, which misaligned the windows whenever the issuer's series
      had gaps.)
    - p0 is the issuer's adjusted close on the entry date (split-safe).

    Benchmark returns use the SAME sign convention as the trade side:
      - buy:  (bench_exit / bench_entry) - 1
      - sell: (bench_entry - bench_exit) / bench_entry
    so excess_return = trade_return - benchmark_return is "good for the insider" on both sides.
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


# Calendar days allowed between the filing date and the entry day (research config `max_entry_gap_days`).
MAX_ENTRY_GAP_DAYS = 7
HORIZONS: Tuple[int, ...] = (60, 180)


def _iso_day(x: Any) -> Optional[str]:
    """'YYYY-MM-DD' from a date/datetime/ISO string (time or timezone suffixes are dropped)."""
    if x is None:
        return None
    s = str(x).strip()[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def find_entry_index(
    dates: Sequence[str], filing_date: Any, *, max_gap_days: int = MAX_ENTRY_GAP_DAYS
) -> Tuple[Optional[int], Optional[str]]:
    """Index of the first trading day strictly AFTER `filing_date`.

    Returns (index, None) or (None, missing_reason).
    `dates` must be sorted ascending 'YYYY-MM-DD' strings.
    """
    fd = _iso_day(filing_date)
    if fd is None:
        return None, "missing_filing_date"
    i = bisect_right(dates, fd)
    if i >= len(dates):
        return None, "anchor_not_found"
    gap = (date.fromisoformat(dates[i]) - date.fromisoformat(fd)).days
    if gap > max_gap_days:
        return None, "entry_gap_too_large"
    return i, None


def _side_return(p0: float, p1: float, side: str) -> float:
    if side == "buy":
        return (p1 / p0) - 1.0
    # sell side: a fall in price after the sale counts as a positive return (short bias)
    return (p0 - p1) / p0


def _bench_return(b0: float, bf: float, side: str) -> float:
    return _side_return(b0, bf, side)


def forward_outcome(
    dates: Sequence[str],
    closes: Sequence[float],
    bench_dates: Sequence[str],
    bench_closes: Sequence[float],
    filing_date: Any,
    side: str,
    *,
    horizons: Sequence[int] = HORIZONS,
    max_entry_gap_days: int = MAX_ENTRY_GAP_DAYS,
) -> Dict[str, Any]:
    """Pure forward-return computation for one event side (no database access).

    Returns a dict with `missing_reason` (None when an entry exists), `anchor_date`, `p0`, and for
    each horizon h: future_date_{h}d, future_price_{h}d, return_{h}d, missing_reason_{h}d,
    bench_return_{h}d, bench_missing_reason_{h}d, excess_return_{h}d.
    """
    out: Dict[str, Any] = {"missing_reason": None, "anchor_date": None, "p0": None}
    for h in horizons:
        out.update({
            f"future_date_{h}d": None, f"future_price_{h}d": None, f"return_{h}d": None,
            f"missing_reason_{h}d": None, f"bench_return_{h}d": None,
            f"bench_missing_reason_{h}d": None, f"excess_return_{h}d": None,
        })

    i, reason = find_entry_index(dates, filing_date, max_gap_days=max_entry_gap_days)
    if i is None:
        out["missing_reason"] = reason
        return out
    p0 = float(closes[i])
    if p0 <= 0:
        out["missing_reason"] = "bad_anchor_price"
        return out
    entry_date = dates[i]
    out["anchor_date"] = entry_date
    out["p0"] = p0

    # Benchmark close on or before the entry date.
    b0 = None
    bench_entry_reason = None
    if not bench_dates:
        bench_entry_reason = "missing_benchmark_series"
    else:
        bi0 = bisect_right(bench_dates, entry_date) - 1
        if bi0 < 0:
            bench_entry_reason = "benchmark_anchor_not_found"
        elif float(bench_closes[bi0]) <= 0:
            bench_entry_reason = "benchmark_bad_p0"
        else:
            b0 = float(bench_closes[bi0])

    for h in horizons:
        xi = i + h
        if xi >= len(dates):
            out[f"missing_reason_{h}d"] = "insufficient_future_data"
            out[f"bench_missing_reason_{h}d"] = bench_entry_reason or "trade_return_missing"
            continue
        exit_date = dates[xi]
        fp = float(closes[xi])
        r = _side_return(p0, fp, side)
        out[f"future_date_{h}d"] = exit_date
        out[f"future_price_{h}d"] = fp
        out[f"return_{h}d"] = r

        if b0 is None:
            out[f"bench_missing_reason_{h}d"] = bench_entry_reason
            continue
        # The benchmark must have a close on/after the exit date, otherwise its series is stale.
        if bench_dates[-1] < exit_date:
            out[f"bench_missing_reason_{h}d"] = "insufficient_benchmark_future_data"
            continue
        bi1 = bisect_right(bench_dates, exit_date) - 1
        br = _bench_return(b0, float(bench_closes[bi1]), side)
        out[f"bench_return_{h}d"] = br
        out[f"excess_return_{h}d"] = r - br
    return out


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

    # Entry = first trading day strictly after filing_date (tradeable),
    # falling back to trade_date when filing_date is missing.
    anchor_source_date = filing_date or trade_date
    res = forward_outcome(dates, closes, bench_dates, bench_closes, anchor_source_date, side)
    if res["missing_reason"] is not None:
        _upsert_missing(
            conn,
            cfg,
            event_key,
            side=side,
            trade_date=trade_date,
            p0=None,
            reason=res["missing_reason"],
            bench_symbol=bench_symbol,
            bench_missing_reason="missing_benchmark_series" if not bench_dates else None,
        )
        return

    anchor_date = res["anchor_date"]
    p0f = res["p0"]
    out = {k: res[k] for k in (
        "future_date_60d", "future_price_60d", "return_60d", "missing_reason_60d",
        "future_date_180d", "future_price_180d", "return_180d", "missing_reason_180d",
    )}
    bench_return_60 = res["bench_return_60d"]
    bench_reason_60 = res["bench_missing_reason_60d"]
    bench_return_180 = res["bench_return_180d"]
    bench_reason_180 = res["bench_missing_reason_180d"]
    excess_60 = res["excess_return_60d"]
    excess_180 = res["excess_return_180d"]

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
