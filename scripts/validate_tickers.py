import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insider_platform.compute.ticker_validation import validate_issuer_ticker
from insider_platform.config import load_config
from insider_platform.db import connect


def main() -> None:
    p = argparse.ArgumentParser(description="Validate SEC issuer/ticker mappings against EODHD company metadata.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="Validate all issuers with a current ticker")
    g.add_argument("--ticker", type=str, help="Validate one ticker")
    g.add_argument("--issuer-cik", type=str, help="Validate one issuer CIK")
    p.add_argument("--limit", type=int, default=None, help="Optional limit for --all")
    p.add_argument("--max-age-days", type=int, default=0, help="Reuse cached validations newer than this many days")
    args = p.parse_args()

    cfg = load_config()
    with connect(cfg.DB_DSN) as conn:
        params = []
        where = ["current_ticker IS NOT NULL", "BTRIM(current_ticker) <> ''"]
        if args.ticker:
            where.append("UPPER(current_ticker)=?")
            params.append(args.ticker.strip().upper())
        if args.issuer_cik:
            where.append("issuer_cik=?")
            params.append(args.issuer_cik.strip().zfill(10))

        limit_sql = ""
        if args.all and args.limit:
            limit_sql = " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(
            f"""
            SELECT issuer_cik, current_ticker
            FROM issuer_master
            WHERE {" AND ".join(where)}
            ORDER BY last_filing_date DESC NULLS LAST, issuer_cik ASC
            {limit_sql}
            """,
            tuple(params),
        ).fetchall()

        valid = invalid = unknown = errors = 0
        for row in rows:
            issuer_cik = str(row["issuer_cik"]).zfill(10)
            ticker = str(row["current_ticker"]).strip().upper()
            try:
                result = validate_issuer_ticker(
                    conn,
                    cfg,
                    issuer_cik=issuer_cik,
                    ticker=ticker,
                    max_age_days=int(args.max_age_days),
                )
                if result.status == "valid":
                    valid += 1
                elif result.status == "invalid":
                    invalid += 1
                else:
                    unknown += 1
                print(
                    f"{result.status.upper()} {ticker} issuer_cik={issuer_cik} "
                    f"provider={result.provider_name or '-'} score={result.match_score}"
                )
            except Exception as e:
                errors += 1
                print(f"ERROR {ticker} issuer_cik={issuer_cik}: {e}")

        print(f"Checked {len(rows)} issuer/ticker mappings: valid={valid} invalid={invalid} unknown={unknown} errors={errors}")


if __name__ == "__main__":
    main()
