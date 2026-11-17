from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from insider_platform.config import Config
from insider_platform.models import EventKey
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[aggregate] {msg}")


def aggregate_accession(conn: Any, cfg: Config, accession_number: str) -> List[EventKey]:
    """Aggregate raw Form4 rows for an accession into insider_events (one per owner_key)."""
    _debug(f"Aggregating accession {accession_number}")

    filing = conn.execute(
        "SELECT issuer_cik, filing_date FROM filings WHERE accession_number=?",
        (accession_number,),
    ).fetchone()
    if filing is None:
        raise RuntimeError(f"No filings row found for accession {accession_number}")

    issuer_cik = filing["issuer_cik"]
    filing_date = filing["filing_date"]

    issuer = conn.execute(
        "SELECT current_ticker FROM issuer_master WHERE issuer_cik=?",
        (issuer_cik,),
    ).fetchone()
    ticker = issuer["current_ticker"] if issuer is not None else None

    # Event market cap is point-in-time and written by COMPUTE_MARKET_CAP_PIT_FOR_ISSUER
    # (compute/market_cap_pit.py). Never copy today's market_cap_cache snapshot onto an event.
    market_cap = None
    market_cap_bucket = None
    market_cap_updated_at = None

    owner_keys = [
        r["owner_key"]
        for r in conn.execute(
            "SELECT DISTINCT owner_key FROM form4_rows_raw WHERE accession_number=? AND issuer_cik=?",
            (accession_number, issuer_cik),
        ).fetchall()
    ]
    event_keys: List[EventKey] = []

    for owner_key in owner_keys:
        event_key = EventKey(issuer_cik=issuer_cik, owner_key=owner_key, accession_number=accession_number)
        event_keys.append(event_key)

        rows = conn.execute(
            """
            SELECT * FROM form4_rows_raw
            WHERE accession_number=? AND issuer_cik=? AND owner_key=?
            """,
            (accession_number, issuer_cik, owner_key),
        ).fetchall()

        if not rows:
            continue

        # Owner display fields from the first row
        first = rows[0]
        owner_cik = first["owner_cik"]
        owner_name_display = first["owner_name_raw"] or first["owner_name_normalized"]

        # Relationship/title from raw_payload_json (best-effort)
        owner_title = None
        is_officer = None
        is_director = None
        is_ten = None
        try:
            payload = json.loads(first["raw_payload_json"]) if first["raw_payload_json"] else {}
            ro = (payload.get("reporting_owner") or {})
            owner_title = ro.get("officer_title")
            is_officer = ro.get("is_officer")
            is_director = ro.get("is_director")
            is_ten = ro.get("is_ten_percent_owner")
        except Exception:
            pass

        # Counts
        derivative_row_count = sum(1 for r in rows if int(r["is_derivative"]) == 1)
        non_open_market_row_count = sum(
            1
            for r in rows
            if int(r["is_derivative"]) == 0 and (r["transaction_code"] not in ("P", "S"))
        )

        buy_roll = _rollup_side(rows, code="P")
        sell_roll = _rollup_side(rows, code="S")

        # event_trade_date should reflect the earliest *open-market* activity when present.
        # This improves downstream trend/outcomes anchoring and avoids being skewed by
        # grants/exercises/withholding rows that can appear earlier in the same filing.
        open_market_dates: List[str] = []
        if buy_roll.get("has") and buy_roll.get("trade_date"):
            open_market_dates.append(str(buy_roll.get("trade_date")))
        if sell_roll.get("has") and sell_roll.get("trade_date"):
            open_market_dates.append(str(sell_roll.get("trade_date")))

        if open_market_dates:
            event_trade_date = min(open_market_dates)
        else:
            # Fallback: earliest transaction date anywhere in the filing.
            all_dates = [r["transaction_date"] for r in rows if r["transaction_date"]]
            event_trade_date = min(all_dates) if all_dates else None

        now = utcnow_iso()

        # Upsert insider_events. We intentionally clear derived computed fields to force recomputation.
        conn.execute(
            """
            INSERT INTO insider_events (
                issuer_cik, owner_key, accession_number,
                ticker, filing_date, event_trade_date,
                owner_cik, owner_name_display, owner_title,
                is_officer, is_director, is_ten_percent_owner,

                has_buy, buy_trade_date, buy_last_tx_date,
                buy_shares_total, buy_dollars_total, buy_vwap_price,
                buy_priced_shares_total, buy_unpriced_shares_total, buy_vwap_is_partial,
                buy_shares_owned_following, buy_pct_holdings_change, buy_pct_change_missing_reason,

                has_sell, sell_trade_date, sell_last_tx_date,
                sell_shares_total, sell_dollars_total, sell_vwap_price,
                sell_priced_shares_total, sell_unpriced_shares_total, sell_vwap_is_partial,
                sell_shares_owned_following, sell_pct_holdings_change, sell_pct_change_missing_reason,

                non_open_market_row_count, derivative_row_count,

                parse_version, event_computed_at,
                trend_computed_at, outcomes_computed_at, stats_computed_at, cluster_computed_at, ai_computed_at,
                trend_anchor_trading_date, trend_close, trend_ret_20d, trend_ret_60d, trend_dist_52w_high, trend_dist_52w_low,
                trend_above_sma_50, trend_above_sma_200, trend_missing_reason,
                cluster_flag_buy, cluster_id_buy, cluster_flag_sell, cluster_id_sell,
                ai_buy_rating, ai_sell_rating, ai_confidence, ai_model_id, ai_prompt_version, ai_generated_at,
                market_cap, market_cap_bucket, market_cap_updated_at
            ) VALUES (
                ?,?,?,
                ?,?, ?,
                ?,?,?,
                ?,?, ?,

                ?, ?,?,
                ?,?,?,
                ?,?,?,
                ?,?, ?,

                ?, ?,?,
                ?,?,?,
                ?,?,?,
                ?,?, ?,

                ?, ?,

                ?, ?,
                NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL,
                NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL, NULL,
                ?, ?, ?
            )
            ON CONFLICT(issuer_cik, owner_key, accession_number) DO UPDATE SET
                ticker=excluded.ticker,
                filing_date=excluded.filing_date,
                event_trade_date=excluded.event_trade_date,

                owner_cik=excluded.owner_cik,
                owner_name_display=excluded.owner_name_display,
                owner_title=excluded.owner_title,
                is_officer=excluded.is_officer,
                is_director=excluded.is_director,
                is_ten_percent_owner=excluded.is_ten_percent_owner,

                has_buy=excluded.has_buy,
                buy_trade_date=excluded.buy_trade_date,
                buy_last_tx_date=excluded.buy_last_tx_date,
                buy_shares_total=excluded.buy_shares_total,
                buy_dollars_total=excluded.buy_dollars_total,
                buy_vwap_price=excluded.buy_vwap_price,
                buy_priced_shares_total=excluded.buy_priced_shares_total,
                buy_unpriced_shares_total=excluded.buy_unpriced_shares_total,
                buy_vwap_is_partial=excluded.buy_vwap_is_partial,
                buy_shares_owned_following=excluded.buy_shares_owned_following,
                buy_pct_holdings_change=excluded.buy_pct_holdings_change,
                buy_pct_change_missing_reason=excluded.buy_pct_change_missing_reason,

                has_sell=excluded.has_sell,
                sell_trade_date=excluded.sell_trade_date,
                sell_last_tx_date=excluded.sell_last_tx_date,
                sell_shares_total=excluded.sell_shares_total,
                sell_dollars_total=excluded.sell_dollars_total,
                sell_vwap_price=excluded.sell_vwap_price,
                sell_priced_shares_total=excluded.sell_priced_shares_total,
                sell_unpriced_shares_total=excluded.sell_unpriced_shares_total,
                sell_vwap_is_partial=excluded.sell_vwap_is_partial,
                sell_shares_owned_following=excluded.sell_shares_owned_following,
                sell_pct_holdings_change=excluded.sell_pct_holdings_change,
                sell_pct_change_missing_reason=excluded.sell_pct_change_missing_reason,

                non_open_market_row_count=excluded.non_open_market_row_count,
                derivative_row_count=excluded.derivative_row_count,

                parse_version=excluded.parse_version,
                event_computed_at=excluded.event_computed_at,

                -- Clear derived fields to force recompute (except AI, which is expensive and only regenerated explicitly
                -- or for poller-discovered new filings).
                trend_computed_at=NULL,
                outcomes_computed_at=NULL,
                stats_computed_at=NULL,
                cluster_computed_at=NULL,

                trend_anchor_trading_date=NULL,
                trend_close=NULL,
                trend_ret_20d=NULL,
                trend_ret_60d=NULL,
                trend_dist_52w_high=NULL,
                trend_dist_52w_low=NULL,
                trend_above_sma_50=NULL,
                trend_above_sma_200=NULL,
                trend_missing_reason=NULL,

                cluster_flag_buy=NULL,
                cluster_id_buy=NULL,
                cluster_flag_sell=NULL,
                cluster_id_sell=NULL,

                -- Keep the point-in-time market cap (recomputed after aggregation)
                market_cap=COALESCE(excluded.market_cap, insider_events.market_cap),
                market_cap_bucket=COALESCE(excluded.market_cap_bucket, insider_events.market_cap_bucket),
                market_cap_updated_at=COALESCE(excluded.market_cap_updated_at, insider_events.market_cap_updated_at)
            """,
            (
                issuer_cik,
                owner_key,
                accession_number,
                ticker,
                filing_date,
                event_trade_date,
                owner_cik,
                owner_name_display,
                owner_title,
                _bool_int(is_officer),
                _bool_int(is_director),
                _bool_int(is_ten),

                1 if buy_roll["has"] else 0,
                buy_roll.get("trade_date"),
                buy_roll.get("last_tx_date"),
                buy_roll.get("shares_total"),
                buy_roll.get("dollars_total"),
                buy_roll.get("vwap_price"),
                buy_roll.get("priced_shares_total"),
                buy_roll.get("unpriced_shares_total"),
                _bool_int(buy_roll.get("vwap_is_partial")),
                buy_roll.get("shares_owned_following"),
                buy_roll.get("pct_holdings_change"),
                buy_roll.get("pct_change_missing_reason"),

                1 if sell_roll["has"] else 0,
                sell_roll.get("trade_date"),
                sell_roll.get("last_tx_date"),
                sell_roll.get("shares_total"),
                sell_roll.get("dollars_total"),
                sell_roll.get("vwap_price"),
                sell_roll.get("priced_shares_total"),
                sell_roll.get("unpriced_shares_total"),
                _bool_int(sell_roll.get("vwap_is_partial")),
                sell_roll.get("shares_owned_following"),
                sell_roll.get("pct_holdings_change"),
                sell_roll.get("pct_change_missing_reason"),

                non_open_market_row_count,
                derivative_row_count,

                cfg.CURRENT_PARSE_VERSION,
                now,

                market_cap,
                market_cap_bucket,
                market_cap_updated_at,
            ),
        )

        _debug(f"Upserted insider_event {event_key} (has_buy={buy_roll['has']} has_sell={sell_roll['has']})")

    # Judgment: normalize all events for issuer to use the issuer's current ticker for consistent UI + clustering
    if ticker:
        conn.execute(
            "UPDATE insider_events SET ticker=? WHERE issuer_cik=?",
            (ticker, issuer_cik),
        )

    return event_keys


def _rollup_side(rows: List[Any], code: str) -> Dict[str, Any]:
    """Roll up open-market non-derivative transactions for one side.

    code:
      - 'P' => purchase (buy)
      - 'S' => sale (sell)

    IMPORTANT (units):
    - pct_holdings_change is stored as a PERCENT value (e.g. 190.1 means +190.1%),
      not a ratio (1.901).
    """

    side_rows = [r for r in rows if int(r["is_derivative"]) == 0 and r["transaction_code"] == code]
    if not side_rows:
        return {"has": False}

    dates = [r["transaction_date"] for r in side_rows if r["transaction_date"]]
    trade_date = min(dates) if dates else None
    last_tx_date = max(dates) if dates else None

    shares_vals = [float(r["shares_abs"]) for r in side_rows if isinstance(r["shares_abs"], (int, float))]
    shares_total = float(sum(shares_vals)) if shares_vals else None

    priced_shares_total = 0.0
    dollars_total = 0.0
    for r in side_rows:
        sh = r["shares_abs"]
        pr = r["price"]
        if isinstance(sh, (int, float)) and isinstance(pr, (int, float)) and float(pr) > 0:
            priced_shares_total += float(sh)
            dollars_total += float(sh) * float(pr)

    unpriced_shares_total = None
    if isinstance(shares_total, (int, float)):
        unpriced_shares_total = float(shares_total) - float(priced_shares_total)

    vwap_price = None
    if priced_shares_total > 0:
        vwap_price = dollars_total / priced_shares_total

    vwap_is_partial = False
    if isinstance(shares_total, (int, float)) and shares_total > 0:
        vwap_is_partial = priced_shares_total < float(shares_total)

    # shares_owned_following should come from the LAST transaction row (date, then row_id),
    # not max() (max can be wrong when multiple legs exist).
    shares_owned_following = None
    sof_rows = [r for r in side_rows if isinstance(r["shares_owned_following"], (int, float))]
    if sof_rows:

        def _sof_key(r: Any) -> tuple:
            d = r["transaction_date"] or ""
            try:
                rid = int(r["row_id"])
            except Exception:
                rid = 0
            return (d, rid)

        last_sof_row = max(sof_rows, key=_sof_key)
        shares_owned_following = float(last_sof_row["shares_owned_following"])

    pct_change = None
    pct_reason = None

    if shares_total is None or shares_total <= 0:
        pct_reason = "missing_shares_total"
    elif shares_owned_following is None:
        pct_reason = "missing_shares_owned_following"
    else:
        # Before/after math differs for buys vs sells:
        # Buy:  after = before + bought => before = after - bought
        # Sell: after = before - sold  => before = after + sold
        if code == "P":
            shares_before = float(shares_owned_following) - float(shares_total)
        elif code == "S":
            shares_before = float(shares_owned_following) + float(shares_total)
        else:
            shares_before = None

        if shares_before is None or shares_before <= 0:
            pct_reason = "nonpositive_shares_before"
        else:
            # Store as percent, not ratio
            pct_change = (float(shares_total) / float(shares_before)) * 100.0

    return {
        "has": True,
        "trade_date": trade_date,
        "last_tx_date": last_tx_date,
        "shares_total": shares_total,
        "dollars_total": dollars_total if priced_shares_total > 0 else None,
        "vwap_price": vwap_price,
        "priced_shares_total": float(priced_shares_total) if priced_shares_total > 0 else 0.0,
        "unpriced_shares_total": unpriced_shares_total,
        "vwap_is_partial": vwap_is_partial,
        "shares_owned_following": shares_owned_following,
        "pct_holdings_change": pct_change,
        "pct_change_missing_reason": pct_reason,
    }

def _min_date(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a and b:
        return min(a, b)
    return a or b


def _bool_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, bool):
        return 1 if x else 0
    if isinstance(x, (int, float)):
        return 1 if int(x) != 0 else 0
    return None
