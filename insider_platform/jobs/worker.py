from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set

from insider_platform.ai.judge import run_ai_for_event
from insider_platform.ai.settings import is_ai_classification_enabled
from insider_platform.compute.aggregate import aggregate_accession
from insider_platform.compute.clusters import compute_clusters_for_ticker
from insider_platform.compute.market_cap import fetch_and_store_market_cap
from insider_platform.compute.news import fetch_and_store_news
from insider_platform.compute.outcomes import compute_outcomes_for_event
from insider_platform.compute.prices import fetch_and_store_benchmark_prices, fetch_and_store_prices_for_issuer
from insider_platform.compute.stats import compute_stats_for_owner_issuer
from insider_platform.compute.trend import compute_trend_for_event
from insider_platform.config import Config
from insider_platform.db import connect, upsert_app_config
from insider_platform.jobs.queue import claim_next_job, enqueue_job, mark_job_deferred, mark_job_error, mark_job_success
from insider_platform.models import EventKey, OwnerIssuerKey
from insider_platform.sec.backfill import discover_form4_accessions_for_issuer
from insider_platform.sec.ingest import fetch_accession_document, parse_accession_document
from insider_platform.sec.poller import poll_sec_current_form4_and_enqueue


def _debug(msg: str) -> None:
    print(f"[worker] {msg}")

class JobDeferred(Exception):
    """Signal that a job should be put back to pending (without consuming an attempt).

    This is used for "dependency not ready yet" situations (e.g., AI waiting on stats/trend/cluster).
    """

    def __init__(self, reason: str, *, retry_after_seconds: int = 30):
        super().__init__(reason)
        self.reason = str(reason)
        self.retry_after_seconds = int(retry_after_seconds)



# Job type groupings (useful for running dedicated workers)
API_JOB_TYPES: Set[str] = {
    # SEC / network
    "FETCH_ACCESSION_DOCS",
    "INGEST_ACCESSION",  # backward-compatible alias that fetches + enqueues parse
    "FETCH_EOD_PRICES_FOR_ISSUER",
    "FETCH_MARKET_CAP_FOR_TICKER",
    "FETCH_NEWS_FOR_TICKER",
    "FETCH_BENCHMARK_PRICES",
    "BACKFILL_DISCOVER_ISSUER",
    # enqueue batch itself is DB-only, but keeping it here helps keep backfills single-role
    "BACKFILL_ENQUEUE_BATCH",
}

COMPUTE_JOB_TYPES: Set[str] = {
    "PARSE_ACCESSION_DOCS",
    "AGGREGATE_ACCESSION",
    "COMPUTE_TREND_FOR_EVENT",
    "COMPUTE_OUTCOMES_FOR_EVENT",
    "COMPUTE_STATS_FOR_OWNER_ISSUER",
    "COMPUTE_CLUSTERS_FOR_TICKER",
    "RUN_AI_FOR_EVENT",
    "REPARSE_TICKER",
}


def run_worker_forever(
    db_path: str,
    cfg: Config,
    *,
    allowed_job_types: Optional[Set[str]] = None,
    enable_poller: Optional[bool] = None,
) -> None:
    """Run a worker loop.

    If allowed_job_types is provided, the worker will only claim and execute those job types.

    enable_poller defaults to:
      - True if allowed_job_types is None or includes FETCH_ACCESSION_DOCS/INGEST_ACCESSION (API worker)
      - False otherwise
    """
    _debug(f"Worker starting; db={db_path} allowed_job_types={sorted(allowed_job_types) if allowed_job_types else 'ALL'}")

    if enable_poller is None:
        if allowed_job_types is None:
            enable_poller = True
        else:
            enable_poller = ("FETCH_ACCESSION_DOCS" in allowed_job_types) or ("INGEST_ACCESSION" in allowed_job_types)

    next_poll_mono: float = time.monotonic()

    while True:
        with connect(db_path) as conn:
            # Optional: periodic SEC "current" Form 4 poller.
            if enable_poller and cfg.ENABLE_FORM4_POLLER and time.monotonic() >= next_poll_mono:
                try:
                    res = poll_sec_current_form4_and_enqueue(conn, cfg)
                    _debug(
                        f"[poller] tracked={res.get('tracked_issuers')} seen={res.get('feed_entries')} enqueued={res.get('enqueued')}"
                    )
                except Exception as e:
                    _debug(f"[poller] error: {e}")
                finally:
                    next_poll_mono = time.monotonic() + max(5, int(cfg.FORM4_POLLER_INTERVAL_SECONDS))

            job = claim_next_job(conn, allowed_job_types=allowed_job_types)
            if job is None:
                # No job; sleep a bit
                pass
            else:
                _debug(f"Running job id={job.job_id} type={job.job_type} attempts={job.attempts}/{job.max_attempts}")
                try:
                    _run_job(conn, cfg, job.job_type, job.payload)
                    mark_job_success(conn, job.job_id)
                    _debug(f"Job success id={job.job_id} type={job.job_type}")
                except JobDeferred as e:
                    _debug(f"Job deferred id={job.job_id} type={job.job_type}: {e.reason}")
                    # Keep last_error for observability, but do NOT consume an attempt.
                    mark_job_deferred(conn, job.job_id, e.reason, retry_after_seconds=e.retry_after_seconds)
                except Exception as e:
                    _debug(f"Job error id={job.job_id} type={job.job_type}: {e}")
                    # For backfill jobs, persist error on the backfill row so progress is visible.
                    _maybe_mark_backfill_error(conn, job.job_type, job.payload, str(e))
                    try:
                        conn.execute("ROLLBACK")  # undo partial work before recording error
                    except Exception:
                        pass
                    mark_job_error(conn, job.job_id, str(e), retry_after_seconds=60)

        time.sleep(cfg.WORKER_POLL_SECONDS)


def _iso_after_seconds(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _maybe_mark_backfill_error(conn: Any, job_type: str, payload: Dict[str, Any], err: str) -> None:
    try:
        if job_type in ("FETCH_ACCESSION_DOCS", "INGEST_ACCESSION"):
            issuer_cik = str(payload.get("issuer_cik_hint") or payload.get("issuer_cik") or "").strip()
            acc = str(payload.get("accession_number") or "").strip()
            if issuer_cik and acc:
                conn.execute(
                    """
                    UPDATE backfill_queue
                    SET status='error', updated_at=?, last_error=?
                    WHERE issuer_cik=? AND accession_number=?
                    """,
                    (_iso_after_seconds(0), err[:1000], issuer_cik.zfill(10), acc),
                )
        if job_type == "PARSE_ACCESSION_DOCS":
            acc = str(payload.get("accession_number") or "").strip()
            if acc:
                doc = conn.execute(
                    "SELECT issuer_cik FROM filing_documents WHERE accession_number=?",
                    (acc,),
                ).fetchone()
                if doc is not None and doc["issuer_cik"]:
                    issuer_cik = str(doc["issuer_cik"]).zfill(10)
                    conn.execute(
                        """
                        UPDATE backfill_queue
                        SET status='error', updated_at=?, last_error=?
                        WHERE issuer_cik=? AND accession_number=?
                        """,
                        (_iso_after_seconds(0), err[:1000], issuer_cik, acc),
                    )
    except Exception:
        # Never let bookkeeping failures break the worker
        return


def _run_job(conn: Any, cfg: Config, job_type: str, payload: Dict[str, Any]) -> None:
    # -------------------------------------------------------------------------
    # INGESTION: split into fetch (API-bound) + parse (compute-bound)
    # -------------------------------------------------------------------------
    if job_type in ("FETCH_ACCESSION_DOCS", "INGEST_ACCESSION"):
        accession = str(payload["accession_number"]).strip()
        issuer_cik_hint = str(payload.get("issuer_cik_hint") or payload.get("issuer_cik") or "").strip() or None
        filing_date = payload.get("filing_date")
        form_type = payload.get("form_type")
        force = bool(payload.get("force") or False)

        # IMPORTANT: We only generate AI for poller-discovered (new) filings. This flag is
        # propagated through the ingest pipeline so backfills/reparses do not trigger AI calls.
        ai_requested = bool(payload.get("ai_requested") or False)
        ingest_source = str(payload.get("ingest_source") or "").strip() or ("poller" if ai_requested else "manual")

        fetch_accession_document(
            conn,
            cfg,
            accession,
            issuer_cik_hint=issuer_cik_hint,
            filing_date_hint=str(filing_date).strip() if filing_date else None,
            form_type_hint=str(form_type).strip() if form_type else None,
            force=force,
        )

        # Enqueue parse (versioned)
        enqueue_job(
            conn,
            job_type="PARSE_ACCESSION_DOCS",
            dedupe_key=f"PARSE|{accession}|{cfg.CURRENT_PARSE_VERSION}",
            payload={
                "accession_number": accession,
                "ingest_source": ingest_source,
                "ai_requested": ai_requested,
            },
            priority=20,
            requeue_if_exists=True,
            # If a job is already pending, allow a "new filing" promotion to update payload/priority.
            promote_if_pending=True,
        )
        return

    if job_type == "PARSE_ACCESSION_DOCS":
        accession = str(payload["accession_number"]).strip()
        ai_requested = bool(payload.get("ai_requested") or False)
        ingest_source = str(payload.get("ingest_source") or "").strip() or ("poller" if ai_requested else "manual")
        res = parse_accession_document(conn, cfg, accession)

        # Enqueue aggregation next (deterministic)
        enqueue_job(
            conn,
            job_type="AGGREGATE_ACCESSION",
            dedupe_key=f"AGG|{accession}|{cfg.CURRENT_PARSE_VERSION}",
            payload={
                "accession_number": accession,
                "ingest_source": ingest_source,
                "ai_requested": ai_requested,
            },
            priority=20,
            requeue_if_exists=True,
            promote_if_pending=True,
        )

        # Also enqueue price fetch + market cap fetch + cluster compute (ticker known after parse)
        if res.issuer_cik:
            enqueue_job(
                conn,
                job_type="FETCH_EOD_PRICES_FOR_ISSUER",
                dedupe_key=f"PRICES|{res.issuer_cik}",
                payload={"issuer_cik": res.issuer_cik},
                priority=10,
                requeue_if_exists=True,
            )
        if res.ticker:
            enqueue_job(
                conn,
                job_type="FETCH_MARKET_CAP_FOR_TICKER",
                dedupe_key=f"MCAP|{res.ticker}",
                payload={"ticker": res.ticker},
                priority=15,
                requeue_if_exists=True,
            )
            enqueue_job(
                conn,
                job_type="FETCH_NEWS_FOR_TICKER",
                dedupe_key=f"NEWS|{res.ticker}",
                payload={"ticker": res.ticker},
                priority=12,
                requeue_if_exists=True,
            )
            enqueue_job(
                conn,
                job_type="COMPUTE_CLUSTERS_FOR_TICKER",
                dedupe_key=f"CLUSTERS|{res.ticker}|{cfg.CURRENT_CLUSTER_VERSION}",
                payload={"ticker": res.ticker},
                priority=30,
                requeue_if_exists=True,
            )
        return

    # -------------------------------------------------------------------------
    # BACKFILL
    # -------------------------------------------------------------------------
    if job_type == "BACKFILL_DISCOVER_ISSUER":
        issuer_cik = str(payload["issuer_cik"]).zfill(10)
        start_year = int(payload.get("start_year") or getattr(cfg, "BACKFILL_START_YEAR", 2006))
        discovered = discover_form4_accessions_for_issuer(
            conn,
            cfg,
            issuer_cik=issuer_cik,
            start_year=start_year,
        )
        _debug(f"Backfill discover issuer={issuer_cik} start_year={start_year} inserted={discovered}")

        batch_size = int(payload.get("batch_size") or getattr(cfg, "BACKFILL_BATCH_SIZE", 50))

        enqueue_job(
            conn,
            job_type="BACKFILL_ENQUEUE_BATCH",
            dedupe_key=f"BACKFILL_BATCH|{issuer_cik}|{start_year}|{cfg.CURRENT_PARSE_VERSION}",
            payload={"issuer_cik": issuer_cik, "start_year": start_year, "batch_size": batch_size},
            priority=5,
            requeue_if_exists=True,
        )
        return

    if job_type == "BACKFILL_ENQUEUE_BATCH":
        issuer_cik = str(payload["issuer_cik"]).zfill(10)
        start_year = int(payload.get("start_year") or getattr(cfg, "BACKFILL_START_YEAR", 2006))
        batch_size = int(payload.get("batch_size") or getattr(cfg, "BACKFILL_BATCH_SIZE", 50))

        rows = conn.execute(
            """
            SELECT accession_number, filing_date, form_type
            FROM backfill_queue
            WHERE issuer_cik=? AND status='pending'
            ORDER BY filing_date ASC
            LIMIT ?
            """,
            (issuer_cik, batch_size),
        ).fetchall()

        if not rows:
            _debug(f"Backfill batch complete issuer={issuer_cik}")
            return

        now = _iso_after_seconds(0)

        for r in rows:
            acc = str(r["accession_number"]).strip()
            # Mark queued (best-effort; idempotent)
            conn.execute(
                """
                UPDATE backfill_queue
                SET status='queued', updated_at=?
                WHERE issuer_cik=? AND accession_number=? AND status='pending'
                """,
                (now, issuer_cik, acc),
            )

            enqueue_job(
                conn,
                job_type="FETCH_ACCESSION_DOCS",
                dedupe_key=f"FETCH|{acc}",
                payload={
                    "accession_number": acc,
                    "issuer_cik_hint": issuer_cik,
                    "filing_date": r["filing_date"],
                    "form_type": r["form_type"],
                    "ingest_source": "backfill",
                    "ai_requested": False,
                },
                priority=5,
                requeue_if_exists=True,
            )

        # If more remain, enqueue another batch job shortly.
        remaining = conn.execute(
            "SELECT 1 FROM backfill_queue WHERE issuer_cik=? AND status='pending' LIMIT 1",
            (issuer_cik,),
        ).fetchone()
        if remaining:
            enqueue_job(
                conn,
                job_type="BACKFILL_ENQUEUE_BATCH",
                dedupe_key=f"BACKFILL_BATCH|{issuer_cik}|{start_year}|{cfg.CURRENT_PARSE_VERSION}",
                payload={"issuer_cik": issuer_cik, "start_year": start_year, "batch_size": batch_size},
                priority=5,
                run_after=_iso_after_seconds(1),
                requeue_if_exists=True,
            )
        return

    # -------------------------------------------------------------------------
    # AGGREGATION + COMPUTE
    # -------------------------------------------------------------------------
    if job_type == "AGGREGATE_ACCESSION":
        accession = str(payload["accession_number"]).strip()
        ai_requested = bool(payload.get("ai_requested") or False)
        ingest_source = str(payload.get("ingest_source") or "").strip() or ("poller" if ai_requested else "manual")

        event_keys = aggregate_accession(conn, cfg, accession)

        # For each event, compute trend + outcomes.
        # AI is *only* enqueued for poller-discovered (new) filings to keep AI API usage bounded.
        for ek in event_keys:
            enqueue_job(
                conn,
                job_type="COMPUTE_TREND_FOR_EVENT",
                dedupe_key=f"TREND|{ek.issuer_cik}|{ek.owner_key}|{ek.accession_number}|{cfg.CURRENT_TREND_VERSION}",
                payload={
                    "issuer_cik": ek.issuer_cik,
                    "owner_key": ek.owner_key,
                    "accession_number": ek.accession_number,
                },
                priority=40,
                requeue_if_exists=True,
            )

            enqueue_job(
                conn,
                job_type="COMPUTE_OUTCOMES_FOR_EVENT",
                dedupe_key=f"OUT|{ek.issuer_cik}|{ek.owner_key}|{ek.accession_number}|{cfg.CURRENT_OUTCOMES_VERSION}",
                payload={
                    "issuer_cik": ek.issuer_cik,
                    "owner_key": ek.owner_key,
                    "accession_number": ek.accession_number,
                },
                priority=50,
                requeue_if_exists=True,
            )

            if ai_requested:
                enqueue_job(
                    conn,
                    job_type="RUN_AI_FOR_EVENT",
                    dedupe_key=f"AI|{ek.issuer_cik}|{ek.owner_key}|{ek.accession_number}|{cfg.PROMPT_VERSION}",
                    payload={
                        "issuer_cik": ek.issuer_cik,
                        "owner_key": ek.owner_key,
                        "accession_number": ek.accession_number,
                        "ingest_source": ingest_source,
                        "ai_requested": True,
                    },
                    priority=200,
                    max_attempts=10,
                    # Do NOT requeue by default; use the admin endpoint to regenerate AI explicitly.
                    requeue_if_exists=False,
                )
        return

    if job_type == "FETCH_EOD_PRICES_FOR_ISSUER":
        issuer_cik = str(payload["issuer_cik"]).zfill(10)
        fetch_and_store_prices_for_issuer(conn, cfg, issuer_cik)

        # Requeue trend/outcomes jobs that previously failed due to missing_price_series.
        _requeue_missing_price_dependent_jobs(conn, cfg, issuer_cik)
        return

    if job_type == "FETCH_BENCHMARK_PRICES":
        symbol = str(payload.get("symbol") or cfg.BENCHMARK_SYMBOL).strip()
        resolved = fetch_and_store_benchmark_prices(conn, cfg, symbol=symbol)
        upsert_app_config(conn, "benchmark_symbol_resolved", resolved)

        # Requeue outcomes jobs that were missing benchmark series.
        _requeue_missing_benchmark_outcomes(conn, cfg)
        return

    if job_type == "FETCH_MARKET_CAP_FOR_TICKER":
        ticker = str(payload["ticker"]).strip()
        fetch_and_store_market_cap(conn, cfg, ticker)
        return

    if job_type == "FETCH_NEWS_FOR_TICKER":
        ticker = str(payload["ticker"]).strip()
        fetch_and_store_news(conn, cfg, ticker)
        return


    if job_type == "COMPUTE_TREND_FOR_EVENT":
        ek = EventKey(
            issuer_cik=str(payload["issuer_cik"]).zfill(10),
            owner_key=str(payload["owner_key"]),
            accession_number=str(payload["accession_number"]),
        )
        compute_trend_for_event(conn, ek)
        return

    if job_type == "COMPUTE_OUTCOMES_FOR_EVENT":
        ek = EventKey(
            issuer_cik=str(payload["issuer_cik"]).zfill(10),
            owner_key=str(payload["owner_key"]),
            accession_number=str(payload["accession_number"]),
        )
        compute_outcomes_for_event(conn, cfg, ek)

        # Outcomes update => recompute stats for this issuer+owner
        enqueue_job(
            conn,
            job_type="COMPUTE_STATS_FOR_OWNER_ISSUER",
            dedupe_key=f"STATS|{ek.issuer_cik}|{ek.owner_key}|{cfg.CURRENT_STATS_VERSION}",
            payload={"issuer_cik": ek.issuer_cik, "owner_key": ek.owner_key},
            priority=60,
            requeue_if_exists=True,
        )
        return

    if job_type == "COMPUTE_STATS_FOR_OWNER_ISSUER":
        key = OwnerIssuerKey(
            issuer_cik=str(payload["issuer_cik"]).zfill(10),
            owner_key=str(payload["owner_key"]),
        )
        compute_stats_for_owner_issuer(conn, cfg, key)
        return

    if job_type == "COMPUTE_CLUSTERS_FOR_TICKER":
        ticker = str(payload["ticker"]).strip()
        compute_clusters_for_ticker(conn, cfg, ticker)
        return

    if job_type == "RUN_AI_FOR_EVENT":
        ek = EventKey(
            issuer_cik=str(payload["issuer_cik"]).zfill(10),
            owner_key=str(payload["owner_key"]),
            accession_number=str(payload["accession_number"]),
        )
        force = bool(payload.get("force") or False)

        # Admin kill switch (Site settings). Paused jobs finish without calling Gemini and are
        # not retried later, so re-enabling never triggers a surprise backlog of paid calls.
        if not is_ai_classification_enabled(conn):
            _debug(f"AI classification paused; skipping {ek}")
            return

        # Only generate AI for poller-discovered (new) filings.
        # - Backfills/reparses historically created thousands of events and would spam the AI API.
        # - Admin can override with force=True via /admin/event/.../regenerate_ai
        ai_requested = bool(payload.get("ai_requested") or False)
        if not force and not ai_requested:
            return

        prereq = conn.execute(
            """
            SELECT ticker, trend_computed_at, stats_computed_at, cluster_computed_at
            FROM insider_events
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (ek.issuer_cik, ek.owner_key, ek.accession_number),
        ).fetchone()

        if prereq is None:
            raise RuntimeError("event_missing")

        # If prerequisites are missing, enqueue the missing work and DEFER this AI job
        # (do not consume an attempt / do not mark the job as an error).
        if prereq["stats_computed_at"] is None:
            enqueue_job(
                conn,
                job_type="COMPUTE_STATS_FOR_OWNER_ISSUER",
                dedupe_key=f"STATS|{ek.issuer_cik}|{ek.owner_key}|{cfg.CURRENT_STATS_VERSION}",
                payload={"issuer_cik": ek.issuer_cik, "owner_key": ek.owner_key},
                priority=60,
                requeue_if_exists=True,
            )
            raise JobDeferred("ai_prereq_missing_stats", retry_after_seconds=45)

        if prereq["trend_computed_at"] is None:
            enqueue_job(
                conn,
                job_type="COMPUTE_TREND_FOR_EVENT",
                dedupe_key=f"TREND|{ek.issuer_cik}|{ek.owner_key}|{ek.accession_number}|{cfg.CURRENT_TREND_VERSION}",
                payload={"issuer_cik": ek.issuer_cik, "owner_key": ek.owner_key, "accession_number": ek.accession_number},
                priority=40,
                requeue_if_exists=True,
            )
            raise JobDeferred("ai_prereq_missing_trend", retry_after_seconds=45)

        # Cluster is only required when we have a ticker (otherwise clustering isn't possible)
        if prereq["ticker"] and prereq["cluster_computed_at"] is None:
            t = str(prereq["ticker"]).strip()
            if t:
                enqueue_job(
                    conn,
                    job_type="COMPUTE_CLUSTERS_FOR_TICKER",
                    dedupe_key=f"CLUSTERS|{t}|{cfg.CURRENT_CLUSTER_VERSION}",
                    payload={"ticker": t},
                    priority=30,
                    requeue_if_exists=True,
                )
            raise JobDeferred("ai_prereq_missing_cluster", retry_after_seconds=90)

        row = conn.execute(
            """
            SELECT has_buy, has_sell
            FROM insider_events
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (ek.issuer_cik, ek.owner_key, ek.accession_number),
        ).fetchone()
        has_buy = bool(row["has_buy"]) if row else False
        has_sell = bool(row["has_sell"]) if row else False

        if has_buy or has_sell:
            run_ai_for_event(conn, cfg, ek, force=force)
        return

    # -------------------------------------------------------------------------
    # ADMIN / MAINTENANCE
    # -------------------------------------------------------------------------
    if job_type == "REPARSE_TICKER":
        ticker = str(payload["ticker"]).strip()
        _enqueue_reparse_ticker(conn, cfg, ticker)
        return

    raise RuntimeError(f"Unknown job_type: {job_type}")


def _requeue_missing_price_dependent_jobs(conn: Any, cfg: Config, issuer_cik: str) -> None:
    # Trend jobs
    trend_rows = conn.execute(
        """
        SELECT issuer_cik, owner_key, accession_number
        FROM insider_events
        WHERE issuer_cik=? AND trend_missing_reason='missing_price_series'
        """,
        (issuer_cik,),
    ).fetchall()

    # Outcomes jobs
    out_rows = conn.execute(
        """
        SELECT DISTINCT issuer_cik, owner_key, accession_number
        FROM event_outcomes
        WHERE issuer_cik=? AND (missing_reason_60d='missing_price_series' OR missing_reason_180d='missing_price_series')
        """,
        (issuer_cik,),
    ).fetchall()

    keys: Set[tuple[str, str, str]] = set()
    for r in trend_rows:
        keys.add((str(r["issuer_cik"]), str(r["owner_key"]), str(r["accession_number"])))
    for r in out_rows:
        keys.add((str(r["issuer_cik"]), str(r["owner_key"]), str(r["accession_number"])))

    for issuer_cik, owner_key, accession in keys:
        enqueue_job(
            conn,
            job_type="COMPUTE_TREND_FOR_EVENT",
            dedupe_key=f"TREND|{issuer_cik}|{owner_key}|{accession}|{cfg.CURRENT_TREND_VERSION}",
            payload={"issuer_cik": issuer_cik, "owner_key": owner_key, "accession_number": accession},
            priority=40,
            requeue_if_exists=True,
        )
        enqueue_job(
            conn,
            job_type="COMPUTE_OUTCOMES_FOR_EVENT",
            dedupe_key=f"OUT|{issuer_cik}|{owner_key}|{accession}|{cfg.CURRENT_OUTCOMES_VERSION}",
            payload={"issuer_cik": issuer_cik, "owner_key": owner_key, "accession_number": accession},
            priority=50,
            requeue_if_exists=True,
        )


def _requeue_missing_benchmark_outcomes(conn: Any, cfg: Config) -> None:
    rows = conn.execute(
        """
        SELECT DISTINCT issuer_cik, owner_key, accession_number
        FROM event_outcomes
        WHERE bench_missing_reason_60d IN (
                'missing_benchmark_series',
                'benchmark_anchor_not_found',
                'insufficient_benchmark_future_data',
                -- backward compatible (older reason strings)
                'benchmark_anchor_missing',
                'benchmark_future_missing'
              )
           OR bench_missing_reason_180d IN (
                'missing_benchmark_series',
                'benchmark_anchor_not_found',
                'insufficient_benchmark_future_data',
                -- backward compatible (older reason strings)
                'benchmark_anchor_missing',
                'benchmark_future_missing'
              )
        LIMIT 5000
        """
    ).fetchall()

    for r in rows:
        issuer_cik = str(r["issuer_cik"]).zfill(10)
        owner_key = str(r["owner_key"])
        accession = str(r["accession_number"])
        enqueue_job(
            conn,
            job_type="COMPUTE_OUTCOMES_FOR_EVENT",
            dedupe_key=f"OUT|{issuer_cik}|{owner_key}|{accession}|{cfg.CURRENT_OUTCOMES_VERSION}",
            payload={"issuer_cik": issuer_cik, "owner_key": owner_key, "accession_number": accession},
            priority=55,
            requeue_if_exists=True,
        )


def _enqueue_reparse_ticker(conn: Any, cfg: Config, ticker: str) -> None:
    """Reparse a ticker's historical accessions (used when parse_version is stale)."""
    rows = conn.execute(
        "SELECT DISTINCT accession_number FROM insider_events WHERE ticker=?",
        (ticker,),
    ).fetchall()
    accessions = [str(r["accession_number"]) for r in rows]
    _debug(f"REPARSE_TICKER ticker={ticker} accessions={len(accessions)}")

    for acc in accessions:
        doc = conn.execute(
            "SELECT 1 FROM filing_documents WHERE accession_number=? LIMIT 1",
            (acc,),
        ).fetchone()
        if doc:
            enqueue_job(
                conn,
                job_type="PARSE_ACCESSION_DOCS",
                dedupe_key=f"PARSE|{acc}|{cfg.CURRENT_PARSE_VERSION}",
                payload={"accession_number": acc, "ingest_source": "reparse", "ai_requested": False},
                priority=5,
                requeue_if_exists=True,
            )
        else:
            enqueue_job(
                conn,
                job_type="FETCH_ACCESSION_DOCS",
                dedupe_key=f"FETCH|{acc}",
                payload={"accession_number": acc, "ingest_source": "reparse", "ai_requested": False},
                priority=5,
                requeue_if_exists=True,
            )
