from __future__ import annotations

from statistics import mean
from typing import Any, List, Tuple, Optional

from insider_platform.models import EventKey
from insider_platform.compute.ticker_validation import get_validation_status
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[trend] {msg}")


def compute_trend_for_event(conn: Any, event_key: EventKey) -> None:
    """Compute trend context for an event using adjusted close prices.

    Anchor trading day:
      - Prefer the earliest open-market trade date (buy_trade_date / sell_trade_date) when present.
      - Otherwise fall back to event_trade_date.
      - Use the first trading day on/after that anchor date.

    Lookbacks: 20/60 pre-returns; 52w distances using trailing 252 trading days; SMA-50/200.
    """
    ev = conn.execute(
        """
        SELECT issuer_cik, ticker, event_trade_date, has_buy, has_sell, buy_trade_date, sell_trade_date
        FROM insider_events
        WHERE issuer_cik=? AND owner_key=? AND accession_number=?
        """,
        (event_key.issuer_cik, event_key.owner_key, event_key.accession_number),
    ).fetchone()
    if ev is None:
        raise RuntimeError(f"Event not found: {event_key}")

    if get_validation_status(conn, event_key.issuer_cik, ev.get("ticker")) == "invalid":
        _set_trend_missing(conn, event_key, reason="ticker_validation_failed")
        return

    # Prefer the earliest open-market trade date when present. This avoids anchoring
    # the trend on non-open-market rows (e.g., grants, exercises, withholding) that
    # may have earlier dates in the same filing.
    trade_date = ev["event_trade_date"]
    try:
        open_mkt_dates: List[str] = []
        if int(ev.get("has_buy") or 0) == 1 and ev.get("buy_trade_date"):
            open_mkt_dates.append(str(ev["buy_trade_date"]))
        if int(ev.get("has_sell") or 0) == 1 and ev.get("sell_trade_date"):
            open_mkt_dates.append(str(ev["sell_trade_date"]))
        if open_mkt_dates:
            trade_date = min(open_mkt_dates)
    except Exception:
        pass
    if not trade_date:
        _set_trend_missing(conn, event_key, reason="missing_event_trade_date")
        return

    series = _load_prices(conn, event_key.issuer_cik)
    if not series:
        _set_trend_missing(conn, event_key, reason="missing_price_series")
        return

    dates = [d for d, _ in series]
    closes = [c for _, c in series]

    # anchor index = first date >= trade_date
    i = None
    for idx, d in enumerate(dates):
        if d >= trade_date:
            i = idx
            break
    if i is None:
        _set_trend_missing(conn, event_key, reason="anchor_not_found")
        return

    # Require enough lookback for SMA200 and 52w window.
    if i < 199:
        _set_trend_missing(conn, event_key, reason="insufficient_history_for_sma200")
        return
    if i < 251:
        _set_trend_missing(conn, event_key, reason="insufficient_history_for_52w")
        return
    if i < 60:
        _set_trend_missing(conn, event_key, reason="insufficient_history_for_60d")
        return
    if i < 20:
        _set_trend_missing(conn, event_key, reason="insufficient_history_for_20d")
        return

    anchor_date = dates[i]
    close_anchor = closes[i]

    close_20 = closes[i - 20]
    close_60 = closes[i - 60]
    ret_20 = (close_anchor / close_20) - 1.0
    ret_60 = (close_anchor / close_60) - 1.0

    window_52w = closes[i - 251 : i + 1]
    high_52 = max(window_52w)
    low_52 = min(window_52w)
    dist_high = (close_anchor / high_52) - 1.0
    dist_low = (close_anchor / low_52) - 1.0

    sma50 = mean(closes[i - 49 : i + 1])
    sma200 = mean(closes[i - 199 : i + 1])
    above50 = 1 if close_anchor > sma50 else 0
    above200 = 1 if close_anchor > sma200 else 0

    now = utcnow_iso()
    conn.execute(
        """
        UPDATE insider_events
        SET trend_anchor_trading_date=?, trend_close=?,
            trend_ret_20d=?, trend_ret_60d=?,
            trend_dist_52w_high=?, trend_dist_52w_low=?,
            trend_above_sma_50=?, trend_above_sma_200=?,
            trend_missing_reason=NULL,
            trend_computed_at=?
        WHERE issuer_cik=? AND owner_key=? AND accession_number=?
        """,
        (
            anchor_date,
            close_anchor,
            ret_20,
            ret_60,
            dist_high,
            dist_low,
            above50,
            above200,
            now,
            event_key.issuer_cik,
            event_key.owner_key,
            event_key.accession_number,
        ),
    )

    _debug(f"Trend computed for {event_key}: anchor={anchor_date} ret_20={ret_20:.3f} ret_60={ret_60:.3f}")


def _load_prices(conn: Any, issuer_cik: str) -> List[Tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, adj_close FROM issuer_prices_daily WHERE issuer_cik=? ORDER BY date ASC",
        (issuer_cik,),
    ).fetchall()
    return [(r["date"], float(r["adj_close"])) for r in rows]


def _set_trend_missing(conn: Any, event_key: EventKey, reason: str) -> None:
    now = utcnow_iso()
    conn.execute(
        """
        UPDATE insider_events
        SET trend_anchor_trading_date=NULL,
            trend_close=NULL,
            trend_ret_20d=NULL,
            trend_ret_60d=NULL,
            trend_dist_52w_high=NULL,
            trend_dist_52w_low=NULL,
            trend_above_sma_50=NULL,
            trend_above_sma_200=NULL,
            trend_missing_reason=?,
            trend_computed_at=?
        WHERE issuer_cik=? AND owner_key=? AND accession_number=?
        """,
        (reason, now, event_key.issuer_cik, event_key.owner_key, event_key.accession_number),
    )
    _debug(f"Trend missing for {event_key}: {reason}")
