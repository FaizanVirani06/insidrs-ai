"""Point-in-time market cap for insider events.

market cap at filing = shares outstanding from the latest 10-Q/10-K filed BEFORE the Form 4
                       x the price the insider reported paying (vwap of the reported trades)

Both inputs were public on the filing date. The EODHD `market_cap_cache` is a current snapshot:
fine for a ticker page ("the company today"), but applied to an old event it leaks the stock's
later performance (a stock that later crashed looks "small" at the time of the trade).

Same definition as research/build_dataset.py `add_pit_market_cap` + research/fetch_shares.py.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from insider_platform.compute.market_cap import _bucket_market_cap
from insider_platform.config import Config
from insider_platform.sec.edgar import _throttle
from insider_platform.util.time import utcnow_iso

SEC_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
# Cover-page share count first; balance-sheet tag as a fallback.
SHARE_TAGS: Tuple[Tuple[str, str], ...] = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
)
# Ignore share counts reported more than ~18 months before the filing.
MAX_SHARES_AGE_DAYS = 550
# Outside this range the product of shares x price is almost always a unit error.
MIN_PLAUSIBLE_MCAP = 1e6
MAX_PLAUSIBLE_MCAP = 5e12


def _debug(msg: str) -> None:
    print(f"[mcap_pit] {msg}")


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
def dedupe_share_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One share count per filed date: the one with the latest period_end (ties: later in input).

    Same as research: sort by (filed, period_end) stably, keep the last row per filed date.
    """
    ordered = sorted(enumerate(rows), key=lambda t: (str(t[1]["filed"]), str(t[1].get("period_end") or ""), t[0]))
    by_filed: Dict[str, Dict[str, Any]] = {}
    for _, r in ordered:
        by_filed[str(r["filed"])] = r
    return [by_filed[k] for k in sorted(by_filed)]


class SharesHistory:
    """Reported shares outstanding for one issuer, by the date the report was filed."""

    def __init__(self, rows: Sequence[Tuple[str, float]]):
        clean = sorted((str(f)[:10], float(s)) for f, s in rows if f and s is not None and float(s) > 0)
        self._filed = [f for f, _ in clean]
        self._shares = [s for _, s in clean]

    def as_of(self, filing_date: Any, *, max_age_days: int = MAX_SHARES_AGE_DAYS) -> Tuple[Optional[float], Optional[str]]:
        """(shares, filed_date) from the latest report filed STRICTLY before `filing_date`.

        A report filed the same day as the Form 4 is not used (order within the day is unknown).
        """
        fd_s = str(filing_date or "")[:10]
        try:
            fd = date.fromisoformat(fd_s)
        except ValueError:
            return None, None
        k = bisect_left(self._filed, fd_s) - 1
        if k < 0:
            return None, None
        filed = self._filed[k]
        if (fd - date.fromisoformat(filed)).days > max_age_days:
            return None, None
        return self._shares[k], filed


def pit_market_cap(shares: Optional[float], price: Optional[float]) -> Optional[float]:
    """shares x price, or None if either is missing or the product is implausible."""
    if shares is None or price is None:
        return None
    try:
        m = float(shares) * float(price)
    except (TypeError, ValueError):
        return None
    if not (MIN_PLAUSIBLE_MCAP < m < MAX_PLAUSIBLE_MCAP):
        return None
    return m


def event_price(ev: Dict[str, Any], side: Optional[str] = None) -> Optional[float]:
    """The price the insider reported: the side's vwap (buy first when no side is given)."""
    sides = (side,) if side else ("buy", "sell")
    for s in sides:
        if int(ev.get(f"has_{s}") or 0) == 1:
            p = ev.get(f"{s}_vwap_price")
            if isinstance(p, (int, float)) and p > 0:
                return float(p)
    return None


# --------------------------------------------------------------------------- #
# SEC download
# --------------------------------------------------------------------------- #
def _fetch_concept_rows(cfg: Config, cik10: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Rows from the first share-count tag the company reports (research/fetch_shares.py)."""
    for taxonomy, tag in SHARE_TAGS:
        url = SEC_CONCEPT_URL.format(cik=cik10, taxonomy=taxonomy, tag=tag)
        _throttle(cfg.SEC_MIN_INTERVAL_SECONDS)
        r = requests.get(url, headers={"User-Agent": cfg.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}, timeout=60)
        if r.status_code == 404:  # company never reported this tag
            continue
        if r.status_code != 200:
            raise RuntimeError(f"SEC companyconcept request failed {r.status_code} for {url}")
        units = (r.json().get("units") or {}).get("shares") or []
        rows = []
        for x in units:
            try:
                val = float(x.get("val"))
            except (TypeError, ValueError):
                continue
            if x.get("filed") and val > 0:
                rows.append({"filed": str(x["filed"])[:10], "period_end": x.get("end"), "shares": val})
        if rows:
            return rows, f"{taxonomy}:{tag}"
    return [], None


def fetch_and_store_shares_outstanding(conn: Any, cfg: Config, issuer_cik: str) -> int:
    """Download SEC-reported shares outstanding for one issuer into issuer_shares_outstanding."""
    cik10 = str(issuer_cik).zfill(10)
    rows, source = _fetch_concept_rows(cfg, cik10)
    rows = dedupe_share_rows(rows)
    now = utcnow_iso()

    conn.execute("DELETE FROM issuer_shares_outstanding WHERE issuer_cik=?", (cik10,))
    for r in rows:
        conn.execute(
            """
            INSERT INTO issuer_shares_outstanding (issuer_cik, filed, period_end, shares, source_tag, fetched_at)
            VALUES (?,?,?,?,?,?)
            """,
            (cik10, r["filed"], r.get("period_end"), r["shares"], source, now),
        )
    conn.execute(
        """
        INSERT INTO issuer_shares_fetch (issuer_cik, status, source_tag, row_count, fetched_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(issuer_cik) DO UPDATE SET
            status=excluded.status, source_tag=excluded.source_tag,
            row_count=excluded.row_count, fetched_at=excluded.fetched_at
        """,
        (cik10, "ok" if rows else "empty", source, len(rows), now),
    )
    _debug(f"issuer={cik10} share counts={len(rows)} source={source}")
    return len(rows)


# --------------------------------------------------------------------------- #
# Apply to events
# --------------------------------------------------------------------------- #
def load_shares_history(conn: Any, issuer_cik: str) -> SharesHistory:
    rows = conn.execute(
        "SELECT filed, shares FROM issuer_shares_outstanding WHERE issuer_cik=? ORDER BY filed",
        (str(issuer_cik).zfill(10),),
    ).fetchall()
    return SharesHistory([(r["filed"], r["shares"]) for r in rows])


def compute_market_cap_pit_for_issuer(conn: Any, cfg: Config, issuer_cik: str) -> int:
    """Write point-in-time market cap onto every event of one issuer. Returns events updated."""
    cik10 = str(issuer_cik).zfill(10)
    hist = load_shares_history(conn, cik10)
    events = conn.execute(
        """
        SELECT issuer_cik, owner_key, accession_number, filing_date,
               has_buy, buy_vwap_price, has_sell, sell_vwap_price
        FROM insider_events WHERE issuer_cik=?
        """,
        (cik10,),
    ).fetchall()
    now = utcnow_iso()
    for ev in events:
        shares, filed = hist.as_of(ev["filing_date"])
        mcap = pit_market_cap(shares, event_price(dict(ev)))
        conn.execute(
            """
            UPDATE insider_events
            SET market_cap=?, market_cap_bucket=?, market_cap_updated_at=?,
                shares_outstanding_pit=?, shares_outstanding_filed=?, market_cap_version=?
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (
                int(round(mcap)) if mcap is not None else None,
                _bucket_market_cap(int(mcap)) if mcap is not None else None,
                now,
                shares,
                filed,
                cfg.CURRENT_MARKET_CAP_VERSION,
                ev["issuer_cik"], ev["owner_key"], ev["accession_number"],
            ),
        )
    _debug(f"issuer={cik10} events={len(events)}")
    return len(events)


def shares_fetch_is_fresh(conn: Any, cfg: Config, issuer_cik: str) -> bool:
    row = conn.execute(
        "SELECT fetched_at FROM issuer_shares_fetch WHERE issuer_cik=?",
        (str(issuer_cik).zfill(10),),
    ).fetchone()
    if row is None or not row["fetched_at"]:
        return False
    try:
        ts = datetime.fromisoformat(str(row["fetched_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - ts) < timedelta(days=cfg.SHARES_OUTSTANDING_MAX_AGE_DAYS)
