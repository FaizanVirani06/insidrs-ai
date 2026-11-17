"""Download the exact EDGAR acceptance time of every Form 4 for the companies in the study.

    python -m research.fetch_acceptance          # resumable: rerun to continue
    python -m research.fetch_acceptance --refresh

Source: SEC submissions data (data.sec.gov/submissions/CIK##########.json plus
its older pages), which lists every filing about a company, including insiders'
Form 4s, with "acceptanceDateTime" in UTC (checked against filing headers,
which show the same instant in New York time).

Needs SEC_USER_AGENT (the SEC requires automated clients to identify themselves).
Outputs:
    data/acceptance.parquet   accession_number, acceptance_utc            (Form 4 and 4/A)
    data/sec_filings.parquet  issuer_cik, accession_number, form, items, acceptance_utc
                              (Form 4, 8-K with item 2.02 = earnings releases, Schedule 13D/13G)
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


COLS = ["issuer_cik", "accession_number", "form", "items", "acceptance_utc"]
KEEP = {"4", "4/A", "SC 13D", "SC 13D/A", "SCHEDULE 13D", "SCHEDULE 13D/A",
        "SC 13G", "SC 13G/A", "SCHEDULE 13G", "SCHEDULE 13G/A"}


def keep_rows(block: dict, cik: str) -> list[tuple]:
    """Form 4s, Schedule 13D/13G, and 8-Ks that report results of operations (item 2.02)."""
    items = block.get("items") or [""] * len(block.get("form", []))
    out = []
    for a, t, f, it in zip(block.get("accessionNumber", []), block.get("acceptanceDateTime", []),
                           block.get("form", []), items):
        if not t:
            continue
        if f in KEEP or (f == "8-K" and "2.02" in (it or "")):
            out.append((cik, a, f, it or "", t))
    return out


def fetch_company(session: requests.Session, cik: str) -> list[tuple]:
    top = get_json(session, f"{BASE}CIK{cik.zfill(10)}.json")
    if top is None:
        return []
    rows = keep_rows(top.get("filings", {}).get("recent", {}), cik)
    for page in top.get("filings", {}).get("files", []):
        if page.get("filingTo", "9999") < OLDEST_NEEDED:
            continue
        time.sleep(0.12)
        older = get_json(session, BASE + page["name"])
        if older:
            rows += keep_rows(older, cik)
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

    buf: list[tuple] = []
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
                pd.DataFrame(buf, columns=COLS).to_parquet(
                    parts / f"part_{int(time.time() * 1000)}.parquet", index=False)
                buf = []
            state_path.write_text(json.dumps(state))
            print(f"[acceptance] {i:,}/{len(todo):,} companies")

    files = sorted(parts.glob("part_*.parquet"))
    if not files:
        raise SystemExit("[acceptance] nothing downloaded")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    if "form" not in df:
        raise SystemExit("[acceptance] old-format download found; rerun with --refresh")
    df["acceptance_utc"] = pd.to_datetime(df["acceptance_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["acceptance_utc"]).drop_duplicates(["issuer_cik", "accession_number"])
    df.to_parquet(data / "sec_filings.parquet", index=False)
    f4 = df[df["form"].isin(["4", "4/A"])].drop_duplicates("accession_number")
    f4[["accession_number", "acceptance_utc"]].to_parquet(data / "acceptance.parquet", index=False)
    print(f"[acceptance] wrote {len(f4):,} Form 4 acceptance times; "
          f"{(df['form'] == '8-K').sum():,} earnings releases; "
          f"{df['form'].str.contains('13D').sum():,} Schedule 13D and {df['form'].str.contains('13G').sum():,} 13G filings")


if __name__ == "__main__":
    main()
