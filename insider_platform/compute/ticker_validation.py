from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from insider_platform.config import Config
from insider_platform.eodhd.client import fetch_fundamentals, resolve_symbol
from insider_platform.util.time import utcnow_iso


_LEGAL_WORDS = {
    "A",
    "AN",
    "AND",
    "BIOTECH",
    "BIOTECHNOLOGIES",
    "BIOSCIENCE",
    "BIOSCIENCES",
    "CLASS",
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "GROUP",
    "HLDG",
    "HLDGS",
    "HOLDING",
    "HOLDINGS",
    "INC",
    "INCORPORATED",
    "LTD",
    "PLC",
    "SA",
    "THE",
}


@dataclass(frozen=True)
class TickerValidationResult:
    issuer_cik: str
    ticker: str
    eodhd_symbol: str | None
    status: str
    issuer_name: str | None
    provider_name: str | None
    provider_code: str | None
    provider_exchange: str | None
    match_score: float | None
    reason: str
    checked_at: str


def _debug(msg: str) -> None:
    print(f"[ticker-validation] {msg}")


def _norm_name(value: Any) -> str:
    s = str(value or "").upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    words = [w for w in s.split() if w and w not in _LEGAL_WORDS]
    return " ".join(words)


def _name_score(a: Any, b: Any) -> float:
    na = _norm_name(a)
    nb = _norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.92

    ta = set(na.split())
    tb = set(nb.split())
    token_score = 0.0
    if ta and tb:
        token_score = len(ta & tb) / float(max(1, min(len(ta), len(tb))))
    seq_score = SequenceMatcher(None, na, nb).ratio()
    return max(token_score, seq_score)


def get_cached_validation(conn: Any, issuer_cik: str, ticker: str) -> Optional[TickerValidationResult]:
    row = conn.execute(
        """
        SELECT *
        FROM issuer_ticker_validation
        WHERE issuer_cik=? AND ticker=?
        """,
        (str(issuer_cik).zfill(10), str(ticker or "").strip().upper()),
    ).fetchone()
    if row is None:
        return None
    return _row_to_result(dict(row))


def get_validation_status(conn: Any, issuer_cik: str, ticker: str | None) -> str | None:
    if not ticker:
        return None
    row = conn.execute(
        """
        SELECT status
        FROM issuer_ticker_validation
        WHERE issuer_cik=? AND ticker=?
        """,
        (str(issuer_cik).zfill(10), str(ticker).strip().upper()),
    ).fetchone()
    return str(row["status"]) if row else None


def validate_issuer_ticker(
    conn: Any,
    cfg: Config,
    *,
    issuer_cik: str,
    ticker: str,
    eodhd_symbol: str | None = None,
    max_age_days: int = 14,
) -> TickerValidationResult:
    cik = str(issuer_cik).zfill(10)
    t = str(ticker or "").strip().upper()
    if not t:
        return _upsert_validation(
            conn,
            issuer_cik=cik,
            ticker=t,
            eodhd_symbol=eodhd_symbol,
            status="invalid",
            issuer_name=None,
            provider_name=None,
            provider_code=None,
            provider_exchange=None,
            match_score=None,
            reason="blank_ticker",
        )

    cached = get_cached_validation(conn, cik, t)
    if cached and _is_fresh(cached.checked_at, max_age_days=max_age_days):
        return cached

    issuer = conn.execute(
        "SELECT issuer_name FROM issuer_master WHERE issuer_cik=?",
        (cik,),
    ).fetchone()
    issuer_name = str(issuer["issuer_name"] or "").strip() if issuer else ""

    if not cfg.EODHD_API_KEY:
        return _upsert_validation(
            conn,
            issuer_cik=cik,
            ticker=t,
            eodhd_symbol=eodhd_symbol,
            status="unknown",
            issuer_name=issuer_name or None,
            provider_name=None,
            provider_code=None,
            provider_exchange=None,
            match_score=None,
            reason="missing_eodhd_api_key",
        )

    symbol = (eodhd_symbol or "").strip()
    if not symbol:
        symbol = resolve_symbol(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, t)

    payload = fetch_fundamentals(cfg.EODHD_BASE_URL, cfg.EODHD_API_KEY, symbol)
    general = payload.get("General") if isinstance(payload, dict) else {}
    if not isinstance(general, dict):
        general = {}

    provider_name = str(general.get("Name") or general.get("CompanyName") or "").strip()
    provider_code = str(general.get("Code") or "").strip().upper() or None
    provider_exchange = str(general.get("Exchange") or general.get("ExchangeCode") or "").strip().upper() or None
    score = _name_score(issuer_name, provider_name)

    code_matches = not provider_code or provider_code == t
    if not issuer_name or not provider_name:
        status = "unknown"
        reason = "missing_company_name"
    elif code_matches and score >= 0.48:
        status = "valid"
        reason = "issuer_name_matches_provider"
    elif code_matches and score >= 0.38 and _has_distinctive_token_overlap(issuer_name, provider_name):
        status = "valid"
        reason = "issuer_name_partial_match"
    else:
        status = "invalid"
        reason = "issuer_name_mismatch"

    result = _upsert_validation(
        conn,
        issuer_cik=cik,
        ticker=t,
        eodhd_symbol=symbol,
        status=status,
        issuer_name=issuer_name or None,
        provider_name=provider_name or None,
        provider_code=provider_code,
        provider_exchange=provider_exchange,
        match_score=score,
        reason=reason,
    )

    if result.status == "invalid":
        _record_data_issue(conn, result)
        _debug(
            f"Rejected ticker mapping issuer_cik={cik} ticker={t} symbol={symbol} "
            f"issuer={issuer_name!r} provider={provider_name!r} score={score:.3f}"
        )
    return result


def _has_distinctive_token_overlap(a: Any, b: Any) -> bool:
    ta = {x for x in _norm_name(a).split() if len(x) >= 4}
    tb = {x for x in _norm_name(b).split() if len(x) >= 4}
    return bool(ta & tb)


def _is_fresh(checked_at: str | None, *, max_age_days: int) -> bool:
    if not checked_at:
        return False
    try:
        checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except Exception:
        return False
    return checked >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _upsert_validation(
    conn: Any,
    *,
    issuer_cik: str,
    ticker: str,
    eodhd_symbol: str | None,
    status: str,
    issuer_name: str | None,
    provider_name: str | None,
    provider_code: str | None,
    provider_exchange: str | None,
    match_score: float | None,
    reason: str,
) -> TickerValidationResult:
    checked_at = utcnow_iso()
    conn.execute(
        """
        INSERT INTO issuer_ticker_validation (
            issuer_cik, ticker, eodhd_symbol, status, issuer_name,
            provider_name, provider_code, provider_exchange, match_score, reason, checked_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(issuer_cik, ticker) DO UPDATE SET
            eodhd_symbol=excluded.eodhd_symbol,
            status=excluded.status,
            issuer_name=excluded.issuer_name,
            provider_name=excluded.provider_name,
            provider_code=excluded.provider_code,
            provider_exchange=excluded.provider_exchange,
            match_score=excluded.match_score,
            reason=excluded.reason,
            checked_at=excluded.checked_at
        """,
        (
            issuer_cik,
            ticker,
            eodhd_symbol,
            status,
            issuer_name,
            provider_name,
            provider_code,
            provider_exchange,
            match_score,
            reason,
            checked_at,
        ),
    )
    return TickerValidationResult(
        issuer_cik=issuer_cik,
        ticker=ticker,
        eodhd_symbol=eodhd_symbol,
        status=status,
        issuer_name=issuer_name,
        provider_name=provider_name,
        provider_code=provider_code,
        provider_exchange=provider_exchange,
        match_score=match_score,
        reason=reason,
        checked_at=checked_at,
    )


def _row_to_result(row: Dict[str, Any]) -> TickerValidationResult:
    return TickerValidationResult(
        issuer_cik=str(row.get("issuer_cik") or ""),
        ticker=str(row.get("ticker") or ""),
        eodhd_symbol=row.get("eodhd_symbol"),
        status=str(row.get("status") or "unknown"),
        issuer_name=row.get("issuer_name"),
        provider_name=row.get("provider_name"),
        provider_code=row.get("provider_code"),
        provider_exchange=row.get("provider_exchange"),
        match_score=float(row["match_score"]) if row.get("match_score") is not None else None,
        reason=str(row.get("reason") or ""),
        checked_at=str(row.get("checked_at") or ""),
    )


def _record_data_issue(conn: Any, result: TickerValidationResult) -> None:
    details = {
        "issuer_name": result.issuer_name,
        "provider_name": result.provider_name,
        "provider_code": result.provider_code,
        "provider_exchange": result.provider_exchange,
        "eodhd_symbol": result.eodhd_symbol,
        "match_score": result.match_score,
        "reason": result.reason,
    }
    import json

    conn.execute(
        """
        INSERT INTO data_issues (issue_type, severity, issuer_cik, ticker, accession_number, details_json, created_at)
        VALUES (?, 'high', ?, ?, NULL, ?, ?)
        """,
        (
            "ticker_validation_failed",
            result.issuer_cik,
            result.ticker,
            json.dumps(details, sort_keys=True),
            result.checked_at,
        ),
    )
