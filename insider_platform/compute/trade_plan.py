from __future__ import annotations

"""Technicals-only trade plan (BETA).

This module generates **suggested** stop-loss / trims / take-profit levels for
BUY signals that meet the automatic AI-rating threshold.

Important constraints / notes:
  - The project currently stores only *adjusted close* prices in
    issuer_prices_daily (no OHLC). Because of that, "gap" detection is only a
    rough proxy based on close-to-close jumps.
  - This is intentionally conservative and should be treated as an
    informational aid only.
"""

import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from insider_platform.config import Config


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _round_price(p: float) -> float:
    # Keep it readable.
    if p >= 100:
        return round(p, 2)
    if p >= 10:
        return round(p, 2)
    if p >= 1:
        return round(p, 3)
    return round(p, 4)


def _dedupe_levels(levels: List[Tuple[float, str]]) -> List[Tuple[float, str]]:
    """Dedupe by near-equality (prices can collide)."""
    out: List[Tuple[float, str]] = []
    for price, label in sorted(levels, key=lambda x: x[0]):
        if not out:
            out.append((price, label))
            continue
        if abs(out[-1][0] - price) / max(1e-9, out[-1][0]) < 0.002:  # within 0.2%
            # Keep the earlier label; they're effectively the same level.
            continue
        out.append((price, label))
    return out


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return None
        return float(x)
    except Exception:
        return None


def _extract_buy_signal_strength(
    ai_output: Optional[Dict[str, Any]],
    event: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Best-effort extraction of buy rating/confidence.

    Priority:
      1) AI verdict JSON (if present)
      2) precomputed event fields (ai_buy_rating / ai_confidence)
    """

    rating: Optional[float] = None
    conf: Optional[float] = None

    if isinstance(ai_output, dict):
        verdict = ai_output.get("verdict")
        if isinstance(verdict, dict):
            buy = verdict.get("buy_signal")
            if isinstance(buy, dict):
                status = str(buy.get("status") or "").strip().lower()
                if status in ("applicable", "insufficient_data"):
                    rating = _safe_float(buy.get("rating"))
                    conf = _safe_float(buy.get("confidence"))

    if event is not None:
        # Fall back to cached event fields when AI verdict isn't present.
        if rating is None:
            rating = _safe_float(event.get("ai_buy_rating"))
        if conf is None:
            conf = _safe_float(event.get("ai_confidence"))

    return (rating, conf)


def _fetch_entry_price(
    conn: Any,
    issuer_cik: str,
    target_date: str,
) -> Optional[Dict[str, Any]]:
    """Find the first trading day on/after target_date and return {date, adj_close}."""
    row = conn.execute(
        """
        SELECT date, adj_close
        FROM issuer_prices_daily
        WHERE issuer_cik=? AND date>=?
        ORDER BY date ASC
        LIMIT 1
        """,
        (issuer_cik, target_date),
    ).fetchone()
    if row is None:
        return None
    try:
        px = float(row["adj_close"])  # type: ignore[index]
    except Exception:
        return None
    return {"date": str(row["date"]), "adj_close": px}


def _fetch_lookback_closes(
    conn: Any,
    issuer_cik: str,
    end_date: str,
    limit: int = 400,
) -> List[Tuple[str, float]]:
    """Return ascending (date, adj_close) series up to end_date (inclusive)."""
    rows = conn.execute(
        """
        SELECT date, adj_close
        FROM issuer_prices_daily
        WHERE issuer_cik=? AND date<=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (issuer_cik, end_date, int(limit)),
    ).fetchall()
    out: List[Tuple[str, float]] = []
    for r in reversed(rows):
        try:
            out.append((str(r["date"]), float(r["adj_close"])) )
        except Exception:
            continue
    return out


def compute_trade_plan_for_event(
    conn: Any,
    cfg: Config,
    event: Dict[str, Any],
    *,
    ai_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute a technicals-only trade plan for a single event.

    This function always returns a dict:
      - {eligible: True, ...levels...} when a plan can be produced
      - {eligible: False, reason: "..."} when it cannot
    """

    def _ineligible(reason: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": "trade_plan_v1",
            "beta": True,
            "eligible": False,
            "reason": reason,
        }
        if extra:
            out.update(extra)
        return out

    # Eligibility: only BUY events
    if int(event.get("has_buy") or 0) != 1:
        return _ineligible("No buy activity for this event.")

    rating, confidence = _extract_buy_signal_strength(ai_output, event)
    # Internal AI ratings are 1-10. The product UI displays the same score on a
    # 1-100 scale, so a displayed 60 maps to an internal 6.0 threshold.
    min_rating = float(getattr(cfg, "TRADE_PLAN_MIN_BUY_RATING", 6.0))
    if rating is not None and rating < min_rating:
        return _ineligible(
            "AI rating doesn't meet automatic trade plan threshold.",
            extra={
                "signal": {
                    "rating": round(float(rating), 1),
                    "confidence": _clamp(float(confidence), 0.0, 1.0) if confidence is not None else None,
                    "threshold": round(min_rating, 1),
                    "display_threshold": int(round(min_rating * 10)),
                }
            },
        )

    issuer_cik = str(event.get("issuer_cik") or "").zfill(10)
    if not issuer_cik:
        return _ineligible("Missing issuer CIK.")

    # Use trend anchor date when available; otherwise fall back.
    target_date = (
        (event.get("trend_anchor_trading_date") or "")
        or (event.get("buy_trade_date") or "")
        or (event.get("event_trade_date") or "")
        or (event.get("filing_date") or "")
    )
    target_date = str(target_date)
    try:
        # validate
        date.fromisoformat(target_date)
    except Exception:
        return _ineligible("Invalid event date for trade plan anchor.")

    entry_row = _fetch_entry_price(conn, issuer_cik, target_date)
    if entry_row is None:
        return _ineligible("Missing entry price / price history.")

    entry_date = str(entry_row["date"])
    entry = float(entry_row["adj_close"])
    if not (entry > 0):
        return _ineligible("Invalid entry price.")

    series = _fetch_lookback_closes(conn, issuer_cik, entry_date, limit=420)
    if len(series) < 40:
        # Not enough context for reasonable levels.
        return _ineligible("Insufficient price history for technical levels.")

    closes = [px for _, px in series]
    # Entry is last point.
    pre = closes[:-1]
    if len(pre) < 20:
        return _ineligible("Insufficient pre-entry history for technical levels.")

    def _window(vals: List[float], n: int) -> List[float]:
        if len(vals) <= n:
            return vals
        return vals[-n:]

    support20 = min(_window(pre, 20))
    support60 = min(_window(pre, 60)) if len(pre) >= 60 else min(pre)
    res20 = max(_window(pre, 20))
    res60 = max(_window(pre, 60)) if len(pre) >= 60 else max(pre)
    res252 = max(_window(pre, 252)) if len(pre) >= 252 else max(pre)

    # Stop-loss: use 20D low unless it's too close, else 60D low.
    buffer_pct = 0.02
    stop_basis = "20D swing low"
    stop = support20 * (1.0 - buffer_pct)
    # If stop is unrealistically tight (<2% risk), widen to 60D low.
    if entry - stop < entry * 0.02:
        stop_basis = "60D swing low"
        stop = support60 * (1.0 - buffer_pct)

    # Basic sanity
    if stop >= entry:
        return _ineligible("Could not compute a sane stop-loss level.")

    risk = entry - stop
    risk_pct = risk / entry
    # Avoid absurdly wide stops.
    if risk_pct > 0.35:
        # If we'd risk >35% from entry to stop, don't suggest anything.
        return _ineligible("Stop-loss would be too wide (>35% risk).")

    # "Liquidity gap" proxy: large down moves in closes. Treat the prior close as an overhead level.
    gap_thr = float(getattr(cfg, "TRADE_PLAN_GAP_PCT_THRESHOLD", 0.08))
    gap_levels: List[Tuple[float, str]] = []
    # Scan last ~120 sessions.
    start_idx = max(1, len(pre) - 120)
    for i in range(start_idx, len(pre)):
        prev_c = pre[i - 1]
        cur_c = pre[i]
        if prev_c <= 0:
            continue
        pct = (cur_c / prev_c) - 1.0
        if pct <= -gap_thr:
            # Down gap proxy: previous close becomes a potential "gap fill" level.
            dt = series[i][0]
            gap_levels.append((prev_c, f"Gap fill (prior close before {pct*100:.0f}% drop on {dt})"))

    # Candidate resistance levels above entry.
    levels: List[Tuple[float, str]] = []
    levels.append((res20, "Prior 20D high"))
    levels.append((res60, "Prior 60D high"))
    levels.append((res252, "52W high"))
    levels.extend(gap_levels)
    levels = [(p, lab) for (p, lab) in levels if isinstance(p, (int, float)) and p > entry * 1.01]
    levels = _dedupe_levels(levels)

    # Choose trims/TP.
    min_move_1 = max(risk * 0.8, entry * 0.03)
    min_move_2 = max(risk * 0.5, entry * 0.05)

    def _pick_next(after_price: float, min_move: float) -> Optional[Tuple[float, str]]:
        for p, lab in levels:
            if p > after_price + min_move:
                return (p, lab)
        return None

    trim1 = _pick_next(entry, min_move_1)
    if trim1 is None:
        trim1 = (entry + risk * 1.0, "1R extension")

    trim2 = _pick_next(trim1[0], min_move_2)
    if trim2 is None:
        trim2 = (entry + risk * 2.0, "2R extension")

    # Take profit: prefer a higher technical level; otherwise 3R.
    tp_pick = None
    for p, lab in reversed(levels):
        if p > trim2[0] + max(risk * 0.5, entry * 0.06):
            tp_pick = (p, lab)
            break
    if tp_pick is None:
        tp_pick = (entry + risk * 3.0, "3R extension")

    # Ensure monotonic order
    t1 = float(trim1[0])
    t2 = float(trim2[0])
    tp = float(tp_pick[0])
    if not (stop < entry < t1 < t2 < tp):
        # If technical levels came back weird, fall back to R-multiples.
        t1 = entry + risk * 1.0
        t2 = entry + risk * 2.0
        tp = entry + risk * 3.0
        trim1 = (t1, "1R extension")
        trim2 = (t2, "2R extension")
        tp_pick = (tp, "3R extension")

    notes: List[str] = [
        "BETA: Technical levels are heuristics based on daily adjusted closes only.",
        "Not investment advice. Consider liquidity, volatility, and your risk tolerance.",
    ]
    if rating is None or confidence is None:
        notes.insert(0, "AI signal not available; plan generated from technicals only.")

    return {
        "schema_version": "trade_plan_v1",
        "beta": True,
        "eligible": True,
        "reason": "ok",
        "signal": {
            "rating": round(float(rating), 1) if rating is not None else None,
            "confidence": _clamp(float(confidence), 0.0, 1.0) if confidence is not None else None,
        },
        "entry": {
            "date": entry_date,
            "price": _round_price(entry),
            "source": "adj_close",
        },
        "stop_loss": {
            "price": _round_price(stop),
            "basis": stop_basis,
        },
        "risk": {
            "per_share": _round_price(risk),
            "pct": round(risk_pct * 100.0, 1),
        },
        "trims": [
            {"price": _round_price(t1), "basis": str(trim1[1])},
            {"price": _round_price(t2), "basis": str(trim2[1])},
        ],
        "take_profit": {"price": _round_price(tp), "basis": str(tp_pick[1])},
        "levels": {
            "support_20d": _round_price(support20),
            "support_60d": _round_price(support60),
            "resistance_20d": _round_price(res20),
            "resistance_60d": _round_price(res60),
            "high_52w": _round_price(res252),
            "gap_levels": [
                {"price": _round_price(p), "label": lab}
                for (p, lab) in _dedupe_levels(gap_levels)
                if p > 0
            ][:5],
        },
        "notes": notes,
    }
