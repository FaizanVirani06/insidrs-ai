"""Study 3, S10b (amendment 3c): Schedule 13D filings made BY each 10%-holder buyer.

    python -m research.fetch_filer_13d          # resumable

For every insider CIK that appears as a 10% holder on a qualifying buy, download
that CIK's own SEC submissions (the filer side) and keep its Schedule 13D and
13D/A accession numbers. Joining these to the company-side list in
sec_filings.parquet identifies "this buyer filed a 13D on this company".

Needs SEC_USER_AGENT. Output: data/filer_13d.parquet (filer_cik, accession_number, acceptance_utc)
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
from research.fetch_acceptance import BASE, OLDEST_NEEDED, get_json


def rows_13d(block: dict, cik: str) -> list[tuple]:
    return [(cik, a, t) for a, t, f in zip(block.get("accessionNumber", []), block.get("acceptanceDateTime", []),
                                          block.get("form", [])) if t and "13D" in f]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    data = cfg["paths"]["data_dir"]
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not agent:
        raise SystemExit("Set SEC_USER_AGENT (the SEC requires a contact string for automated requests).")
    parts, state_path = data / "filer13d_parts", data / "filer13d_state.json"
    if args.refresh:
        shutil.rmtree(parts, ignore_errors=True)
        state_path.unlink(missing_ok=True)
    parts.mkdir(exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}

    a = pd.read_parquet(data / "analysis.parquet", columns=["side", "qualifies", "is_ten_percent_owner", "owner_cik"])
    ciks = a[(a["side"] == "buy") & a["qualifies"] & (a["is_ten_percent_owner"] == 1)]["owner_cik"].dropna()
    ciks = sorted({str(int(c)) for c in ciks if str(c).strip().isdigit()})
    todo = [c for c in ciks if c not in set(state["done"])]
    print(f"[filer13d] {len(ciks):,} 10%-holder buyers, {len(todo):,} still to download")
    session = requests.Session()
    session.headers.update({"User-Agent": agent, "Accept-Encoding": "gzip, deflate"})
    buf: list[tuple] = []
    for i, cik in enumerate(todo, 1):
        try:
            top = get_json(session, f"{BASE}CIK{cik.zfill(10)}.json")
            if top:
                buf += rows_13d(top.get("filings", {}).get("recent", {}), cik)
                for page in top.get("filings", {}).get("files", []):
                    if page.get("filingTo", "9999") < OLDEST_NEEDED:
                        continue
                    time.sleep(0.12)
                    older = get_json(session, BASE + page["name"])
                    if older:
                        buf += rows_13d(older, cik)
        except requests.RequestException as e:
            print(f"[filer13d] stopped at {cik}: {e}. Rerun to resume.")
            break
        state["done"].append(cik)
        time.sleep(0.12)
        if i % 200 == 0 or i == len(todo):
            if buf:
                pd.DataFrame(buf, columns=["filer_cik", "accession_number", "acceptance_utc"]).to_parquet(
                    parts / f"part_{int(time.time() * 1000)}.parquet", index=False)
                buf = []
            state_path.write_text(json.dumps(state))
            print(f"[filer13d] {i:,}/{len(todo):,}")
    files = sorted(parts.glob("part_*.parquet"))
    df = (pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files
          else pd.DataFrame(columns=["filer_cik", "accession_number", "acceptance_utc"]))
    df["acceptance_utc"] = pd.to_datetime(df["acceptance_utc"], utc=True, errors="coerce")
    df = df.dropna().drop_duplicates(["filer_cik", "accession_number"])
    df.to_parquet(data / "filer_13d.parquet", index=False)
    print(f"[filer13d] wrote {len(df):,} Schedule 13D filings by {df['filer_cik'].nunique():,} buyers")


if __name__ == "__main__":
    main()
