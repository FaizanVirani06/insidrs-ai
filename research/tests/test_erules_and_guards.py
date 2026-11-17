"""Hand-built price paths for E1-E3, the holdout date checks and the run guards (no database needed)."""
import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from research.analysis.erules import H, simulate

FLAT = 100.0


def path(**over):
    """A flat 61-day path at 100 (open = high = low = close), IWM flat; override single days."""
    o, h, l, c = (np.full(H + 1, FLAT) for _ in range(4))
    for name, days in over.items():
        arr = {"o": o, "h": h, "l": l, "c": c}[name]
        for k, v in days.items():
            arr[k] = v
    flat = np.full(H + 1, 50.0)
    return o, h, l, c, flat.copy(), flat.copy()


# ---- E1
def test_e1_fills_at_a_gap_down_open():
    o, h, l, c, io, ic = path(o={2: 95.0}, l={2: 94.0}, c={H: 110.0})
    r = simulate(o, h, l, c, io, ic, cost=0.01)
    assert r["e1_filled"] and r["e1_day"] == 2
    assert np.isclose(r["E1"], 110 / 95 - 1 - 0.01)           # min(open 95, L 98) = 95


def test_e1_low_touching_the_limit_does_not_fill():
    o, h, l, c, io, ic = path(l={1: 98.0, 2: 98.0, 3: 98.0}, c={H: 110.0})
    r = simulate(o, h, l, c, io, ic, cost=0.01)
    assert not r["e1_filled"]


def test_e1_unfilled_is_zero_with_no_cost_and_e1c_buys_at_t0_plus_3_close():
    o, h, l, c, io, ic = path(c={3: 104.0, H: 130.0})
    r = simulate(o, h, l, c, io, ic, cost=0.05)
    assert r["E1"] == 0.0 and r["E1_half"] == 0.0
    assert np.isclose(r["B0"], 0.30 - 0.05)
    assert np.isclose(r["E1c"], 130 / 104 - 1 - 0.05)


def test_e1_half_cost_sensitivity():
    o, h, l, c, io, ic = path(l={1: 97.0})
    r = simulate(o, h, l, c, io, ic, cost=0.02)
    assert np.isclose(r["E1"], 100 / 98 - 1 - 0.02) and np.isclose(r["E1_half"], 100 / 98 - 1 - 0.01)


# ---- E2
def test_e2_trigger_exits_at_next_days_open():
    o, h, l, c, io, ic = path(c={5: 120.0, 6: 120.0, 7: 120.0, 8: 120.0, 9: 120.0, 10: 102.0}, o={11: 101.0})
    io[11] = 55.0                                               # IWM up 10% from t0 close to that open
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["e2_fired"] and r["e2_days"] == 11                 # 102 <= 0.85 x 120 on day 10
    assert np.isclose(r["E2"], (101 / 100 - 1) - (55 / 50 - 1))


def test_e2_no_trigger_holds_to_day_60():
    o, h, l, c, io, ic = path(c={5: 110.0, 10: 94.0})          # every close >= 94 > 0.85 x 110 = 93.5
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert not r["e2_fired"] and r["E2"] == r["B0"]


# ---- E3
def test_e3_gap_through_the_stop_exits_at_the_open():
    o, h, l, c, io, ic = path(o={7: 80.0}, l={7: 79.0}, h={7: 82.0}, c={7: 81.0})
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["e3_exit"] == "stop_gap" and r["e3_days"] == 7 and np.isclose(r["E3"], 80 / 100 - 1)


def test_e3_both_levels_the_same_day_assumes_the_stop():
    o, h, l, c, io, ic = path(l={9: 84.0}, h={9: 121.0})
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["e3_exit"] == "stop" and np.isclose(r["E3"], 85 / 100 - 1)


def test_e3_neither_level_holds_to_day_60():
    o, h, l, c, io, ic = path(h={20: 119.0}, l={30: 86.0}, c={H: 105.0})
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["e3_exit"] == "none" and np.isclose(r["E3"], r["B0"]) and np.isclose(r["B0"], 0.05)


def test_e3_missing_high_or_low_cannot_trigger():
    o, h, l, c, io, ic = path(c={H: 100.0})
    l[12], h[12] = np.nan, np.nan
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["e3_exit"] == "none" and not r["invalid"]


def test_missing_execution_open_invalidates_the_signal():
    o, h, l, c, io, ic = path(l={2: 90.0})
    o[2] = np.nan
    r = simulate(o, h, l, c, io, ic, cost=0.0)
    assert r["invalid"] and np.isnan(r["B0"]) and np.isnan(r["E1"])


# ---- holdout dates
def test_stage_dates_refuse_early_opening():
    from research.analysis.study3 import check_stage_date

    with pytest.raises(SystemExit):
        check_stage_date("A", dt.date(2027, 3, 7))
    check_stage_date("A", dt.date(2027, 3, 8))
    with pytest.raises(SystemExit):
        check_stage_date("B", dt.date(2027, 9, 6))
    check_stage_date("B", dt.date(2027, 9, 7))
    check_stage_date("dev", dt.date(2026, 1, 1))


# ---- run guards
def test_analysis_refuses_without_the_clean_tree_marker(monkeypatch):
    from research.common import require_clean_commit

    monkeypatch.delenv("RESEARCH_TREE_CLEAN", raising=False)
    monkeypatch.delenv("RESEARCH_GIT_COMMIT", raising=False)
    with pytest.raises(SystemExit):
        require_clean_commit()
    monkeypatch.setenv("RESEARCH_GIT_COMMIT", "abc123")
    monkeypatch.setenv("RESEARCH_TREE_CLEAN", "1")
    assert require_clean_commit() == "abc123"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed (e.g. inside the research container)")
def test_run_sh_refuses_a_dirty_tree_and_passes_the_commit(tmp_path):
    repo = tmp_path / "repo"
    (repo / "research").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "run.sh", repo / "research" / "run.sh")
    (repo / "tracked.txt").write_text("v1\n")
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text("#!/bin/sh\necho DOCKER \"$@\"\n")
    (bindir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "SUMMARY": str(tmp_path / "s.txt")}

    clean = subprocess.run(["bash", "research/run.sh", "research.x"], cwd=repo, env=env, capture_output=True, text=True)
    head = subprocess.run(git[:3] + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert clean.returncode == 0 and f"RESEARCH_GIT_COMMIT={head}" in clean.stdout
    assert head in (tmp_path / "s.txt").read_text()

    (repo / "tracked.txt").write_text("v2\n")
    dirty = subprocess.run(["bash", "research/run.sh", "research.x"], cwd=repo, env=env, capture_output=True, text=True)
    assert dirty.returncode == 1 and "uncommitted" in dirty.stderr
