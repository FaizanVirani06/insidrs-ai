from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from insider_platform.config import Config
from insider_platform.util.hashing import sha256_hex
from insider_platform.util.time import utcnow_iso

# Other insiders' trades (same side) FILED in the previous N calendar days, up to and including
# the event's own filing date, form its cluster.
CLUSTER_WINDOW_DAYS = 14
# The flag is set when at least this many OTHER countable insiders filed in that window.
MIN_OTHER_INSIDERS = 1


def _debug(msg: str) -> None:
    print(f"[clusters] {msg}")


@dataclass
class Candidate:
    issuer_cik: str
    owner_key: str
    accession_number: str
    filing_date: str
    trade_date: str
    dollars: float
    is_exec: bool
    pct_change: float | None
    countable: bool = True


_CEO = re.compile(r"\b(ceo|chief executive)\b", re.I)
_CFO = re.compile(r"\b(cfo|chief financial)\b", re.I)


def is_countable_insider(title: Any, is_officer: Any, is_director: Any, is_ten_percent_owner: Any) -> bool:
    """False for a 10% holder with no officer/director role (mostly funds), True otherwise.

    Mirrors research/build_dataset.py `role_of(...) != "ten_pct_owner"`.
    """
    t = title if isinstance(title, str) else ""
    if _CEO.search(t) or _CFO.search(t):
        return True
    if _as_int(is_officer) == 1 or _as_int(is_director) == 1:
        return True
    return _as_int(is_ten_percent_owner) != 1


def _as_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def pit_cluster_members(
    issuer: Sequence[str],
    owner: Sequence[str],
    filing_date: Sequence[str],
    *,
    window_days: int = CLUSTER_WINDOW_DAYS,
    accession: Optional[Sequence[str]] = None,
    countable: Optional[Sequence[bool]] = None,
) -> List[List[int]]:
    """For each filing, the indices of OTHER insiders' filings that make up its cluster.

    A filing j counts toward filing i when it is at the same issuer, was filed in
    [filing_date_i - window_days, filing_date_i] (never later), is by a different insider,
    is on a different accession (co-filers on one joint form are one decision), and
    is countable (not a 10%-holder-only filer).

    Same rule as research/build_dataset.py `cluster_pit`; that function returns
    len({owner[j] for j in members[i]}).
    """
    n = len(issuer)
    acc = list(accession) if accession is not None else [str(i) for i in range(n)]
    ok = list(countable) if countable is not None else [True] * n
    fd = [date.fromisoformat(str(d)[:10]) for d in filing_date]
    out: List[List[int]] = [[] for _ in range(n)]

    groups: Dict[str, List[int]] = {}
    for i in range(n):
        groups.setdefault(issuer[i], []).append(i)
    for idx in groups.values():
        idx.sort(key=lambda k: fd[k])
        ds = [fd[k] for k in idx]
        for k in idx:
            lo = bisect_left(ds, fd[k] - timedelta(days=window_days))
            hi = bisect_right(ds, fd[k])
            out[k] = [
                j for j in idx[lo:hi]
                if ok[j] and acc[j] != acc[k] and owner[j] != owner[k]
            ]
    return out


def compute_clusters_for_ticker(conn: Any, cfg: Config, ticker: str) -> None:
    t = (ticker or "").strip()
    if not t:
        raise RuntimeError("Ticker blank for cluster computation")

    _debug(f"Recomputing clusters for ticker={t}")

    for side in ("buy", "sell"):
        _compute_side_clusters(conn, cfg, ticker=t, side=side)

    # Mark that clustering was computed for all events of this ticker (for AI gating)
    conn.execute(
        "UPDATE insider_events SET cluster_computed_at=? WHERE ticker=?",
        (utcnow_iso(), t),
    )


def _compute_side_clusters(conn: Any, cfg: Config, ticker: str, side: str) -> None:
    """Compute point-in-time cluster flags for one side (cluster_v3).

    Each event gets its OWN cluster: the event plus every countable insider at the same issuer
    who filed a same-side open-market trade in the CLUSTER_WINDOW_DAYS days up to and including
    the event's filing date (see `pit_cluster_members`). Later filings never change an earlier
    event's flag, so what a user saw on the filing date is what the flag still says.

    Before v3, clusters were non-overlapping 14-day windows over trade dates that included
    filings made after the event, and every entity on one joint fund filing counted as a
    separate insider.
    """
    candidates = _load_candidates(conn, ticker, side)
    _debug(f"ticker={ticker} side={side} candidates={len(candidates)}")

    flag_col, id_col = ("cluster_flag_buy", "cluster_id_buy") if side == "buy" else ("cluster_flag_sell", "cluster_id_sell")

    # Reset flags for this ticker+side to 0 (deterministic)
    conn.execute(f"UPDATE insider_events SET {flag_col}=0, {id_col}=NULL WHERE ticker=?", (ticker,))

    # Delete old cluster records for this ticker+side
    conn.execute(
        "DELETE FROM cluster_members WHERE cluster_id IN (SELECT cluster_id FROM clusters WHERE ticker=? AND side=?)",
        (ticker, side),
    )
    conn.execute("DELETE FROM clusters WHERE ticker=? AND side=?", (ticker, side))

    if len(candidates) < 2:
        return

    members = pit_cluster_members(
        [c.issuer_cik for c in candidates],
        [c.owner_key for c in candidates],
        [c.filing_date for c in candidates],
        window_days=CLUSTER_WINDOW_DAYS,
        accession=[c.accession_number for c in candidates],
        countable=[c.countable for c in candidates],
    )
    now = utcnow_iso()

    for i, ev in enumerate(candidates):
        others = members[i]
        other_owners = {candidates[j].owner_key for j in others}
        if len(other_owners) < MIN_OTHER_INSIDERS:
            continue

        group = [ev] + [candidates[j] for j in others]
        total_dollars = sum(float(c.dollars or 0.0) for c in group)
        execs_involved = any(c.is_exec for c in group)
        pct_vals = [c.pct_change for c in group if isinstance(c.pct_change, (int, float))]
        max_pct = max(pct_vals) if pct_vals else None
        window_start = min(c.filing_date for c in group)
        window_end = ev.filing_date

        event_ref = f"{ev.issuer_cik}|{ev.owner_key}|{ev.accession_number}"
        cluster_id = f"clu|{ticker}|{side}|{window_end}|{sha256_hex(event_ref)[:12]}"

        conn.execute(
            """
            INSERT INTO clusters (
                cluster_id, ticker, issuer_cik, side,
                window_start_date, window_end_date,
                unique_insiders, total_dollars, execs_involved, max_pct_holdings_change,
                cluster_version, computed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cluster_id, ticker, ev.issuer_cik, side,
                window_start, window_end,
                len(other_owners) + 1, total_dollars, 1 if execs_involved else 0, max_pct,
                cfg.CURRENT_CLUSTER_VERSION, now,
            ),
        )
        for c in group:
            conn.execute(
                """
                INSERT INTO cluster_members (
                    cluster_id, issuer_cik, owner_key, accession_number, side,
                    trade_date, dollars_contributed, pct_holdings_change
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
                """,
                (cluster_id, c.issuer_cik, c.owner_key, c.accession_number, side,
                 c.trade_date, c.dollars, c.pct_change),
            )

        conn.execute(
            f"""
            UPDATE insider_events
            SET {flag_col}=1, {id_col}=?
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (cluster_id, ev.issuer_cik, ev.owner_key, ev.accession_number),
        )

        _debug(
            f"Built cluster {cluster_id} ticker={ticker} side={side} insiders={len(other_owners) + 1} "
            f"dollars={total_dollars:.0f} window={window_start}->{window_end}"
        )


def _load_candidates(conn: Any, ticker: str, side: str) -> List[Candidate]:
    p = "buy" if side == "buy" else "sell"
    rows = conn.execute(
        f"""
        SELECT issuer_cik, owner_key, accession_number, filing_date,
               {p}_trade_date AS trade_date,
               COALESCE({p}_dollars_total, 0) AS dollars,
               owner_title,
               is_officer, is_director, is_ten_percent_owner,
               {p}_pct_holdings_change AS pct_change
        FROM insider_events
        WHERE ticker=? AND has_{p}=1 AND {p}_trade_date IS NOT NULL AND filing_date IS NOT NULL
        """,
        (ticker,),
    ).fetchall()

    out: List[Candidate] = []
    for r in rows:
        fd = str(r["filing_date"] or "")[:10]
        try:
            date.fromisoformat(fd)
        except ValueError:
            continue
        out.append(
            Candidate(
                issuer_cik=r["issuer_cik"],
                owner_key=r["owner_key"],
                accession_number=r["accession_number"],
                filing_date=fd,
                trade_date=r["trade_date"],
                dollars=float(r["dollars"] or 0.0),
                is_exec=(_as_int(r["is_officer"]) == 1 or _as_int(r["is_director"]) == 1),
                pct_change=(float(r["pct_change"]) if isinstance(r["pct_change"], (int, float)) else None),
                countable=is_countable_insider(
                    r["owner_title"], r["is_officer"], r["is_director"], r["is_ten_percent_owner"]
                ),
            )
        )
    out.sort(key=lambda c: (c.filing_date, c.accession_number, c.owner_key))
    return out
