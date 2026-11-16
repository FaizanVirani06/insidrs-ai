"""Download each company's reported shares outstanding from the SEC (free, official).

Why: market cap must be known AS OF the filing date.  The production table
only has today's market cap, and rescaling it by the price change since then
quietly uses the stock's future return (a look-ahead leak).  Instead:

    market cap at filing = shares outstanding from the latest 10-Q/10-K filed
                           BEFORE the Form 4  x  the price the insider paid

Both inputs were public on the filing date.

    python -m research.fetch_shares            # resumable

Needs SEC_USER_AGENT in the environment (the SEC asks automated clients to
identify themselves); the app's existing .env value is reused.
Output: data/shares.parquet (issuer_cik, filed, period_end, shares)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

import pandas as pd
import requests

from research.common import load_config

URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
# Cover-page share count first; balance-sheet tag as a fallback.
TAGS = [("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")]


def fetch_one(session: requests.Session, cik: str) -> list[dict]:
    for taxonomy, tag in TAGS:
        for attempt in range(4):
            r = session.get(URL.format(cik=cik.zfill(10), taxonomy=taxonomy, tag=tag), timeout=30)
            if r.status_code in (429, 500, 502, 503):        # rate limited / busy: wait and retry
                time.sleep(5 * (attempt + 1))
                continue
            break
        if r.status_code == 404:                             # company never reported this tag
            continue
        r.raise_for_status()
        rows = r.json().get("units", {}).get("shares", [])
        rows = [{"issuer_cik": cik, "filed": x["filed"], "period_end": x["end"], "shares": float(x["val"])}
                for x in rows if x.get("filed") and x.get("val") and float(x["val"]) > 0]
        if rows:
            return rows
    return []


def main() -> None:
    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not agent:
        raise SystemExit("Set SEC_USER_AGENT (the SEC requires a contact string for automated requests).")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="discard earlier downloads and start over")
    args = ap.parse_args()
    parts, state_path = data / "shares_parts", data / "shares_state.json"
    if args.refresh:
        shutil.rmtree(parts, ignore_errors=True)
        state_path.unlink(missing_ok=True)
    parts.mkdir(exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": [], "empty": []}

    ciks = sorted(pd.read_parquet(data / "events.parquet", columns=["issuer_cik"])["issuer_cik"].dropna().unique())
    todo = [c for c in ciks if c not in set(state["done"])]
    print(f"[shares] {len(ciks):,} companies, {len(todo):,} still to download")
    session = requests.Session()
    session.headers.update({"User-Agent": agent, "Accept-Encoding": "gzip, deflate"})

    buf: list[dict] = []
    for i, cik in enumerate(todo, 1):
        try:
            rows = fetch_one(session, cik)
        except requests.RequestException as e:
            print(f"[shares] stopped at {cik}: {e}. Rerun to resume.")
            break
        buf += rows
        state["done"].append(cik)
        if not rows:
            state["empty"].append(cik)
        time.sleep(0.15)                                     # stay well under the SEC's 10 requests/second
        if i % 200 == 0 or i == len(todo):
            if buf:
                pd.DataFrame(buf).to_parquet(parts / f"part_{int(time.time() * 1000)}.parquet", index=False)
                buf = []
            state_path.write_text(json.dumps(state))
            print(f"[shares] {i:,}/{len(todo):,}  no data for {len(state['empty']):,}")

    files = sorted(parts.glob("part_*.parquet"))
    if not files:
        raise SystemExit("[shares] nothing downloaded")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df = df.dropna(subset=["filed"]).sort_values(["issuer_cik", "filed", "period_end"])
    df = df.drop_duplicates(["issuer_cik", "filed"], keep="last")      # one value per filing date
    df.to_parquet(data / "shares.parquet", index=False)
    print(f"[shares] wrote {len(df):,} rows for {df['issuer_cik'].nunique():,} companies; "
          f"{len(state['empty']):,} companies have no reported share count")


if __name__ == "__main__":
    main()
