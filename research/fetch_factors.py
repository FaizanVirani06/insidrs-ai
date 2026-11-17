"""Download the Fama-French five factors and momentum (daily) from Ken French's data library.

    python -m research.fetch_factors

Output: data/factors.parquet with columns
    date, mkt_rf, smb, hml, rmw, cma, rf, mom   (decimal daily returns)
The library is updated monthly with a lag of a month or two, so abnormal
returns for the most recent weeks are not available until the next update.
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd
import requests

from research.common import load_config

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FILES = {"ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip", "mom": "F-F_Momentum_Factor_daily_CSV.zip"}


def parse(raw: bytes) -> pd.DataFrame:
    """The CSV has free-text lines before and after the table; keep only rows that start with a date."""
    text = zipfile.ZipFile(io.BytesIO(raw)).read(zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]).decode("latin1")
    lines = text.splitlines()
    header = next(i for i, l in enumerate(lines) if l.startswith(","))
    rows = [l for l in lines[header + 1:] if l[:8].isdigit()]
    df = pd.read_csv(io.StringIO("\n".join([lines[header]] + rows)), skipinitialspace=True)
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    df.columns = ["date"] + [c.strip().lower().replace("-", "_") for c in df.columns[1:]]
    for c in df.columns[1:]:
        df[c] = df[c].astype(float) / 100.0          # file is in percent
    return df


def main() -> None:
    cfg = load_config()
    ff5 = parse(requests.get(BASE + FILES["ff5"], timeout=120).content)
    mom = parse(requests.get(BASE + FILES["mom"], timeout=120).content)
    mom = mom.rename(columns={mom.columns[1]: "mom"})
    df = ff5.merge(mom[["date", "mom"]], on="date", how="inner")
    df = df[df["date"] >= "2008-01-01"]
    expected = ["date", "mkt_rf", "smb", "hml", "rmw", "cma", "rf", "mom"]
    if list(df.columns) != expected:
        raise SystemExit(f"[factors] unexpected columns {list(df.columns)}; the file format may have changed")
    df.to_parquet(cfg["paths"]["data_dir"] / "factors.parquet", index=False)
    print(f"[factors] wrote {len(df):,} days, {df['date'].min().date()} to {df['date'].max().date()}")


if __name__ == "__main__":
    main()
