"""Hand-checkable tests for the point-in-time rules (no database needed).

    python -m pytest tests -q

These mirror research/tests/test_build.py: the same scenarios, run against the production
functions, so the product and the research pipeline agree on what "point-in-time" means.
"""
from datetime import date, timedelta

import pytest

from insider_platform.compute.clusters import is_countable_insider, pit_cluster_members
from insider_platform.compute.market_cap_pit import (
    SharesHistory,
    dedupe_share_rows,
    event_price,
    pit_market_cap,
)
from insider_platform.compute.outcomes import find_entry_index, forward_outcome
from insider_platform.compute.stats import prior_track_record, summarize


def _series(start, n, first=100.0, step=1.0):
    """n consecutive calendar days, price rising by `step` a day: 100, 101, 102..."""
    d0 = date.fromisoformat(start)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(n)]
    return dates, [first + step * i for i in range(n)]


def _approx(x):
    return pytest.approx(x, rel=1e-12, abs=1e-12)


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
def test_entry_is_the_day_after_filing_and_exit_is_h_days_later():
    dates, px = _series("2020-01-01", 30)                          # price = 100 + day index
    bdates, bpx = _series("2020-01-01", 30, first=200.0, step=0.0)  # flat benchmark
    r = forward_outcome(dates, px, bdates, bpx, "2020-01-05", "buy", horizons=(10,))
    assert r["missing_reason"] is None
    assert r["anchor_date"] == "2020-01-06"                        # NOT the filing day
    assert r["future_date_10d"] == "2020-01-16"
    assert r["p0"] == 105.0
    assert r["return_10d"] == _approx(115 / 105 - 1)
    assert r["excess_return_10d"] == _approx(115 / 105 - 1)        # benchmark was flat


def test_filing_day_close_is_never_the_entry_even_with_a_timestamped_filing_date():
    dates, px = _series("2020-01-01", 30)
    assert find_entry_index(dates, "2020-01-05") == (5, None)
    assert find_entry_index(dates, "2020-01-05T21:15:00Z") == (5, None)
    # Filed on a Saturday with no weekend prices -> Monday.
    wk = ["2020-01-03", "2020-01-06", "2020-01-07"]
    assert find_entry_index(wk, "2020-01-04") == (1, None)


def test_benchmark_uses_the_same_calendar_dates_even_if_the_stock_has_gaps():
    dates, px = _series("2020-01-01", 60)
    keep = list(range(0, 10)) + list(range(30, 60))                # stock missing 20 days
    sd, sp = [dates[i] for i in keep], [px[i] for i in keep]
    bdates, bpx = _series("2020-01-01", 60, first=100.0, step=1.0)
    r = forward_outcome(sd, sp, bdates, bpx, "2020-01-05", "buy", horizons=(10,))
    # entry Jan 6 (index 5), exit 10 ROWS later = index 15 of the gappy series = Feb 5
    assert r["future_date_10d"] == "2020-02-05"
    assert r["bench_return_10d"] == _approx(r["return_10d"])       # benchmark measured Jan 6 -> Feb 5 too
    assert r["excess_return_10d"] == _approx(0.0)


def test_benchmark_with_a_missing_day_uses_its_last_close_on_or_before_each_date():
    dates, px = _series("2020-01-01", 30)
    bdates, bpx = _series("2020-01-01", 30, first=100.0, step=1.0)
    del bdates[5], bpx[5]                                          # benchmark has no Jan 6 close
    r = forward_outcome(dates, px, bdates, bpx, "2020-01-05", "buy", horizons=(10,))
    assert r["bench_return_10d"] == _approx(115 / 104 - 1)         # Jan 5 close -> Jan 16 close


def test_stale_benchmark_series_is_reported_not_silently_shortened():
    dates, px = _series("2020-01-01", 30)
    bdates, bpx = _series("2020-01-01", 12)                        # benchmark stops Jan 12
    r = forward_outcome(dates, px, bdates, bpx, "2020-01-05", "buy", horizons=(10,))
    assert r["return_10d"] is not None
    assert r["bench_return_10d"] is None
    assert r["bench_missing_reason_10d"] == "insufficient_benchmark_future_data"


def test_sell_side_keeps_the_production_sign_convention():
    dates, px = _series("2020-01-01", 30)
    bdates, bpx = _series("2020-01-01", 30, first=200.0, step=0.0)
    r = forward_outcome(dates, px, bdates, bpx, "2020-01-05", "sell", horizons=(10,))
    # A rising stock after an insider SELL is a loss for the signal.
    assert r["return_10d"] == _approx((105 - 115) / 105)
    assert r["excess_return_10d"] == _approx((105 - 115) / 105)


def test_short_series_is_not_matured():
    dates, px = _series("2020-01-01", 12)
    r = forward_outcome(dates, px, dates, px, "2020-01-05", "buy", horizons=(60,))
    assert r["missing_reason"] is None
    assert r["missing_reason_60d"] == "insufficient_future_data"
    assert r["excess_return_60d"] is None


def test_filing_after_the_series_ended_or_long_before_it_started_has_no_entry():
    dates, px = _series("2020-01-01", 12)
    assert forward_outcome(dates, px, dates, px, "2020-03-01", "buy", horizons=(5,))["missing_reason"] == "anchor_not_found"
    # First price is months after the filing: more than the 7-day entry gap.
    assert forward_outcome(dates, px, dates, px, "2019-06-01", "buy", horizons=(5,))["missing_reason"] == "entry_gap_too_large"
    # Exactly 7 days later is still an entry.
    assert find_entry_index(dates, "2019-12-25") == (0, None)
    assert find_entry_index(dates, "2019-12-24") == (None, "entry_gap_too_large")


# --------------------------------------------------------------------------- #
# Track records
# --------------------------------------------------------------------------- #
def test_track_record_only_counts_trades_that_had_already_finished():
    # (filing, exit, excess) for one insider
    trades = [("2020-01-01", "2020-04-01", 0.10),
              ("2020-02-01", "2020-05-01", -0.05),
              ("2020-06-01", "2020-09-01", 0.02)]
    out = prior_track_record([(x, e) for _, x, e in trades], [f for f, _, _ in trades])
    # Trade 2 was filed Feb 1 while trade 1 was still open (exit Apr 1): no record yet.
    assert [n for n, _, _ in out] == [0, 0, 2]
    assert [w for _, w, _ in out] == [0, 0, 1]
    assert out[2][2] == _approx(0.05)
    assert summarize(*out[2]) == (0.5, _approx(0.025))


def test_track_record_excludes_a_trade_that_exits_on_the_filing_date():
    out = prior_track_record([("2020-04-01", 0.1)], ["2020-04-01", "2020-04-02"])
    assert [n for n, _, _ in out] == [0, 1]


def test_track_record_ignores_unmatured_trades():
    out = prior_track_record([(None, None), ("2020-03-01", None)], ["2021-01-01"])
    assert out == [(0, 0, 0.0)]
    assert summarize(0, 0, 0.0) == (None, None)


# --------------------------------------------------------------------------- #
# Clusters
# --------------------------------------------------------------------------- #
def _n_other(members, owner):
    return [len({owner[j] for j in m}) for m in members]


def test_cluster_counts_only_other_insiders_who_filed_earlier():
    issuer = ["x", "x", "x", "x", "y"]
    owner = ["a", "b", "a", "c", "a"]
    filing = ["2020-01-01", "2020-01-10", "2020-01-12", "2020-03-01", "2020-01-10"]
    out = _n_other(pit_cluster_members(issuer, owner, filing, window_days=14), owner)
    # a (Jan 1): nobody yet, even though b files 9 days LATER.  b: sees a.  a again: sees b.
    # c (Mar 1): window empty.  issuer y: separate company.
    assert out == [0, 1, 1, 0, 0]


def test_cluster_window_includes_the_same_day_and_exactly_14_days_back():
    issuer = ["x", "x", "x"]
    owner = ["a", "b", "c"]
    filing = ["2020-01-01", "2020-01-15", "2020-01-15"]
    out = _n_other(pit_cluster_members(issuer, owner, filing, window_days=14), owner)
    assert out == [0, 2, 2]


def test_cluster_ignores_co_filers_on_the_same_form_and_funds():
    issuer = ["x", "x", "x", "x"]
    owner = ["fundA", "fundB", "ceo", "director"]
    filing = ["2020-01-02", "2020-01-02", "2020-01-05", "2020-01-08"]
    accession = ["f1", "f1", "f2", "f3"]
    is_person = [False, False, True, True]
    out = _n_other(pit_cluster_members(issuer, owner, filing, window_days=14,
                                       accession=accession, countable=is_person), owner)
    # The two fund entities filed jointly: they are not each other's "cluster".
    # The CEO sees no earlier officer/director; the director sees the CEO only.
    assert out == [0, 0, 0, 1]


def test_ten_percent_holder_only_filers_are_not_countable():
    assert is_countable_insider(None, 0, 0, 1) is False                 # fund
    assert is_countable_insider("Chief Executive Officer", 0, 0, 1) is True
    assert is_countable_insider(None, 1, 0, 1) is True                  # officer who is also 10%
    assert is_countable_insider(None, 0, 1, None) is True               # director
    assert is_countable_insider(None, None, None, None) is True         # "other"


# --------------------------------------------------------------------------- #
# Market cap
# --------------------------------------------------------------------------- #
def test_market_cap_uses_only_share_counts_filed_before_the_form4():
    hist = SharesHistory([("2020-02-01", 1e7), ("2020-06-15", 5e7)])
    assert pit_market_cap(hist.as_of("2020-03-01")[0], 10.0) == 1e8    # Feb report x $10
    assert hist.as_of("2020-06-15") == (1e7, "2020-02-01")              # the report filed the SAME day is not yet usable
    assert hist.as_of("2020-06-16") == (5e7, "2020-06-15")
    assert hist.as_of(None) == (None, None)                             # blank date
    assert SharesHistory([]).as_of("2020-06-15") == (None, None)        # company with no share data


def test_market_cap_ignores_share_counts_older_than_about_18_months():
    hist = SharesHistory([("2020-01-01", 1e7)])
    assert hist.as_of("2021-07-04")[0] == 1e7                           # 550 days
    assert hist.as_of("2021-07-05") == (None, None)                     # 551 days


def test_implausible_market_caps_are_dropped():
    assert pit_market_cap(1e5, 5.0) is None                             # $500K: unit error
    assert pit_market_cap(1e12, 10.0) is None                           # $10T
    assert pit_market_cap(None, 10.0) is None
    assert pit_market_cap(1e7, None) is None


def test_share_rows_keep_the_latest_period_per_filed_date():
    rows = [{"filed": "2020-02-01", "period_end": "2019-12-31", "shares": 1.0},
            {"filed": "2020-02-01", "period_end": "2020-01-25", "shares": 2.0},
            {"filed": "2020-05-01", "period_end": "2020-04-20", "shares": 3.0},
            {"filed": "2020-05-01", "period_end": "2020-04-20", "shares": 4.0}]   # tie: later row wins
    out = dedupe_share_rows(rows)
    assert [(r["filed"], r["shares"]) for r in out] == [("2020-02-01", 2.0), ("2020-05-01", 4.0)]


def test_event_price_is_the_reported_trade_price():
    ev = {"has_buy": 1, "buy_vwap_price": 12.5, "has_sell": 1, "sell_vwap_price": 13.0}
    assert event_price(ev) == 12.5
    assert event_price(ev, "sell") == 13.0
    assert event_price({"has_buy": 0, "has_sell": 1, "sell_vwap_price": 9.0}) == 9.0
    assert event_price({"has_buy": 1, "buy_vwap_price": None}) is None
