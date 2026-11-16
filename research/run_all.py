"""Run the whole pipeline end to end. Meant for a monthly scheduled job.

    python -m research.run_all                 # refresh data, rebuild, rerun every analysis
    python -m research.run_all --skip-fetch    # reuse the downloaded prices and share counts

Stops at the first failing step, so a failed download never produces results
from half-updated data.  Output of each run goes to output/logs/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys

from research.common import load_config

FETCH = [["research.extract"], ["research.fetch_prices", "--refresh"], ["research.fetch_shares", "--refresh"]]
REST = [["research.build_dataset"], ["research.sanity_check"], ["research.analysis.q1_ratings"],
        ["research.analysis.q2_track_records"], ["research.analysis.q3_features"],
        ["research.analysis.q4_sells"], ["research.analysis.robustness"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args()
    out = load_config()["paths"]["output_dir"]
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    steps = ([["research.extract"]] if args.skip_fetch else FETCH) + REST
    status = {"started": stamp, "steps": []}
    with open(logs / f"run_{stamp}.log", "w") as log:
        for step in steps:
            log.write(f"\n===== {' '.join(step)} =====\n")
            log.flush()
            code = subprocess.run([sys.executable, "-m", *step], stdout=log, stderr=subprocess.STDOUT).returncode
            status["steps"].append({"step": step[0], "ok": code == 0})
            print(f"{'ok  ' if code == 0 else 'FAIL'} {' '.join(step)}")
            if code != 0:
                break
    status["ok"] = all(s["ok"] for s in status["steps"]) and len(status["steps"]) == len(steps)
    status["finished"] = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / "last_run.json").write_text(json.dumps(status, indent=2))
    print(f"log: {logs / f'run_{stamp}.log'}")
    sys.exit(0 if status["ok"] else 1)


if __name__ == "__main__":
    main()
