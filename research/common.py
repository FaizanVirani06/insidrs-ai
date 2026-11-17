"""Shared helpers: config loading and a read-only database connection."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path or os.environ.get("RESEARCH_CONFIG") or ROOT / "research" / "config.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    for key in ("data_dir", "output_dir"):
        p = Path(cfg["paths"][key])
        cfg["paths"][key] = p if p.is_absolute() else ROOT / p
        cfg["paths"][key].mkdir(parents=True, exist_ok=True)
    return cfg


def price_paths(cfg: dict):
    """(prices file, benchmark file) for the configured price source."""
    data = cfg["paths"]["data_dir"]
    if cfg["price_source"] == "yfinance":
        return data / "prices_yf.parquet", data / "benchmark_yf.parquet"
    return data / "prices.parquet", data / "benchmark.parquet"


def load_benchmark(cfg: dict, symbol: str):
    """Return (dates, closes) for one benchmark symbol, or None if it is not in the file.

    Matches "SPY" and "SPY.US" alike (Yahoo and the production table name it differently).
    """
    import pandas as pd

    bench = pd.read_parquet(price_paths(cfg)[1])
    b = bench[bench["symbol"].str.split(".").str[0] == symbol].sort_values("date")
    if b.empty:
        return None
    return b["date"].to_numpy().astype("datetime64[D]"), b["adj_close"].to_numpy(float)


def load_benchmark_open(cfg: dict, symbol: str):
    """(dates, adjusted opens) for one benchmark, or None if opens were not downloaded."""
    import pandas as pd

    bench = pd.read_parquet(price_paths(cfg)[1])
    if "open_adj" not in bench:
        return None
    b = bench[bench["symbol"].str.split(".").str[0] == symbol].sort_values("date")
    if b.empty or b["open_adj"].isna().all():
        return None
    return b["date"].to_numpy().astype("datetime64[D]"), b["open_adj"].to_numpy(float)


def connect_readonly():
    """Open a connection that cannot write, whatever role it logs in as.

    The DSN comes from the environment only (never from a file in git).
    """
    import psycopg2

    dsn = (os.environ.get("RESEARCH_DATABASE_URL") or os.environ.get("INSIDER_DATABASE_URL")
           or os.environ.get("DATABASE_URL"))
    if not dsn:
        raise SystemExit("Set RESEARCH_DATABASE_URL (or INSIDER_DATABASE_URL) to the Postgres DSN.")
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True)
    return conn
