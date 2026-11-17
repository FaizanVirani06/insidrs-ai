"""Run a research module and print what the summary file needs: module, arguments, commit,
start and end time (UTC), elapsed time and peak memory.

Used by research/run.sh; not meant to be called directly.
"""
from __future__ import annotations

import datetime as dt
import os
import resource
import runpy
import sys
import time


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m research.runner <module> [args...]")
    module, args = sys.argv[1], sys.argv[2:]
    start = time.time()
    print(f"[runner] module {module} {' '.join(args)}")
    print(f"[runner] commit {os.environ.get('RESEARCH_GIT_COMMIT', 'unknown')}  "
          f"started {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC", flush=True)
    sys.argv = [module] + args
    code = 0
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if e.code not in (None, 0) and not isinstance(e.code, int):
            print(e.code, file=sys.stderr)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"[runner] finished {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC  "
          f"elapsed {(time.time() - start) / 60:.1f} min  peak memory {peak_mb:,.0f} MB  exit {code}", flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
