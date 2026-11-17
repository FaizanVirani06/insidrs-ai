"""Download the exact EDGAR acceptance time of every Form 4 for the companies in the study.

    python -m research.fetch_acceptance          # resumable: rerun to continue
    python -m research.fetch_acceptance --refresh

Source: SEC submissions data (data.sec.gov/submissions/CIK##########.json plus
its older pages), which lists every filing about a company, including insiders'
Form 4s, with "acceptanceDateTime" in UTC (checked against filing headers,
which show the same instant in New York time).

Needs SEC_USER_AGENT (the SEC requires automated clients to identify themselves).
Output: data/acceptance.parquet (accession_number, acceptance_utc)
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

BASE = "https://data.sec.gov/submissions/"
OLDEST_NEEDED = "2009-06-01"          # older pages only matter if they reach into the study period


def get_json(session: requests.Session, url: str):
    for attempt in range(5):
        r = session.get(url, timeout=30)
        if r.status_code in (429, 500, 502, 503):
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    raise requests.RequestException(f"gave up on {url}")


def form4_rows(block: dict) -> list[tuple[str, str]]:
    return [(a, t) for a, t, f in zip(block.get("accessionNumber", []), block.get("acceptanceDateTime", []),
                                      block.get("form", [])) if f in ("4", "4/A") and t]


def fetch_company(session: requests.Session, cik: str) -> list[tuple[str, str]]:
    top = get_json(session, f"{BASE}CIK{cik.zfill(10)}.json")
    if top is None:
        return []
    rows = form4_rows(top.get("filings", {}).get("recent", {}))
    for page in top.get("filings", {}).get("files", []):
        if page.get("filingTo", "9999") < OLDEST_NEEDED:
            continue
        time.sleep(0.12)
        older = get_json(session, BASE + page["name"])
        if older:
            rows += form4_rows(older)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not agent:
        raise SystemExit("Set SEC_USER_AGENT (the SEC requires a contact string for automated requests).")
    parts, state_path = data / "acceptance_parts", data / "acceptance_state.json"
    if args.refresh:
        shutil.rmtree(parts, ignore_errors=True)
        state_path.unlink(missing_ok=True)
    parts.mkdir(exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}

    ciks = sorted(pd.read_parquet(data / "events.parquet", columns=["issuer_cik"])["issuer_cik"].dropna().unique())
    done = set(state["done"])
    todo = [c for c in ciks if c not in done]
    print(f"[acceptance] {len(ciks):,} companies, {len(todo):,} still to download")
    session = requests.Session()
    session.headers.update({"User-Agent": agent, "Accept-Encoding": "gzip, deflate"})

    buf: list[tuple[str, str]] = []
    for i, cik in enumerate(todo, 1):
        try:
            buf += fetch_company(session, cik)
        except requests.RequestException as e:
            print(f"[acceptance] stopped at {cik}: {e}. Rerun to resume.")
            break
        state["done"].append(cik)
        time.sleep(0.12)                                   # stay under the SEC's 10 requests/second
        if i % 200 == 0 or i == len(todo):
            if buf:
                pd.DataFrame(buf, columns=["accession_number", "acceptance_utc"]).to_parquet(
                    parts / f"part_{int(time.time() * 1000)}.parquet", index=False)
                buf = []
            state_path.write_text(json.dumps(state))
            print(f"[acceptance] {i:,}/{len(todo):,} companies")

    files = sorted(parts.glob("part_*.parquet"))
    if not files:
        raise SystemExit("[acceptance] nothing downloaded")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True).drop_duplicates("accession_number")
    df["acceptance_utc"] = pd.to_datetime(df["acceptance_utc"], utc=True, errors="coerce")
    df = df.dropna()
    df.to_parquet(data / "acceptance.parquet", index=False)
    print(f"[acceptance] wrote {len(df):,} Form 4 acceptance times")


if __name__ == "__main__":
    main()
