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


def test_market_cap_uses_only_share_counts_filed_before_the_form4():
    import pandas as pd

    from research.build_dataset import add_pit_market_cap

    df = pd.DataFrame({"issuer_cik": ["x", "x", "x", "y"],
                       "filing_date": pd.to_datetime(["2020-03-01", "2020-06-15", None, "2020-06-15"]),
                       "vwap_price": [10.0, 10.0, 10.0, 10.0], "dollars_total": [1e5] * 4})
    shares = pd.DataFrame({"issuer_cik": ["x", "x"], "filed": pd.to_datetime(["2020-02-01", "2020-06-15"]),
                           "shares": [1e7, 5e7]})
    out = add_pit_market_cap(df, shares).set_index(["issuer_cik", "filing_date"])["mcap_pit"]
    assert out[("x", pd.Timestamp("2020-03-01"))] == 1e8      # Feb report x $10
    assert out[("x", pd.Timestamp("2020-06-15"))] == 1e8      # the report filed the SAME day is not yet usable
    assert out.isna().sum() == 2                              # blank date; company with no share data


def test_cluster_ignores_co_filers_on_the_same_form_and_funds():
    issuer = np.array(["x", "x", "x", "x"])
    owner = np.array(["fundA", "fundB", "ceo", "director"])
    filing = np.array(["2020-01-02", "2020-01-02", "2020-01-05", "2020-01-08"], dtype=D)
    accession = np.array(["f1", "f1", "f2", "f3"])
    is_person = np.array([False, False, True, True])
    out = cluster_pit(issuer, owner, filing, 14, accession=accession, countable=is_person)
    # The two fund entities filed jointly: they are not each other's "cluster".
    # The CEO sees no earlier officer/director; the director sees the CEO only.
    assert list(out) == [0, 0, 0, 1]


def test_event_windows_and_factor_car():
    import pandas as pd

    from research.build_events import issuer_windows

    dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2021-06-01"), dtype=D)
    rng = np.random.default_rng(0)
    mkt = rng.normal(0, 0.01, len(dates))
    r = 1.5 * mkt + 0.001                                          # stock = 1.5 x market + 0.1%/day
    closes = 100 * np.cumprod(1 + np.r_[0, r[1:]])
    f = pd.DataFrame({"mkt_rf": mkt, "smb": rng.normal(0, .005, len(dates)), "hml": rng.normal(0, .005, len(dates)),
                      "rmw": rng.normal(0, .005, len(dates)), "cma": rng.normal(0, .005, len(dates)),
                      "rf": 0.0, "mom": rng.normal(0, .005, len(dates))},
                     index=pd.DatetimeIndex(dates.astype("datetime64[ns]")))
    bench = (dates, np.full(len(dates), 50.0))                    # flat benchmark
    ev = pd.DataFrame({"trade_date": pd.to_datetime(["2020-12-01"]), "filing_date": pd.to_datetime(["2020-12-03"])})
    w = issuer_windows(dates, closes, f, bench, ev).iloc[0]
    it, ipre, ient = 335, 336, 338                                 # Dec 1, Dec 2, Dec 4 (day after filing)
    assert np.isclose(w["ex_iwm_B"], closes[ipre] / closes[it] - 1)
    assert np.isclose(w["ex_iwm_C"], closes[ient] / closes[ipre] - 1)
    assert np.isclose(w["ex_iwm_D20"], closes[ient + 20] / closes[ient] - 1)
    assert np.isclose(w["car_ff6_D20"], 20 * 0.001, atol=1e-9)     # betas recovered exactly -> only the 0.1%/day alpha remains
    assert np.isclose(w["car_mkt_D60"], 60 * 0.001, atol=1e-9)


def test_trader_types_use_only_earlier_filings():
    import pandas as pd

    from research.build_events import classify_traders

    hist = pd.DataFrame({"insider_id": ["a"] * 4 + ["b"] * 3, "side": ["sell", "sell", "sell", "buy", "buy", "buy", "buy"],
                         "trade_date": pd.to_datetime(["2017-03-05", "2018-03-09", "2019-03-02", "2020-02-01",
                                                       "2017-01-05", "2018-07-01", "2019-11-01"]),
                         "filing_date": pd.to_datetime(["2017-03-07", "2018-03-11", "2019-03-04", "2020-02-03",
                                                        "2017-01-07", "2018-07-03", "2021-01-01"])})
    targets = pd.DataFrame({"insider_id": ["a", "b", "c"], "trade_date": pd.to_datetime(["2020-06-01"] * 3),
                            "filing_date": pd.to_datetime(["2020-06-03"] * 3)})
    out = classify_traders(hist, targets, 24)
    # a: traded every March 2017-19 -> routine. b: the 2019 trade was filed AFTER the target -> not yet eligible.
    assert list(out["trader_type"]) == ["routine", "insufficient history", "insufficient history"]
    assert list(out["bought_in_prior_window"]) == [True, True, False]


def test_bhar_compounds_returns():
    import pandas as pd

    from research.build_events import issuer_windows

    dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2021-06-01"), dtype=D)
    rng = np.random.default_rng(1)
    mkt = rng.normal(0, 0.03, len(dates))                          # volatile market
    r = mkt                                                        # stock = market exactly: zero alpha
    closes = 100 * np.cumprod(1 + np.r_[0, r[1:]])
    zeros = np.zeros(len(dates))
    f = pd.DataFrame({"mkt_rf": mkt, "smb": rng.normal(0, .005, len(dates)), "hml": rng.normal(0, .005, len(dates)),
                      "rmw": rng.normal(0, .005, len(dates)), "cma": rng.normal(0, .005, len(dates)),
                      "rf": zeros, "mom": rng.normal(0, .005, len(dates))},
                     index=pd.DatetimeIndex(dates.astype("datetime64[ns]")))
    ev = pd.DataFrame({"trade_date": pd.to_datetime(["2020-12-01"]), "filing_date": pd.to_datetime(["2020-12-03"])})
    w = issuer_windows(dates, closes, f, (dates, np.full(len(dates), 50.0)), ev).iloc[0]
    assert abs(w["bhar_ff6_D60"]) < 1e-9                           # stock == prediction -> zero abnormal return
    assert abs(w["car_ff6_D60"]) < 1e-9


def test_first_available_price_by_acceptance_session():
    from research.analysis.realtime import first_prices

    cal = np.array(["2020-03-02", "2020-03-03", "2020-03-04", "2020-03-06"], dtype=D)   # Thu 3/5 is a holiday here
    acc_date = np.array(["2020-03-03", "2020-03-03", "2020-03-03", "2020-03-05", "2020-03-01"], dtype=D)
    acc_min = np.array([8 * 60, 11 * 60, 18 * 60, 12 * 60, 12 * 60])
    session, bd, bf, fd, ff = first_prices(cal, acc_date, acc_min)
    assert list(session) == ["pre-market", "market hours", "after close", "non-trading day", "non-trading day"]
    # pre-market Tue: Mon close -> Tue open; market hours: Tue open -> Tue close; after close: Tue close -> Wed open
    assert list(zip(bd[:3], bf[:3], fd[:3], ff[:3])) == [(0, 1, 1, 0), (1, 0, 1, 1), (1, 1, 2, 0)]
    # holiday: Wed close -> Fri open; Sunday before the calendar starts: no earlier close -> unusable
    assert (bd[3], bf[3], fd[3], ff[3]) == (2, 1, 3, 0)
    assert bd[4] == -1 and fd[4] == -1


def test_announcement_day_and_three_day_reaction():
    import pandas as pd

    from research.build_study3 import announcement_days, reaction3

    cal = np.array(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08", "2021-01-11"], dtype=D)
    acc = pd.Series(pd.to_datetime(["2021-01-06 14:00", "2021-01-06 21:30", "2021-01-09 15:00"]).tz_localize("UTC"))
    # 9:00 New York -> same day; 16:30 New York -> next day; Saturday -> Monday
    assert list(announcement_days(cal, acc).astype(str)) == ["2021-01-06", "2021-01-07", "2021-01-11"]
    closes = np.array([100, 100, 100, 110, 110, 110.0])
    bench = np.full(len(cal), 50.0)
    r = reaction3(cal, closes, cal, bench, np.array(["2021-01-07"], dtype=D))
    assert np.isclose(r[0], 0.10)                      # close of 1/05 -> close of 1/08


def test_switcher_counts_only_earlier_filings():
    import pandas as pd

    from research.build_study3 import switcher_flags

    hist = pd.DataFrame({"insider_id": ["a"] * 4, "side": ["sell", "sell", "sell", "buy"],
                         "trade_date": pd.to_datetime(["2019-01-01", "2019-06-01", "2020-01-01", "2020-05-01"]),
                         "filing_date": pd.to_datetime(["2019-01-03", "2019-06-03", "2020-01-03", "2020-08-01"])})
    t = pd.DataFrame({"insider_id": ["a"], "trade_date": pd.to_datetime(["2020-06-01"]),
                      "filing_date": pd.to_datetime(["2020-06-03"])})
    out = switcher_flags(hist, t)
    # the May 2020 buy was filed AFTER the target filing, so it does not count yet
    assert (out.iloc[0]["prior36_sells"], out.iloc[0]["prior36_buys"]) == (3, 0)
