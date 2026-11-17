"""End-to-end check of the point-in-time jobs against a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL points at a database whose name contains "test"
(the tables it touches are emptied first):

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/insider_test python -m pytest tests -q
"""
from __future__ import annotations

import contextlib
import io
import os
from dataclasses import replace
from datetime import date, timedelta

import pytest

DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    "test" not in DSN.rsplit("/", 1)[-1].split("?")[0], reason="set TEST_DATABASE_URL to a *test* database"
)

TABLES = ("insider_events", "event_outcomes", "issuer_prices_daily", "benchmark_prices_daily", "clusters",
          "cluster_members", "insider_issuer_stats", "insider_event_stats", "issuer_shares_outstanding",
          "issuer_shares_fetch", "market_cap_cache", "issuer_fundamentals_cache", "jobs")
CIK = "0000000001"


def _days(start: str, n: int):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


@pytest.fixture()
def db():
    from insider_platform.config import load_config
    from insider_platform.db import connect, init_db

    cfg = replace(load_config(), DB_DSN=DSN)
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(DSN)
    with connect(DSN) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)}")
        days = _days("2020-01-01", 400)
        for i, d in enumerate(days):        # stock: +1 a day; benchmark: flat
            conn.execute("INSERT INTO issuer_prices_daily VALUES (?,?,?,?,?)", (CIK, d, 100.0 + i, "TST", "t"))
            conn.execute("INSERT INTO benchmark_prices_daily VALUES (?,?,?,?)", ("SPY.US", d, 50.0, "t"))
        # Today's snapshot says $50B: must never reach an event.
        conn.execute("INSERT INTO market_cap_cache VALUES (?,?,?,?,?)", ("TST", 50_000_000_000, "large", "eodhd", "t"))
        conn.execute("INSERT INTO issuer_shares_outstanding VALUES (?,?,?,?,?,?)", (CIK, "2020-01-20", "2019-12-31", 2e6, "dei", "t"))
        conn.execute("INSERT INTO issuer_shares_outstanding VALUES (?,?,?,?,?,?)", (CIK, "2020-04-20", "2020-03-31", 4e6, "dei", "t"))

        def ev(owner, acc, filing, *, ten=0, officer=1, price=20.0):
            conn.execute(
                """
                INSERT INTO insider_events (issuer_cik, owner_key, accession_number, ticker, filing_date,
                    owner_title, is_officer, is_director, is_ten_percent_owner,
                    has_buy, buy_trade_date, buy_shares_total, buy_dollars_total, buy_vwap_price,
                    has_sell, parse_version, event_computed_at)
                VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,0,'v','t')
                """,
                (CIK, owner, acc, "TST", filing, None, officer, 0, ten, filing, 1000.0, 1000.0 * price, price),
            )
        ev("alice", "A1", "2020-01-10")
        ev("alice", "A2", "2020-02-01")          # A1 still open (exit ~Mar 10)
        ev("alice", "A3", "2020-06-01")          # A1 and A2 have matured
        ev("fund1", "J1", "2020-05-25", ten=1, officer=0)
        ev("fund2", "J1", "2020-05-25", ten=1, officer=0)   # co-filer on the same form
        ev("bob", "B1", "2020-05-28")
    yield cfg


def test_jobs_are_point_in_time(db):
    from insider_platform.ai.judge import build_ai_input
    from insider_platform.compute.clusters import compute_clusters_for_ticker
    from insider_platform.compute.market_cap_pit import compute_market_cap_pit_for_issuer
    from insider_platform.compute.outcomes import compute_outcomes_for_event
    from insider_platform.compute.stats import compute_stats_for_owner_issuer, get_event_stats
    from insider_platform.db import connect
    from insider_platform.models import EventKey, OwnerIssuerKey

    cfg = db
    with contextlib.redirect_stdout(io.StringIO()), connect(DSN) as conn:
        keys = [EventKey(CIK, r["owner_key"], r["accession_number"])
                for r in conn.execute("SELECT owner_key, accession_number FROM insider_events").fetchall()]
        for k in keys:
            compute_outcomes_for_event(conn, cfg, k)
        for o in {k.owner_key for k in keys}:
            compute_stats_for_owner_issuer(conn, cfg, OwnerIssuerKey(CIK, o))
        compute_clusters_for_ticker(conn, cfg, "TST")
        compute_market_cap_pit_for_issuer(conn, cfg, CIK)

    with connect(DSN) as conn:
        # Outcomes: entry is the day AFTER the filing; benchmark over the same dates (flat -> 0).
        o = conn.execute("SELECT * FROM event_outcomes WHERE accession_number='A1'").fetchone()
        assert o["anchor_trading_date"] == "2020-01-11"
        assert o["future_date_60d"] == "2020-03-11"
        assert o["p0"] == 110.0
        assert o["return_60d"] == pytest.approx(170 / 110 - 1)
        assert o["bench_return_60d"] == pytest.approx(0.0)
        assert o["outcomes_version"] == cfg.CURRENT_OUTCOMES_VERSION

        # Stats: A1 sees nothing (its own trade is open); A2 sees nothing (A1 still open); A3 sees A1+A2.
        st = {acc: get_event_stats(conn, cfg, CIK, "alice", acc, fd)["buy"]
              for acc, fd in (("A1", "2020-01-10"), ("A2", "2020-02-01"), ("A3", "2020-06-01"))}
        assert [st[a]["eligible_n_60d"] for a in ("A1", "A2", "A3")] == [0, 0, 2]
        assert st["A3"]["win_rate_60d"] == 1.0
        assert st["A3"]["eligible_n_180d"] == 0          # 180-day holds still open on Jun 1
        lifetime = conn.execute("SELECT eligible_n_60d FROM insider_issuer_stats WHERE owner_key='alice' AND side='buy'").fetchone()
        assert lifetime["eligible_n_60d"] == 3            # the as-of-today table still counts everything

        # Clusters: funds on one form are not a cluster; bob sees no countable earlier insider
        # (only the funds); alice's A3 sees bob (Jun 1 - May 28 = 4 days).
        flags = {(r["owner_key"], r["accession_number"]): r["cluster_flag_buy"]
                 for r in conn.execute("SELECT owner_key, accession_number, cluster_flag_buy FROM insider_events").fetchall()}
        assert flags == {("alice", "A1"): 0, ("alice", "A2"): 0, ("alice", "A3"): 1,
                         ("fund1", "J1"): 0, ("fund2", "J1"): 0, ("bob", "B1"): 0}
        c = conn.execute("SELECT c.* FROM clusters c JOIN insider_events e ON e.cluster_id_buy=c.cluster_id "
                         "WHERE e.accession_number='A3'").fetchone()
        assert c["unique_insiders"] == 2 and c["window_end_date"] == "2020-06-01"

        # Market cap: latest share count filed BEFORE the Form 4 x reported price; never the snapshot.
        mc = {r["accession_number"]: r for r in conn.execute(
            "SELECT accession_number, market_cap, shares_outstanding_filed, market_cap_bucket FROM insider_events "
            "WHERE owner_key='alice'").fetchall()}
        assert mc["A1"]["market_cap"] is None                         # no 10-Q filed before Jan 10
        assert mc["A2"]["market_cap"] == 40_000_000                   # 2M shares x $20
        assert mc["A3"]["market_cap"] == 80_000_000                   # 4M shares (Apr 20 report) x $20
        assert mc["A3"]["market_cap_bucket"] == "micro"

        # AI input sees the point-in-time numbers only.
        ai = build_ai_input(conn, cfg, EventKey(CIK, "alice", "A2"))
        assert ai["insider_stats"]["buy"]["eligible_n_60d"] == 0
        assert ai["issuer_context"]["market_cap"] == 40_000_000
        assert ai["issuer_context"]["market_cap_as_of"] == "2020-01-20"
        assert ai["event"]["buy"]["trade_value_pct_market_cap"] == pytest.approx(20_000 / 40_000_000 * 100)
        assert "market_cap" not in (ai["issuer_context"].get("fundamentals") or {})
