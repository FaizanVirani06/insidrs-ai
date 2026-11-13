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
