"""Hand-checkable tests for the return and point-in-time logic (no database needed).

    python -m pytest research/tests -q
"""
import numpy as np

from research.build_dataset import cluster_pit, forward_returns, prior_track_record

D = "datetime64[D]"


def _series(start, n, first=100.0, step=1.0):
    """n consecutive calendar days, price rising by `step` a day: 100, 101, 102..."""
    dates = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(n, "D"), dtype=D)
    return dates, first + step * np.arange(n)


def test_entry_is_the_day_after_filing_and_exit_is_h_days_later():
    dates, px = _series("2020-01-01", 30)                 # price = 100 + day index
    bdates, bpx = _series("2020-01-01", 30, first=200.0, step=0.0)   # flat benchmark
    r = forward_returns(dates, px, bdates, bpx, ["2020-01-05"], 10, global_last="2020-01-30")
    assert r["status"][0] == "ok"
    assert str(r["entry_date"][0]) == "2020-01-06"        # NOT the filing day
    assert str(r["exit_date"][0]) == "2020-01-16"
    assert np.isclose(r["ret"][0], 115 / 105 - 1)         # prices on those two days
    assert np.isclose(r["excess"][0], 115 / 105 - 1)      # benchmark was flat


def test_same_day_entry_matches_production_convention():
    dates, px = _series("2020-01-01", 30)
    r = forward_returns(dates, px, dates, px, ["2020-01-05"], 10, entry="same_day", global_last="2020-01-30")
    assert str(r["entry_date"][0]) == "2020-01-05"
    assert np.isclose(r["excess"][0], 0.0)                # stock == benchmark


def test_benchmark_uses_the_same_calendar_dates_even_if_the_stock_has_gaps():
    dates, px = _series("2020-01-01", 60)
    keep = np.r_[0:10, 30:60]                             # stock missing 20 days
    bdates, bpx = _series("2020-01-01", 60, first=100.0, step=1.0)
    r = forward_returns(dates[keep], px[keep], bdates, bpx, ["2020-01-05"], 10, global_last="2020-02-29")
    # entry Jan 6 (index 5), exit 10 ROWS later = index 15 of the gappy series = Feb 5
    assert str(r["exit_date"][0]) == "2020-02-05"
    assert np.isclose(r["bench_ret"][0], r["ret"][0])     # benchmark measured Jan 6 -> Feb 5 too
    assert np.isclose(r["excess"][0], 0.0)


def test_delisted_stock_is_kept_and_exits_at_its_last_price():
    dates, px = _series("2020-01-01", 12)                 # series stops Jan 12
    bdates, bpx = _series("2020-01-01", 400, first=100.0, step=0.0)
    r = forward_returns(dates, px, bdates, bpx, ["2020-01-05"], 60, global_last="2021-01-01")
    assert r["status"][0] == "delisted"
    assert str(r["exit_date"][0]) == "2020-01-12"
    assert np.isclose(r["ret"][0], 111 / 105 - 1)


def test_recent_filing_on_a_live_series_is_not_matured_not_delisted():
    dates, px = _series("2020-01-01", 12)
    r = forward_returns(dates, px, dates, px, ["2020-01-05"], 60, global_last="2020-01-12")
    assert r["status"][0] == "not_matured"
    assert np.isnan(r["excess"][0])


def test_filing_after_the_series_ended_has_no_entry():
    dates, px = _series("2020-01-01", 12)
    r = forward_returns(dates, px, dates, px, ["2020-03-01", "2019-06-01"], 5, global_last="2021-01-01")
    assert list(r["status"]) == ["no_entry", "no_entry"]  # after delisting / long before listing


def test_split_like_jump_inside_the_window_is_flagged():
    dates, px = _series("2020-01-01", 30, step=0.0)
    px = px.copy()
    px[15:] /= 4                                          # unadjusted 4-for-1 split
    r = forward_returns(dates, px, dates, px, ["2020-01-05", "2020-01-20"], 5, global_last="2020-01-30")
    assert list(r["suspect"]) == [False, False]           # neither window spans the break
    r = forward_returns(dates, px, dates, px, ["2020-01-12"], 5, global_last="2020-01-30")
    assert r["suspect"][0]


def test_track_record_only_counts_trades_that_had_already_finished():
    owner = np.array(["a", "a", "a", "b"])
    filing = np.array(["2020-01-01", "2020-02-01", "2020-06-01", "2020-06-01"], dtype=D)
    exit_ = np.array(["2020-04-01", "2020-05-01", "2020-09-01", "2020-09-01"], dtype=D)
    excess = np.array([0.10, -0.05, 0.02, 0.5])
    n, w, s = prior_track_record(owner, filing, exit_, excess)
    # Trade 2 was filed Feb 1 while trade 1 was still open (exit Apr 1): no record yet.
    assert list(n) == [0, 0, 2, 0]
    assert list(w) == [0, 0, 1, 0]
    assert np.isclose(s[2], 0.05)


def test_track_record_ignores_unmatured_trades():
    owner = np.array(["a", "a"])
    filing = np.array(["2020-01-01", "2021-01-01"], dtype=D)
    exit_ = np.array(["NaT", "NaT"], dtype=D)
    n, _, _ = prior_track_record(owner, filing, exit_, np.array([np.nan, np.nan]))
    assert list(n) == [0, 0]


def test_cluster_counts_only_other_insiders_who_filed_earlier():
    issuer = np.array(["x", "x", "x", "x", "y"])
    owner = np.array(["a", "b", "a", "c", "a"])
    filing = np.array(["2020-01-01", "2020-01-10", "2020-01-12", "2020-03-01", "2020-01-10"], dtype=D)
    out = cluster_pit(issuer, owner, filing, window_days=14)
    # a (Jan 1): nobody yet, even though b files 9 days LATER.  b: sees a.  a again: sees b.
    # c (Mar 1): window empty.  issuer y: separate company.
    assert list(out) == [0, 1, 1, 0, 0]
