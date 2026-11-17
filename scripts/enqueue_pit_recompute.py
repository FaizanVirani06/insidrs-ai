"""Enqueue the point-in-time recomputation after the outcomes_v4 / stats_v3 / cluster_v3 /
mcap_pit_v1 version bumps.

    python scripts/enqueue_pit_recompute.py --dry-run          # counts only
    python scripts/enqueue_pit_recompute.py                    # everything still on an old version
    python scripts/enqueue_pit_recompute.py --ticker AAPL      # one ticker
    python scripts/enqueue_pit_recompute.py --only clusters    # one part

What it enqueues (only rows not already at the current version, unless --all):
  outcomes  COMPUTE_OUTCOMES_FOR_EVENT per event; each one re-enqueues the owner/issuer stats job,
            so per-event point-in-time stats (insider_event_stats) follow automatically.
  stats     COMPUTE_STATS_FOR_OWNER_ISSUER per owner/issuer (for pairs whose outcomes are already
            current but whose stats are not).
  clusters  COMPUTE_CLUSTERS_FOR_TICKER per ticker.
  mcap      FETCH_SHARES_OUTSTANDING_FOR_ISSUER per issuer (SEC download, needs the API worker);
            it enqueues COMPUTE_MARKET_CAP_PIT_FOR_ISSUER when done.

Recomputation never happens implicitly: the jobs only run after this script enqueues them
(or when new filings arrive).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insider_platform.config import load_config
from insider_platform.db import connect, init_db
from insider_platform.jobs.queue import enqueue_job

PARTS = ("outcomes", "stats", "clusters", "mcap")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=PARTS, action="append", help="Limit to these parts (repeatable)")
    p.add_argument("--ticker", type=str, default=None, help="Only events of this ticker")
    p.add_argument("--all", action="store_true", help="Also re-enqueue rows already at the current version")
    p.add_argument("--dry-run", action="store_true", help="Print counts, enqueue nothing")
    p.add_argument("--priority", type=int, default=None, help="Override job priority (higher runs sooner)")
    args = p.parse_args()
    parts = set(args.only or PARTS)

    cfg = load_config()
    init_db(cfg.DB_DSN)
    t = args.ticker.strip().upper() if args.ticker else None
    tick_sql, tick_params = (" AND e.ticker=?", [t]) if t else ("", [])

    with connect(cfg.DB_DSN) as conn:
        counts = {}

        if "outcomes" in parts:
            stale = "" if args.all else """
              AND NOT EXISTS (SELECT 1 FROM event_outcomes o
                              WHERE o.issuer_cik=e.issuer_cik AND o.owner_key=e.owner_key
                                AND o.accession_number=e.accession_number AND o.outcomes_version=?)"""
            rows = conn.execute(
                f"""
                SELECT e.issuer_cik, e.owner_key, e.accession_number FROM insider_events e
                WHERE (e.has_buy=1 OR e.has_sell=1){tick_sql}{stale}
                """,
                tuple(tick_params + ([] if args.all else [cfg.CURRENT_OUTCOMES_VERSION])),
            ).fetchall()
            counts["outcomes"] = len(rows)
            if not args.dry_run:
                for r in rows:
                    enqueue_job(
                        conn,
                        job_type="COMPUTE_OUTCOMES_FOR_EVENT",
                        dedupe_key=f"OUT|{r['issuer_cik']}|{r['owner_key']}|{r['accession_number']}|{cfg.CURRENT_OUTCOMES_VERSION}",
                        payload={"issuer_cik": r["issuer_cik"], "owner_key": r["owner_key"],
                                 "accession_number": r["accession_number"]},
                        priority=args.priority if args.priority is not None else 50,
                        requeue_if_exists=True,
                    )

        if "stats" in parts:
            stale = "" if args.all else """
              AND NOT EXISTS (SELECT 1 FROM insider_event_stats s
                              WHERE s.issuer_cik=e.issuer_cik AND s.owner_key=e.owner_key
                                AND s.accession_number=e.accession_number AND s.stats_version=?)"""
            rows = conn.execute(
                f"""
                SELECT DISTINCT e.issuer_cik, e.owner_key FROM insider_events e
                WHERE (e.has_buy=1 OR e.has_sell=1){tick_sql}{stale}
                """,
                tuple(tick_params + ([] if args.all else [cfg.CURRENT_STATS_VERSION])),
            ).fetchall()
            counts["stats"] = len(rows)
            if not args.dry_run:
                for r in rows:
                    enqueue_job(
                        conn,
                        job_type="COMPUTE_STATS_FOR_OWNER_ISSUER",
                        dedupe_key=f"STATS|{r['issuer_cik']}|{r['owner_key']}|{cfg.CURRENT_STATS_VERSION}",
                        payload={"issuer_cik": r["issuer_cik"], "owner_key": r["owner_key"]},
                        priority=args.priority if args.priority is not None else 45,
                        requeue_if_exists=True,
                    )

        if "clusters" in parts:
            stale = "" if args.all else """
              AND (NOT EXISTS (SELECT 1 FROM clusters c WHERE c.ticker=e.ticker AND c.cluster_version=?)
                   OR EXISTS (SELECT 1 FROM clusters c WHERE c.ticker=e.ticker AND c.cluster_version<>?))"""
            rows = conn.execute(
                f"""
                SELECT DISTINCT e.ticker FROM insider_events e
                WHERE e.ticker IS NOT NULL AND e.ticker<>'' AND (e.has_buy=1 OR e.has_sell=1){tick_sql}{stale}
                """,
                tuple(tick_params + ([] if args.all else [cfg.CURRENT_CLUSTER_VERSION] * 2)),
            ).fetchall()
            counts["clusters"] = len(rows)
            if not args.dry_run:
                for r in rows:
                    enqueue_job(
                        conn,
                        job_type="COMPUTE_CLUSTERS_FOR_TICKER",
                        dedupe_key=f"CLUSTERS|{r['ticker']}|{cfg.CURRENT_CLUSTER_VERSION}",
                        payload={"ticker": r["ticker"]},
                        priority=args.priority if args.priority is not None else 30,
                        requeue_if_exists=True,
                    )

        if "mcap" in parts:
            stale = "" if args.all else " AND COALESCE(e.market_cap_version,'')<>?"
            rows = conn.execute(
                f"SELECT DISTINCT e.issuer_cik FROM insider_events e WHERE 1=1{tick_sql}{stale}",
                tuple(tick_params + ([] if args.all else [cfg.CURRENT_MARKET_CAP_VERSION])),
            ).fetchall()
            counts["mcap"] = len(rows)
            if not args.dry_run:
                for r in rows:
                    enqueue_job(
                        conn,
                        job_type="FETCH_SHARES_OUTSTANDING_FOR_ISSUER",
                        dedupe_key=f"SHARES|{r['issuer_cik']}",
                        payload={"issuer_cik": r["issuer_cik"]},
                        priority=args.priority if args.priority is not None else 15,
                        requeue_if_exists=True,
                    )

    verb = "Would enqueue" if args.dry_run else "Enqueued"
    for k in PARTS:
        if k in counts:
            unit = {"outcomes": "events", "stats": "owner/issuer pairs", "clusters": "tickers", "mcap": "issuers"}[k]
            print(f"{verb} {k}: {counts[k]:,} {unit}")


if __name__ == "__main__":
    main()
