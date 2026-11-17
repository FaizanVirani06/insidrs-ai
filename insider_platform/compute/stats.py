from __future__ import annotations

from bisect import bisect_left
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from insider_platform.config import Config
from insider_platform.models import OwnerIssuerKey
from insider_platform.util.time import utcnow_iso

HORIZONS: Tuple[int, ...] = (60, 180)
SIDES: Tuple[str, ...] = ("buy", "sell")


def _debug(msg: str) -> None:
    print(f"[stats] {msg}")


def _day(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()[:10]
    return s if len(s) == 10 else None


# --------------------------------------------------------------------------- #
# Pure point-in-time logic (mirrors research/build_dataset.py `prior_track_record`)
# --------------------------------------------------------------------------- #
class TrackRecord:
    """Matured outcomes of one insider/issuer/side/horizon, sorted by exit date.

    `as_of(filing_date)` returns the track record that was knowable on `filing_date`:
    only trades whose holding period had already ENDED (exit_date < filing_date) count.
    A trade that was still open on the filing date (including the trade being rated, and
    any later trade) is excluded.
    """

    def __init__(self, records: Iterable[Tuple[Any, Any]]):
        done = []
        for exit_date, excess in records:
            d = _day(exit_date)
            if d is None or excess is None:
                continue
            done.append((d, float(excess)))
        done.sort(key=lambda r: r[0])
        self._exits = [d for d, _ in done]
        self._cum_wins = [0]
        self._cum_sum = [0.0]
        for _, x in done:
            self._cum_wins.append(self._cum_wins[-1] + (1 if x > 0 else 0))
            self._cum_sum.append(self._cum_sum[-1] + x)

    def as_of(self, filing_date: Any) -> Tuple[int, int, float]:
        """(n, wins, sum_excess) over trades with exit_date strictly before filing_date."""
        fd = _day(filing_date)
        if fd is None:
            return 0, 0, 0.0
        k = bisect_left(self._exits, fd)
        return k, self._cum_wins[k], self._cum_sum[k]


def prior_track_record(
    records: Iterable[Tuple[Any, Any]], filing_dates: Sequence[Any]
) -> List[Tuple[int, int, float]]:
    """For each filing date, (n, wins, sum_excess) from `records` = [(exit_date, excess), ...]
    whose exit_date is strictly before that filing date."""
    tr = TrackRecord(records)
    return [tr.as_of(fd) for fd in filing_dates]


def summarize(n: int, wins: int, total: float) -> Tuple[Optional[float], Optional[float]]:
    """(win_rate, avg_excess_return) or (None, None) when there is no matured trade."""
    if n <= 0:
        return None, None
    return wins / n, total / n


def _stats_payload(by_h: Dict[int, Tuple[int, int, float]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for h in HORIZONS:
        n, w, s = by_h[h]
        rate, avg = summarize(n, w, s)
        out[f"eligible_n_{h}d"] = n
        out[f"wins_{h}d"] = w
        out[f"win_rate_{h}d"] = rate
        out[f"avg_return_{h}d"] = avg
    return out


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def _load_track_records(conn: Any, issuer_cik: str, owner_key: str) -> Dict[Tuple[str, int], TrackRecord]:
    rows = conn.execute(
        """
        SELECT side, future_date_60d, excess_return_60d, future_date_180d, excess_return_180d
        FROM event_outcomes
        WHERE issuer_cik=? AND owner_key=?
        """,
        (issuer_cik, owner_key),
    ).fetchall()
    out: Dict[Tuple[str, int], TrackRecord] = {}
    for side in SIDES:
        side_rows = [r for r in rows if r["side"] == side]
        for h in HORIZONS:
            out[(side, h)] = TrackRecord(
                (r[f"future_date_{h}d"], r[f"excess_return_{h}d"]) for r in side_rows
            )
    return out


def compute_stats_for_owner_issuer(conn: Any, cfg: Config, key: OwnerIssuerKey) -> None:
    """Recompute issuer-specific insider performance stats from event_outcomes.

    stats_v3:
    - `insider_event_stats` (one row per event x side): the insider's track record AS OF that
      event's filing date. Only trades whose holding period ended before the filing date count,
      so the trade being rated and later trades never leak in. This is what per-event displays
      and the AI input use.
    - `insider_issuer_stats` (one row per owner x issuer x side): the record as of today, over
      every matured trade. Not point-in-time; do not attach it to a past event.

    Averages are of **excess returns** (trade_return - benchmark_return), sign-adjusted by side.
    """
    now = utcnow_iso()
    records = _load_track_records(conn, key.issuer_cik, key.owner_key)

    # ---- point-in-time, per event ----------------------------------------
    events = conn.execute(
        "SELECT accession_number, filing_date FROM insider_events WHERE issuer_cik=? AND owner_key=?",
        (key.issuer_cik, key.owner_key),
    ).fetchall()
    conn.execute(
        "DELETE FROM insider_event_stats WHERE issuer_cik=? AND owner_key=?",
        (key.issuer_cik, key.owner_key),
    )
    for ev in events:
        as_of = _day(ev["filing_date"])
        for side in SIDES:
            p = _stats_payload({h: records[(side, h)].as_of(as_of) for h in HORIZONS})
            conn.execute(
                """
                INSERT INTO insider_event_stats (
                    issuer_cik, owner_key, accession_number, side, as_of_date,
                    eligible_n_60d, wins_60d, win_rate_60d, avg_return_60d,
                    eligible_n_180d, wins_180d, win_rate_180d, avg_return_180d,
                    stats_version, computed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key.issuer_cik, key.owner_key, ev["accession_number"], side, as_of,
                    p["eligible_n_60d"], p["wins_60d"], p["win_rate_60d"], p["avg_return_60d"],
                    p["eligible_n_180d"], p["wins_180d"], p["win_rate_180d"], p["avg_return_180d"],
                    cfg.CURRENT_STATS_VERSION, now,
                ),
            )

    # ---- as of today (lifetime) ------------------------------------------
    for side in SIDES:
        p = _stats_payload({h: records[(side, h)].as_of("9999-12-31") for h in HORIZONS})
        conn.execute(
            """
            INSERT INTO insider_issuer_stats (
                issuer_cik, owner_key, side,
                eligible_n_60d, win_rate_60d, avg_return_60d,
                eligible_n_180d, win_rate_180d, avg_return_180d,
                stats_version, computed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(issuer_cik, owner_key, side) DO UPDATE SET
                eligible_n_60d=excluded.eligible_n_60d,
                win_rate_60d=excluded.win_rate_60d,
                avg_return_60d=excluded.avg_return_60d,
                eligible_n_180d=excluded.eligible_n_180d,
                win_rate_180d=excluded.win_rate_180d,
                avg_return_180d=excluded.avg_return_180d,
                stats_version=excluded.stats_version,
                computed_at=excluded.computed_at
            """,
            (
                key.issuer_cik, key.owner_key, side,
                p["eligible_n_60d"], p["win_rate_60d"], p["avg_return_60d"],
                p["eligible_n_180d"], p["win_rate_180d"], p["avg_return_180d"],
                cfg.CURRENT_STATS_VERSION, now,
            ),
        )

    _debug(f"Stats computed issuer={key.issuer_cik} owner={key.owner_key} events={len(events)}")

    # Mark events for this owner+issuer as having stats computed (for AI gating/UI transparency)
    conn.execute(
        """
        UPDATE insider_events
        SET stats_computed_at=?
        WHERE issuer_cik=? AND owner_key=?
        """,
        (now, key.issuer_cik, key.owner_key),
    )


def get_event_stats(
    conn: Any,
    cfg: Config,
    issuer_cik: str,
    owner_key: str,
    accession_number: str,
    filing_date: Any,
) -> Dict[str, Dict[str, Any]]:
    """Point-in-time insider stats for one event, keyed by side ('buy'/'sell').

    Reads `insider_event_stats` when it is at the current stats version; otherwise computes the
    same numbers directly from event_outcomes. Never falls back to the look-ahead lifetime table.
    """
    rows = conn.execute(
        """
        SELECT * FROM insider_event_stats
        WHERE issuer_cik=? AND owner_key=? AND accession_number=? AND stats_version=?
        """,
        (issuer_cik, owner_key, accession_number, cfg.CURRENT_STATS_VERSION),
    ).fetchall()
    as_of = _day(filing_date)
    stored = {r["side"]: r for r in rows}
    if all(s in stored for s in SIDES) and all(stored[s]["as_of_date"] == as_of for s in SIDES):
        out = {}
        for s in SIDES:
            r = stored[s]
            out[s] = {"side": s, "as_of_date": r["as_of_date"]}
            out[s].update({
                k: r[k] for h in HORIZONS
                for k in (f"eligible_n_{h}d", f"wins_{h}d", f"win_rate_{h}d", f"avg_return_{h}d")
            })
        return out

    records = _load_track_records(conn, issuer_cik, owner_key)
    out = {}
    for s in SIDES:
        out[s] = {"side": s, "as_of_date": as_of}
        out[s].update(_stats_payload({h: records[(s, h)].as_of(as_of) for h in HORIZONS}))
    return out
