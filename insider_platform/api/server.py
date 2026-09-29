from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Header, Response
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from insider_platform.config import Config, load_config
from insider_platform.db import connect, init_db, get_app_config, upsert_app_config
from insider_platform.util.time import utcnow_iso
from insider_platform.jobs.queue import enqueue_job

from insider_platform.ai.settings import (
    get_ai_classification_settings,
    is_ai_classification_enabled,
    set_ai_classification_enabled,
)
from insider_platform.compute.trade_plan import compute_trade_plan_for_event
from insider_platform.compute.ticker_validation import get_cached_validation, get_validation_status, validate_issuer_ticker

from insider_platform.auth import get_current_user, require_admin, require_admin_viewer, require_subscription
from insider_platform.entitlements import build_entitlements, get_result_limit_for_user, has_full_access
from insider_platform.social.x_client import XSettings, ensure_disclaimer, post_to_x_with_media, upload_media_to_x
from insider_platform.auth.crud import (
    bootstrap_admin_if_needed,
    create_user,
    public_user,
    touch_last_login,
    verify_user_credentials,
)
from insider_platform.auth.security import create_access_token, hash_password, verify_password

from insider_platform.billing.stripe_billing import (
    create_billing_portal_session,
    create_checkout_session,
    process_stripe_webhook,
)


def _debug(msg: str) -> None:
    print(f"[api] {msg}")


app = FastAPI(title="Insider Trading Analysis Platform", version="0.2.0")
cfg: Config = load_config()

# CORS is mainly needed for local development (Vite on :5173 -> API on :8000).
# In production (single origin behind a reverse proxy) CORS is typically unnecessary.
_cors_origins = [o.strip() for o in (cfg.CORS_ALLOW_ORIGINS or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )


@app.on_event("startup")
def _on_startup() -> None:
    # Make config available to auth deps.
    app.state.cfg = cfg

    # Ensure schema exists.
    init_db(cfg.DB_DSN)

    # Bootstrap first admin if needed (only when users table is empty)
    boot = bootstrap_admin_if_needed(cfg)
    if boot:
        _debug(
            f"Bootstrapped initial admin user: username={boot.get('username')} role={boot.get('role')}"
        )


# -----------------------------
# Health
# -----------------------------


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}


# -----------------------------
# Small in-process cache for public, read-heavy endpoints
# -----------------------------

_CACHE_TTL_SECONDS = 600.0
_cache_lock = threading.Lock()
_cache: Dict[Any, tuple[float, Any]] = {}


def _cached(key: Any, loader: Any, *, ttl: float = _CACHE_TTL_SECONDS) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _market_data_as_of(conn: Any) -> str | None:
    """Latest date with stored daily prices (market data is frozen in showcase mode)."""

    def load() -> str | None:
        r = conn.execute("SELECT MAX(date) AS d FROM issuer_prices_daily").fetchone()
        return str(r["d"]) if r and r.get("d") else None

    return _cached("market_data_as_of", load)


def _showcase_stats(conn: Any) -> Dict[str, Any]:
    def load() -> Dict[str, Any]:
        filings = conn.execute(
            "SELECT COUNT(*) AS n, MIN(filing_date) AS first_date, MAX(filing_date) AS last_date FROM filings"
        ).fetchone()
        events = conn.execute("SELECT COUNT(*) AS n FROM insider_events").fetchone()
        issuers = conn.execute("SELECT COUNT(*) AS n FROM issuer_master").fetchone()
        ai = conn.execute("SELECT COUNT(*) AS n FROM ai_outputs").fetchone()
        return {
            "filings": int((filings or {}).get("n") or 0),
            "first_filing_date": (filings or {}).get("first_date"),
            "last_filing_date": (filings or {}).get("last_date"),
            "insider_events": int((events or {}).get("n") or 0),
            "issuers": int((issuers or {}).get("n") or 0),
            "ai_ratings": int((ai or {}).get("n") or 0),
        }

    return _cached("showcase_stats", load)


@app.get("/public/site-status")
def public_site_status() -> Dict[str, Any]:
    """What the SPA needs to render showcase framing (banner, data freshness, demo button)."""
    as_of: str | None = None
    stats: Dict[str, Any] | None = None
    ai_enabled = False
    try:
        with connect(cfg.DB_DSN) as conn:
            as_of = _market_data_as_of(conn)
            stats = _showcase_stats(conn) if cfg.SHOWCASE_MODE else None
            ai_enabled = is_ai_classification_enabled(conn)
    except Exception as e:
        _debug(f"site-status lookup failed: {e}")
    return {
        "showcase_mode": bool(cfg.SHOWCASE_MODE),
        "demo_login_available": bool(cfg.SHOWCASE_MODE),
        "market_data_as_of": as_of,
        "ai_classification_enabled": ai_enabled,
        "stats": stats,
    }


# -----------------------------
# Auth
# -----------------------------

def _cookie_secure(cfg: Config) -> bool:
    """Return whether auth cookies should be marked Secure."""
    samesite = str(getattr(cfg, "AUTH_COOKIE_SAMESITE", "lax") or "lax").lower()
    secure = bool(getattr(cfg, "AUTH_COOKIE_SECURE", False))
    # Browsers require Secure when SameSite=None
    if samesite == "none":
        return True
    return secure

def _set_auth_cookies(response: Response, *, token: str, user: Dict[str, Any], cfg: Config) -> None:
    """Set session cookies for browser-based auth."""
    max_age = int(getattr(cfg, "AUTH_TOKEN_EXPIRE_MINUTES", 10080)) * 60
    cookie_name = str(getattr(cfg, "AUTH_COOKIE_NAME", "ip_token") or "ip_token")
    samesite = str(getattr(cfg, "AUTH_COOKIE_SAMESITE", "lax") or "lax").lower()
    domain = getattr(cfg, "AUTH_COOKIE_DOMAIN", None)
    path = str(getattr(cfg, "AUTH_COOKIE_PATH", "/") or "/")
    secure = _cookie_secure(cfg)

    # Auth token cookie (httpOnly)
    response.set_cookie(
        key=cookie_name,
        value=str(token),
        httponly=True,
        samesite=samesite,
        secure=secure,
        max_age=max_age,
        path=path,
        domain=domain,
    )

    # Convenience cookies (not security-critical)
    role = user.get("role") or ("admin" if user.get("is_admin") else "")
    if role:
        response.set_cookie(
            key="ip_role",
            value=str(role),
            httponly=False,
            samesite=samesite,
            secure=secure,
            max_age=max_age,
            path=path,
            domain=domain,
        )

    sub = user.get("subscription_status") or ""
    response.set_cookie(
        key="ip_sub",
        value=str(sub),
        httponly=False,
        samesite=samesite,
        secure=secure,
        max_age=max_age,
        path=path,
        domain=domain,
    )

def _clear_auth_cookies(response: Response, cfg: Config) -> None:
    cookie_name = str(getattr(cfg, "AUTH_COOKIE_NAME", "ip_token") or "ip_token")
    domain = getattr(cfg, "AUTH_COOKIE_DOMAIN", None)
    path = str(getattr(cfg, "AUTH_COOKIE_PATH", "/") or "/")
    response.delete_cookie(key=cookie_name, path=path, domain=domain)
    response.delete_cookie(key="ip_role", path=path, domain=domain)
    response.delete_cookie(key="ip_sub", path=path, domain=domain)



class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    """Public self-serve registration.

    NOTE: We keep the project model as a simple username/password system.
    In production, "username" should be treated as the customer's email.
    """

    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"  # admin|showcase|user


class ProfileUpsertRequest(BaseModel):
    full_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    trade_side: str = "buy"  # buy|sell|both
    min_ai_rating: float = 7.0
    max_beta: float | None = None
    preferred_sectors: list[str] = []
    email_alerts_enabled: bool = False
    daily_digest_enabled: bool = False


class UpdateCredentialsRequest(BaseModel):
    current_password: str
    new_username: str | None = None
    new_password: str | None = None


class SiteBrandingUpdateRequest(BaseModel):
    logo_mode: str | None = None
    logo_text: str | None = None
    logo_image_src: str | None = None
    favicon_image_src: str | None = None


class ShowcaseCredentialsUpdateRequest(BaseModel):
    username: str
    password: str | None = None


DEFAULT_PROFILE_PREFERENCES: Dict[str, Any] = {
    "trade_side": "buy",
    "min_ai_rating": 7.0,
    "max_beta": None,
    "preferred_sectors": [],
    "email_alerts_enabled": False,
    "daily_digest_enabled": False,
}


def _unique_nonempty_strs(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return out
    for v in values:
        s = str(v or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _clean_profile_text(value: Any) -> str | None:
    s = str(value or "").strip()
    return s or None


def _reject_showcase_mutation(user: Dict[str, Any]) -> None:
    if str(user.get("role") or "").strip().lower() == "showcase":
        raise HTTPException(status_code=403, detail="showcase_read_only")


# -----------------------------
# Showcase viewer privacy
# -----------------------------
# The showcase account is reachable by anyone via /auth/demo-login, so admin
# pages it can read must never expose real customers' contact details or any
# credentials that ended up in job error strings.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")
_SECRET_PARAM_RE = re.compile(r"(?i)\b(api_token|api_key|apikey|key|token|secret|password)=([^&\s'\"]+)")


def _is_showcase_viewer(user: Dict[str, Any]) -> bool:
    return str(user.get("role") or "").strip().lower() == "showcase"


def _mask_identity(value: Any) -> str | None:
    """Mask a username / email so it stays recognizable as data, not as a person."""
    s = str(value or "").strip()
    if not s:
        return None
    if "@" in s:
        local, _, domain = s.partition("@")
        domain_name, _, tld = domain.rpartition(".")
        masked_domain = f"{(domain_name or domain)[:1]}•••" + (f".{tld}" if domain_name else "")
        return f"{local[:1]}•••@{masked_domain}"
    return f"{s[:1]}•••"


def _mask_full_name(value: Any) -> str | None:
    parts = [p for p in str(value or "").split() if p]
    if not parts:
        return None
    return " ".join(f"{p[0].upper()}." for p in parts[:3])


def _scrub_free_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    out = _EMAIL_RE.sub("[email hidden]", value)
    out = _PHONE_RE.sub("[phone hidden]", out)
    return out


def _scrub_secrets(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=[redacted]", value)


def _normalize_profile_preferences(raw: Any) -> Dict[str, Any]:
    prefs = dict(DEFAULT_PROFILE_PREFERENCES)

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = None

    if not isinstance(parsed, dict):
        return prefs

    side = str(parsed.get("trade_side") or prefs["trade_side"]).strip().lower()
    if side in ("buy", "sell", "both"):
        prefs["trade_side"] = side

    try:
        min_ai = float(parsed.get("min_ai_rating"))
        if min_ai < 0:
            min_ai = 0.0
        if min_ai > 10:
            min_ai = 10.0
        prefs["min_ai_rating"] = float(min_ai)
    except Exception:
        pass

    max_beta = parsed.get("max_beta")
    try:
        if max_beta is not None:
            beta = float(max_beta)
            if beta >= 0:
                prefs["max_beta"] = beta
    except Exception:
        prefs["max_beta"] = None

    prefs["preferred_sectors"] = _unique_nonempty_strs(parsed.get("preferred_sectors"))
    prefs["email_alerts_enabled"] = bool(parsed.get("email_alerts_enabled"))
    prefs["daily_digest_enabled"] = bool(parsed.get("daily_digest_enabled"))
    return prefs


def _profile_from_rows(user_row: Dict[str, Any], profile_row: Dict[str, Any] | None) -> Dict[str, Any]:
    if profile_row is None:
        username = str(user_row.get("username") or "").strip()
        default_contact_email = username if "@" in username else None
        return {
            "user_id": int(user_row["user_id"]),
            "full_name": None,
            "contact_email": default_contact_email,
            "contact_phone": None,
            "preferences": dict(DEFAULT_PROFILE_PREFERENCES),
            "created_at": user_row.get("created_at"),
            "updated_at": user_row.get("updated_at"),
        }

    return {
        "user_id": int(user_row["user_id"]),
        "full_name": profile_row.get("full_name"),
        "contact_email": profile_row.get("contact_email"),
        "contact_phone": profile_row.get("contact_phone"),
        "preferences": _normalize_profile_preferences(profile_row.get("preferences_json")),
        "created_at": profile_row.get("created_at") or user_row.get("created_at"),
        "updated_at": profile_row.get("updated_at") or user_row.get("updated_at"),
    }


def _get_profile_row(conn: Any, user_id: int) -> Dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def _get_current_profile(conn: Any, user_id: int) -> Dict[str, Any]:
    user_row = conn.execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()
    if user_row is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return _profile_from_rows(dict(user_row), _get_profile_row(conn, user_id))


def _upsert_profile(conn: Any, user_id: int, payload: ProfileUpsertRequest) -> Dict[str, Any]:
    side = str(payload.trade_side or "buy").strip().lower()
    if side not in ("buy", "sell", "both"):
        raise HTTPException(status_code=400, detail="invalid_trade_side")

    try:
        min_ai = float(payload.min_ai_rating)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_min_ai_rating")
    if min_ai < 0 or min_ai > 10:
        raise HTTPException(status_code=400, detail="invalid_min_ai_rating")

    max_beta = payload.max_beta
    if max_beta is not None:
        try:
            max_beta = float(max_beta)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_max_beta")
        if max_beta < 0:
            raise HTTPException(status_code=400, detail="invalid_max_beta")

    prefs = {
        "trade_side": side,
        "min_ai_rating": float(min_ai),
        "max_beta": max_beta,
        "preferred_sectors": _unique_nonempty_strs(payload.preferred_sectors),
        "email_alerts_enabled": bool(payload.email_alerts_enabled),
        "daily_digest_enabled": bool(payload.daily_digest_enabled),
    }

    now = utcnow_iso()
    conn.execute(
        """
        INSERT INTO user_profiles (
            user_id,
            full_name,
            contact_email,
            contact_phone,
            preferences_json,
            created_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (user_id) DO UPDATE SET
            full_name=excluded.full_name,
            contact_email=excluded.contact_email,
            contact_phone=excluded.contact_phone,
            preferences_json=excluded.preferences_json,
            updated_at=excluded.updated_at
        """,
        (
            int(user_id),
            _clean_profile_text(payload.full_name),
            _clean_profile_text(payload.contact_email),
            _clean_profile_text(payload.contact_phone),
            json.dumps(prefs, sort_keys=True),
            now,
            now,
        ),
    )
    return _get_current_profile(conn, user_id)


DEFAULT_SITE_BRANDING: Dict[str, Any] = {
    "logo_mode": "text",
    "logo_text": "InsidrsAI",
    "logo_image_src": None,
    "favicon_image_src": None,
}


def _validate_brand_image_src(value: Any, *, error_prefix: str) -> str | None:
    image_src = str(value or "").strip() or None
    if image_src is None:
        return None
    if not (
        image_src.startswith("data:image/")
        or image_src.startswith("https://")
        or image_src.startswith("http://")
        or image_src.startswith("/")
    ):
        raise HTTPException(status_code=400, detail=f"invalid_{error_prefix}_image_src")
    if len(image_src) > 500000:
        raise HTTPException(status_code=400, detail=f"{error_prefix}_image_too_large")
    return image_src


def _get_site_branding(conn: Any) -> Dict[str, Any]:
    logo_mode = str(get_app_config(conn, "site_logo_mode") or DEFAULT_SITE_BRANDING["logo_mode"]).strip().lower()
    logo_text = str(get_app_config(conn, "site_logo_text") or DEFAULT_SITE_BRANDING["logo_text"]).strip() or str(
        DEFAULT_SITE_BRANDING["logo_text"]
    )
    logo_image_src = str(get_app_config(conn, "site_logo_image_src") or "").strip() or None
    favicon_image_src = str(get_app_config(conn, "site_favicon_image_src") or "").strip() or None

    if logo_mode not in ("text", "image"):
        logo_mode = "text"
    if logo_mode == "image" and not logo_image_src:
        logo_mode = "text"

    return {
        "logo_mode": logo_mode,
        "logo_text": logo_text,
        "logo_image_src": logo_image_src,
        "favicon_image_src": favicon_image_src,
    }


def _upsert_site_branding(conn: Any, payload: SiteBrandingUpdateRequest) -> Dict[str, Any]:
    logo_mode = str(payload.logo_mode or DEFAULT_SITE_BRANDING["logo_mode"]).strip().lower()
    if logo_mode not in ("text", "image"):
        raise HTTPException(status_code=400, detail="invalid_logo_mode")

    logo_text = str(payload.logo_text or DEFAULT_SITE_BRANDING["logo_text"]).strip() or str(DEFAULT_SITE_BRANDING["logo_text"])
    if len(logo_text) > 80:
        raise HTTPException(status_code=400, detail="logo_text_too_long")

    logo_image_src = _validate_brand_image_src(payload.logo_image_src, error_prefix="logo")
    favicon_image_src = _validate_brand_image_src(payload.favicon_image_src, error_prefix="favicon")

    upsert_app_config(conn, "site_logo_mode", logo_mode)
    upsert_app_config(conn, "site_logo_text", logo_text)
    upsert_app_config(conn, "site_logo_image_src", logo_image_src or "")
    upsert_app_config(conn, "site_favicon_image_src", favicon_image_src or "")
    return _get_site_branding(conn)


def _get_showcase_user_row(conn: Any) -> Dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM users WHERE role='showcase' ORDER BY user_id ASC LIMIT 1"
    ).fetchone()
    return dict(row) if row is not None else None


def _get_showcase_user(conn: Any) -> Dict[str, Any] | None:
    row = _get_showcase_user_row(conn)
    return public_user(row) if row is not None else None


def _upsert_showcase_user(conn: Any, payload: ShowcaseCredentialsUpdateRequest) -> Dict[str, Any]:
    username = str(payload.username or "").strip().lower()
    password = payload.password or None

    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username_too_short")
    if password is not None and password != "" and len(password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")

    rows = conn.execute(
        "SELECT * FROM users WHERE role='showcase' ORDER BY user_id ASC"
    ).fetchall()
    primary = dict(rows[0]) if rows else None
    extras = [dict(r) for r in rows[1:]]
    now = utcnow_iso()

    if primary is None:
        if not password:
            raise HTTPException(status_code=400, detail="password_required")
        user = create_user(conn, username=username, password=password, role="showcase")
        return user

    existing = conn.execute(
        "SELECT user_id FROM users WHERE username=? AND user_id<>?",
        (username, int(primary["user_id"])),
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="username_exists")

    fields: list[tuple[str, Any]] = []
    if username != str(primary.get("username") or ""):
        fields.append(("username", username))
    if password:
        fields.append(("password_hash", hash_password(password)))
    if int(primary.get("is_active") or 0) != 1:
        fields.append(("is_active", 1))

    if fields:
        fields.append(("updated_at", now))
        sets = ", ".join([f"{key}=?" for key, _ in fields])
        values = [value for _, value in fields] + [int(primary["user_id"])]
        conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", values)

    for extra in extras:
        conn.execute(
            "UPDATE users SET is_active=0, updated_at=? WHERE user_id=?",
            (now, int(extra["user_id"])),
        )

    refreshed = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (int(primary["user_id"]),),
    ).fetchone()
    if refreshed is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return public_user(refreshed)


def _sanitize_event_row_for_viewer(event: Dict[str, Any], *, is_admin: bool) -> Dict[str, Any]:
    if is_admin:
        return event

    clean = dict(event)
    for key in ("ai_model_id", "ai_prompt_version"):
        clean.pop(key, None)
    return clean


def _sanitize_ai_latest_for_viewer(ai_latest: Dict[str, Any] | None, *, is_admin: bool) -> Dict[str, Any] | None:
    if ai_latest is None:
        return None
    if is_admin:
        return ai_latest

    clean = dict(ai_latest)
    for key in (
        "ai_output_id",
        "model_id",
        "prompt_version",
        "input_schema_version",
        "output_schema_version",
        "inputs_hash",
        "input",
    ):
        clean.pop(key, None)

    output = clean.get("output")
    if isinstance(output, dict):
        output_clean = dict(output)
        for key in ("schema_version", "model_id", "prompt_version"):
            output_clean.pop(key, None)
        clean["output"] = output_clean

    return clean


@app.post("/auth/login")
def auth_login(payload: LoginRequest, response: Response) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        user_row = verify_user_credentials(conn, payload.username, payload.password)
        if user_row is None:
            raise HTTPException(status_code=401, detail="invalid_credentials")

        touch_last_login(conn, int(user_row["user_id"]))

        token = create_access_token(
            secret=cfg.AUTH_JWT_SECRET,
            user_id=int(user_row["user_id"]),
            username=str(user_row["username"]),
            role=str(user_row["role"]),
            expires_minutes=int(cfg.AUTH_TOKEN_EXPIRE_MINUTES),
        )

        u = public_user(user_row)
        u["is_admin"] = (u.get("role") == "admin")

        # Set browser session cookies (httpOnly JWT + convenience metadata cookies).
        _set_auth_cookies(response, token=token, user=u, cfg=cfg)

        return {"access_token": token, "token_type": "bearer", "user": u}


@app.post("/auth/register")
def auth_register(payload: RegisterRequest, response: Response) -> Dict[str, Any]:
    """Create a new user account.

    This endpoint is intentionally simple to unblock productization.
    Consider adding email verification + rate limiting before public launch.
    """

    username = (payload.username or "").strip().lower()
    password = payload.password or ""
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username_too_short")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")

    with connect(cfg.DB_DSN) as conn:
        try:
            u = create_user(conn, username=username, password=password, role="user")
        except ValueError as e:
            detail = str(e)
            if detail == "username_exists":
                raise HTTPException(status_code=409, detail=detail)
            raise HTTPException(status_code=400, detail=detail)

        token = create_access_token(
            secret=cfg.AUTH_JWT_SECRET,
            user_id=int(u["user_id"]),
            username=str(u["username"]),
            role=str(u["role"]),
            expires_minutes=int(cfg.AUTH_TOKEN_EXPIRE_MINUTES),
        )
        u["is_admin"] = (u.get("role") == "admin")

        _set_auth_cookies(response, token=token, user=u, cfg=cfg)

        return {"access_token": token, "token_type": "bearer", "user": u}




@app.post("/auth/logout")
def auth_logout(response: Response) -> Dict[str, Any]:
    """Clear browser session cookies."""
    _clear_auth_cookies(response, cfg)
    return {"ok": True}

@app.get("/auth/me")
def auth_me(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return {"user": user}


DEMO_SHOWCASE_USERNAME = "recruiter-demo"


@app.post("/auth/demo-login")
def auth_demo_login(response: Response) -> Dict[str, Any]:
    """One-click sign-in as the read-only showcase account (showcase mode only).

    If no showcase account exists yet, one is created with a random password
    (admins can set real credentials later from Site settings).
    """
    if not cfg.SHOWCASE_MODE:
        raise HTTPException(status_code=404, detail="demo_login_disabled")

    with connect(cfg.DB_DSN) as conn:
        row = _get_showcase_user_row(conn)
        if row is None:
            create_user(
                conn,
                username=DEMO_SHOWCASE_USERNAME,
                password=secrets.token_urlsafe(32),
                role="showcase",
            )
            row = _get_showcase_user_row(conn)
        if row is None or int(row.get("is_active") or 0) != 1:
            raise HTTPException(status_code=503, detail="demo_account_unavailable")

        touch_last_login(conn, int(row["user_id"]))
        token = create_access_token(
            secret=cfg.AUTH_JWT_SECRET,
            user_id=int(row["user_id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            expires_minutes=int(cfg.AUTH_TOKEN_EXPIRE_MINUTES),
        )
        u = public_user(row)
        _set_auth_cookies(response, token=token, user=u, cfg=cfg)
        return {"user": u}


@app.put("/auth/credentials")
def auth_update_credentials(
    payload: UpdateCredentialsRequest,
    response: Response,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _reject_showcase_mutation(user)
    current_password = payload.current_password or ""
    if not current_password:
        raise HTTPException(status_code=400, detail="current_password_required")

    raw_username = (payload.new_username or "").strip()
    new_username = raw_username.lower() if raw_username else None
    new_password = payload.new_password or None

    if not new_username and not new_password:
        raise HTTPException(status_code=400, detail="no_credential_changes_requested")

    if new_username is not None and len(new_username) < 3:
        raise HTTPException(status_code=400, detail="username_too_short")

    if new_password is not None and len(new_password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")

    user_id = int(user["user_id"])

    with connect(cfg.DB_DSN) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="user_not_found")

        if not verify_password(current_password, str(row["password_hash"])):
            raise HTTPException(status_code=401, detail="invalid_current_password")

        now = utcnow_iso()

        if new_username is not None and new_username != str(row["username"]):
            existing = conn.execute(
                "SELECT user_id FROM users WHERE username=? AND user_id<>?",
                (new_username, user_id),
            ).fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail="username_exists")
            conn.execute(
                "UPDATE users SET username=?, updated_at=? WHERE user_id=?",
                (new_username, now, user_id),
            )

        if new_password is not None:
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?",
                (hash_password(new_password), now, user_id),
            )

        updated = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if updated is None:
            raise HTTPException(status_code=404, detail="user_not_found")

        public = public_user(updated)
        public["is_admin"] = (public.get("role") == "admin")

        token = create_access_token(
            secret=cfg.AUTH_JWT_SECRET,
            user_id=int(updated["user_id"]),
            username=str(updated["username"]),
            role=str(updated["role"]),
            expires_minutes=int(cfg.AUTH_TOKEN_EXPIRE_MINUTES),
        )
        _set_auth_cookies(response, token=token, user=public, cfg=cfg)
        return {"user": public}


@app.get("/profile")
def get_profile(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        profile = _get_current_profile(conn, int(user["user_id"]))
    return {"profile": profile}


@app.put("/profile")
def put_profile(
    payload: ProfileUpsertRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _reject_showcase_mutation(user)
    with connect(cfg.DB_DSN) as conn:
        profile = _upsert_profile(conn, int(user["user_id"]), payload)
    return {"profile": profile}


@app.get("/public/sectors")
def public_sectors() -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT sector
            FROM issuer_fundamentals_cache
            WHERE sector IS NOT NULL AND BTRIM(sector) <> ''
            ORDER BY sector ASC
            """
        ).fetchall()
    return {"sectors": [str(r["sector"]).strip() for r in rows if str(r.get("sector") or "").strip()]}


@app.get("/recommendations")
def recommendations(
    days: int = Query(30, ge=1, le=3650),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0, le=50000),
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    user_id = int(user["user_id"])
    start_date = (date.today() - timedelta(days=int(days))).isoformat()
    page_limit = int(limit) + 1

    best_ai_expr = (
        "CASE WHEN e.ai_buy_rating IS NULL AND e.ai_sell_rating IS NULL "
        "THEN NULL "
        "ELSE GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) END"
    )

    with connect(cfg.DB_DSN) as conn:
        profile = _get_current_profile(conn, user_id)
        prefs = _normalize_profile_preferences(profile.get("preferences"))

        where = [
            "e.filing_date >= ?",
            "(e.has_buy=1 OR e.has_sell=1)",
            "(e.ai_buy_rating IS NOT NULL OR e.ai_sell_rating IS NOT NULL OR e.ai_confidence IS NOT NULL)",
        ]
        params: list[Any] = [start_date]

        side = str(prefs.get("trade_side") or "buy").strip().lower()
        if side == "buy":
            where.append("e.has_buy=1")
            where.append("COALESCE(e.ai_buy_rating, -1) >= ?")
            params.append(float(prefs.get("min_ai_rating") or 0.0))
        elif side == "sell":
            where.append("e.has_sell=1")
            where.append("COALESCE(e.ai_sell_rating, -1) >= ?")
            params.append(float(prefs.get("min_ai_rating") or 0.0))
        else:
            where.append(f"COALESCE(({best_ai_expr}), -1) >= ?")
            params.append(float(prefs.get("min_ai_rating") or 0.0))

        max_beta = prefs.get("max_beta")
        if max_beta is not None:
            where.append("f.beta IS NOT NULL AND f.beta <= ?")
            params.append(float(max_beta))

        preferred_sectors = _unique_nonempty_strs(prefs.get("preferred_sectors"))
        if preferred_sectors:
            placeholders = ", ".join(["?" for _ in preferred_sectors])
            where.append(f"f.sector IN ({placeholders})")
            params.extend(preferred_sectors)

        where_sql = " AND ".join(where)

        rows = conn.execute(
            f"""
            SELECT
                e.*,
                {best_ai_expr} AS best_ai_rating,
                im.issuer_name AS issuer_name,
                f.sector AS sector,
                f.beta AS beta
            FROM insider_events e
            LEFT JOIN issuer_master im ON im.issuer_cik = e.issuer_cik
            LEFT JOIN issuer_fundamentals_cache f ON f.ticker = e.ticker
            WHERE {where_sql}
            ORDER BY
                COALESCE(({best_ai_expr}), -1) DESC,
                COALESCE(e.ai_confidence, -1) DESC,
                e.filing_date DESC,
                e.event_trade_date DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_limit, offset),
        ).fetchall()

    events = [_sanitize_event_row_for_viewer(dict(r), is_admin=bool(user.get("is_admin"))) for r in rows]
    has_next = len(events) > limit
    if has_next:
        events = events[:limit]

    return {
        "days": days,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if has_next else None,
        "applied": prefs,
        "profile": profile,
        "events": events,
    }


# Admin: create users
@app.post("/admin/users")
def admin_create_user(
    payload: CreateUserRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        try:
            u = create_user(conn, username=payload.username, password=payload.password, role=payload.role)
        except ValueError as e:
            detail = str(e)
            if detail == "username_exists":
                raise HTTPException(status_code=409, detail=detail)
            raise HTTPException(status_code=400, detail=detail)
    return {"user": u}


@app.get("/admin/users")
def admin_list_users(
    q: str | None = None,
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=50000),
    viewer: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    showcase = _is_showcase_viewer(viewer)
    # Search would let a public demo viewer probe whether an email has an account.
    qn = "" if showcase else (q or "").strip()
    like = f"%{qn}%" if qn else None
    page_limit = int(limit) + 1

    where = ["1=1"]
    params: list[Any] = []

    if not include_inactive:
        where.append("u.is_active=1")

    if like is not None:
        where.append(
            "(u.username ILIKE ? OR COALESCE(p.full_name,'') ILIKE ? OR COALESCE(p.contact_email,'') ILIKE ? OR COALESCE(p.contact_phone,'') ILIKE ?)"
        )
        params.extend([like, like, like, like])

    where_sql = " AND ".join(where)

    with connect(cfg.DB_DSN) as conn:
        total_row = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM users u
            LEFT JOIN user_profiles p ON p.user_id = u.user_id
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchone()
        total = int((total_row or {}).get("n") or 0)

        rows = conn.execute(
            f"""
            SELECT
                u.user_id,
                u.username,
                u.role,
                u.is_active,
                u.created_at,
                u.updated_at,
                u.last_login_at,
                u.subscription_status,
                u.current_period_end,
                u.cancel_at_period_end,
                u.stripe_customer_id,
                u.stripe_subscription_id,
                u.stripe_price_id,
                p.full_name,
                p.contact_email,
                p.contact_phone
            FROM users u
            LEFT JOIN user_profiles p ON p.user_id = u.user_id
            WHERE {where_sql}
            ORDER BY u.created_at DESC, u.user_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_limit, offset),
        ).fetchall()

    users = [dict(r) for r in rows]
    has_next = len(users) > limit
    if has_next:
        users = users[:limit]

    if showcase:
        for u in users:
            u["username"] = _mask_identity(u.get("username"))
            u["full_name"] = _mask_full_name(u.get("full_name"))
            u["contact_email"] = _mask_identity(u.get("contact_email"))
            u["contact_phone"] = "•••" if u.get("contact_phone") else None
            for key in ("stripe_customer_id", "stripe_subscription_id", "stripe_price_id"):
                if u.get(key):
                    u[key] = str(u[key]).split("_", 1)[0] + "_•••"

    return {
        "users": users,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if has_next else None,
        "query": qn,
        "include_inactive": include_inactive,
    }


@app.delete("/admin/users/{user_id}")
def admin_remove_user(
    user_id: int,
    admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    target_id = int(user_id)
    admin_id = int(admin["user_id"])

    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="cannot_remove_current_user")

    with connect(cfg.DB_DSN) as conn:
        target = conn.execute("SELECT * FROM users WHERE user_id=?", (target_id,)).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="user_not_found")

        if str(target.get("role") or "") == "admin" and int(target.get("is_active") or 0) == 1:
            active_admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1"
            ).fetchone()
            if int((active_admins or {}).get("n") or 0) <= 1:
                raise HTTPException(status_code=400, detail="cannot_remove_last_admin")

        now = utcnow_iso()
        conn.execute(
            """
            UPDATE users
            SET
                is_active=0,
                stripe_subscription_id=NULL,
                stripe_price_id=NULL,
                subscription_status=NULL,
                current_period_end=NULL,
                cancel_at_period_end=0,
                subscription_updated_at=?,
                updated_at=?
            WHERE user_id=?
            """,
            (now, now, target_id),
        )

    return {"ok": True, "user_id": target_id, "removed_at": now}


@app.get("/public/site-branding")
def public_site_branding() -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        branding = _get_site_branding(conn)
    return {"branding": branding}


@app.post("/admin/site/branding")
def admin_update_site_branding(
    payload: SiteBrandingUpdateRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        branding = _upsert_site_branding(conn, payload)
    return {"ok": True, "branding": branding}


@app.get("/admin/site/showcase-user")
def admin_get_showcase_user(
    _viewer: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        showcase_user = _get_showcase_user(conn)
    return {"showcase_user": showcase_user}


@app.post("/admin/site/showcase-user")
def admin_upsert_showcase_user(
    payload: ShowcaseCredentialsUpdateRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        showcase_user = _upsert_showcase_user(conn, payload)
    return {"ok": True, "showcase_user": showcase_user}


class AiSettingsUpdateRequest(BaseModel):
    enabled: bool


@app.get("/admin/site/ai-settings")
def admin_get_ai_settings(_viewer: Dict[str, Any] = Depends(require_admin_viewer)) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        return {"ai_settings": get_ai_classification_settings(conn)}


@app.post("/admin/site/ai-settings")
def admin_update_ai_settings(
    payload: AiSettingsUpdateRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        settings = set_ai_classification_enabled(conn, bool(payload.enabled))
    return {"ok": True, "ai_settings": settings}


# -----------------------------
# Billing (Stripe)
# -----------------------------


class CheckoutSessionRequest(BaseModel):
    plan: str = "monthly"  # monthly|yearly|trial


class PricingDisplayUpdateRequest(BaseModel):
    """Admin-controlled display prices shown on the marketing pricing page.

    NOTE: This does *not* change Stripe pricing. It's purely a website display setting
    so pricing copy can be updated without a deploy.
    """

    monthly_usd: float | None = None
    yearly_usd: float | None = None
    currency: str | None = None  # default: USD


def _parse_display_price(raw: str | None, default: float) -> float:
    if raw is None:
        return float(default)
    try:
        v = float(str(raw).strip())
        if not (v > 0):
            return float(default)
        # Keep it sane
        if v > 100000:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


@app.get("/public/pricing-display")
def public_pricing_display() -> Dict[str, Any]:
    """Public endpoint for marketing UI.

    Returns the admin-configured *display* prices.
    """

    DEFAULT_MONTHLY = 25.0
    DEFAULT_YEARLY = 200.0

    with connect(cfg.DB_DSN) as conn:
        monthly_raw = get_app_config(conn, "pricing_display_monthly_usd")
        yearly_raw = get_app_config(conn, "pricing_display_yearly_usd")
        currency = (get_app_config(conn, "pricing_display_currency") or "USD").strip().upper()

    if not currency:
        currency = "USD"

    return {
        "currency": currency,
        "monthly_usd": _parse_display_price(monthly_raw, DEFAULT_MONTHLY),
        "yearly_usd": _parse_display_price(yearly_raw, DEFAULT_YEARLY),
    }


@app.post("/admin/site/pricing-display")
def admin_update_pricing_display(
    payload: PricingDisplayUpdateRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Admin endpoint to update marketing display prices."""

    def _validate_price(v: float | None) -> float | None:
        if v is None:
            return None
        try:
            x = float(v)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_price")
        if not (x > 0):
            raise HTTPException(status_code=400, detail="price_must_be_positive")
        if x > 100000:
            raise HTTPException(status_code=400, detail="price_too_large")
        return float(x)

    monthly = _validate_price(payload.monthly_usd)
    yearly = _validate_price(payload.yearly_usd)
    currency = (payload.currency or "").strip().upper() if payload.currency is not None else None
    if currency is not None and (len(currency) < 3 or len(currency) > 6):
        raise HTTPException(status_code=400, detail="invalid_currency")

    with connect(cfg.DB_DSN) as conn:
        if monthly is not None:
            upsert_app_config(conn, "pricing_display_monthly_usd", str(monthly))
        if yearly is not None:
            upsert_app_config(conn, "pricing_display_yearly_usd", str(yearly))
        if currency is not None:
            upsert_app_config(conn, "pricing_display_currency", currency)

        # Return the updated values
        monthly_raw = get_app_config(conn, "pricing_display_monthly_usd")
        yearly_raw = get_app_config(conn, "pricing_display_yearly_usd")
        cur = (get_app_config(conn, "pricing_display_currency") or "USD").strip().upper()

    return {
        "ok": True,
        "pricing": {
            "currency": cur,
            "monthly_usd": _parse_display_price(monthly_raw, 25.0),
            "yearly_usd": _parse_display_price(yearly_raw, 200.0),
        },
    }


@app.get("/billing/plans")
def billing_plans() -> Dict[str, Any]:
    """Expose configured plan price IDs so the frontend can render pricing."""
    billing_enabled = bool(
        not cfg.SHOWCASE_MODE and cfg.STRIPE_SECRET_KEY and (cfg.STRIPE_PRICE_ID_MONTHLY or cfg.STRIPE_PRICE_ID_YEARLY)
    )
    monthly_trial_days = max(int(cfg.STRIPE_MONTHLY_TRIAL_DAYS or 0), 0)
    return {
        "monthly": cfg.STRIPE_PRICE_ID_MONTHLY,
        "yearly": cfg.STRIPE_PRICE_ID_YEARLY,
        "enabled": billing_enabled,
        "monthly_trial_days": monthly_trial_days,
        "monthly_trial_available": bool(billing_enabled and cfg.STRIPE_PRICE_ID_MONTHLY and monthly_trial_days > 0),
    }


@app.get("/billing/status")
def billing_status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Return current user's subscription state."""
    return {
        "user": user,
        "billing_enabled": bool(cfg.STRIPE_SECRET_KEY and (cfg.STRIPE_PRICE_ID_MONTHLY or cfg.STRIPE_PRICE_ID_YEARLY)),
    }


@app.post("/billing/checkout-session")
def billing_checkout_session(
    payload: CheckoutSessionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a Stripe Checkout session for the logged-in user."""
    _reject_showcase_mutation(user)
    if cfg.SHOWCASE_MODE:
        raise HTTPException(status_code=403, detail="subscriptions_closed")
    plan = (payload.plan or "monthly").strip().lower()
    if plan not in ("monthly", "yearly", "trial", "trial_monthly"):
        raise HTTPException(status_code=400, detail="invalid_plan")

    trial_days = 0
    if plan in ("trial", "trial_monthly"):
        price_id = cfg.STRIPE_PRICE_ID_MONTHLY
        trial_days = max(int(cfg.STRIPE_MONTHLY_TRIAL_DAYS or 0), 0)
        if trial_days <= 0:
            raise HTTPException(status_code=400, detail="trial_not_configured")
    else:
        price_id = cfg.STRIPE_PRICE_ID_MONTHLY if plan == "monthly" else cfg.STRIPE_PRICE_ID_YEARLY

    if not price_id:
        raise HTTPException(status_code=400, detail="plan_not_configured")

    # Stripe will redirect back to your public site.
    success_url = f"{cfg.PUBLIC_APP_URL.rstrip('/')}/app/account?checkout=success"
    cancel_url = f"{cfg.PUBLIC_APP_URL.rstrip('/')}/pricing?checkout=cancel"

    try:
        url = create_checkout_session(
            cfg,
            user_id=int(user.get("user_id")),
            price_id=str(price_id),
            success_url=success_url,
            cancel_url=cancel_url,
            customer_id=(user.get("stripe_customer_id") or None),
            customer_email=str(user.get("username")) if user.get("username") else None,
            trial_days=trial_days,
        )
        return {"url": url}
    except RuntimeError as e:
        # Stripe missing / not configured.
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"billing_error: {e}")


@app.post("/billing/portal-session")
def billing_portal_session(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Create a Stripe Customer Portal session."""
    _reject_showcase_mutation(user)
    customer_id = (user.get("stripe_customer_id") or "").strip()
    if not customer_id:
        raise HTTPException(status_code=400, detail="stripe_customer_missing")

    return_url = f"{cfg.PUBLIC_APP_URL.rstrip('/')}/app/account"
    try:
        url = create_billing_portal_session(cfg, customer_id=customer_id, return_url=return_url)
        return {"url": url}
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"billing_error: {e}")


@app.post("/billing/stripe/webhook")
async def billing_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> Dict[str, Any]:
    """Stripe webhook endpoint.

    Configure this in Stripe as:
      https://YOUR_DOMAIN/api/backend/billing/stripe/webhook
    (or route directly to the backend if you don't use the Next.js proxy).
    """
    payload_bytes = await request.body()
    try:
        event_id, processed = process_stripe_webhook(cfg, payload_bytes=payload_bytes, signature=stripe_signature)
        return {"ok": True, "event_id": event_id, "processed": processed}
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"webhook_error: {e}")


# -----------------------------
# Feedback
# -----------------------------


class FeedbackRequest(BaseModel):
    message: str
    page_url: Optional[str] = None
    rating: Optional[int] = None  # 1-5
    metadata: Optional[Dict[str, Any]] = None


@app.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    _reject_showcase_mutation(user)
    msg = (payload.message or "").strip()
    if len(msg) < 3:
        raise HTTPException(status_code=400, detail="message_too_short")

    rating = payload.rating
    if rating is not None and (rating < 1 or rating > 5):
        raise HTTPException(status_code=400, detail="invalid_rating")

    with connect(cfg.DB_DSN) as conn:
        conn.execute(
            """
            INSERT INTO user_feedback (user_id, message, page_url, rating, metadata_json, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                int(user.get("user_id")),
                msg,
                payload.page_url,
                rating,
                json.dumps(payload.metadata or {}),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )

    return {"ok": True}


@app.get("/admin/feedback")
def admin_list_feedback(
    limit: int = Query(100, ge=1, le=500),
    viewer: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        rows = conn.execute(
            """
            SELECT f.feedback_id, f.user_id, u.username, f.message, f.page_url, f.rating, f.created_at
            FROM user_feedback f
            JOIN users u ON u.user_id = f.user_id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        feedback = [dict(r) for r in rows]
        if _is_showcase_viewer(viewer):
            for f in feedback:
                f["username"] = _mask_identity(f.get("username"))
                f["message"] = _scrub_free_text(f.get("message"))
        return {"feedback": feedback}


# -----------------------------
# Support chat
# -----------------------------


class SupportMessageRequest(BaseModel):
    message: str


class AdminSupportReplyRequest(BaseModel):
    message: str
    close_thread: bool | None = None


def _insert_row_id(conn: Any, *, insert_sql: str, params: tuple[Any, ...], id_col: str) -> int:
    """Insert a row and return its generated id (PostgreSQL)."""

    r = conn.execute(insert_sql + f" RETURNING {id_col}", params).fetchone()
    if not r or r.get(id_col) is None:
        raise RuntimeError("insert_failed")
    return int(r[id_col])


@app.get("/support/thread")
def support_get_thread(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get the current user's latest support thread + messages."""

    user_id = int(user.get("user_id"))
    with connect(cfg.DB_DSN) as conn:
        thread = conn.execute(
            """
            SELECT *
            FROM support_threads
            WHERE user_id=?
            ORDER BY (status='open') DESC, updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if thread is None:
            return {"thread": None, "messages": []}

        tid = int(thread["thread_id"])
        msgs = conn.execute(
            """
            SELECT message_id, thread_id, sender_role, sender_user_id, message, created_at
            FROM support_messages
            WHERE thread_id=?
            ORDER BY created_at ASC, message_id ASC
            """,
            (tid,),
        ).fetchall()

        return {"thread": dict(thread), "messages": [dict(m) for m in msgs]}


@app.post("/support/message")
def support_send_message(
    payload: SupportMessageRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Send a support message as the current user.

    If there is no open thread, a new one is created.
    """

    _reject_showcase_mutation(user)
    msg = (payload.message or "").strip()
    if len(msg) < 1:
        raise HTTPException(status_code=400, detail="message_too_short")
    if len(msg) > 4000:
        raise HTTPException(status_code=400, detail="message_too_long")

    user_id = int(user.get("user_id"))
    now = utcnow_iso()

    with connect(cfg.DB_DSN) as conn:

        thread = conn.execute(
            """
            SELECT *
            FROM support_threads
            WHERE user_id=? AND status='open'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if thread is None:
            tid = _insert_row_id(
                conn,
                insert_sql="""
                INSERT INTO support_threads (user_id, status, created_at, updated_at, last_message_at)
                VALUES (?,?,?,?,?)
                """.strip(),
                params=(user_id, "open", now, now, now),
                id_col="thread_id",
            )
        else:
            tid = int(thread["thread_id"])

        mid = _insert_row_id(
            conn,
            insert_sql="""
            INSERT INTO support_messages (thread_id, sender_role, sender_user_id, message, created_at)
            VALUES (?,?,?,?,?)
            """.strip(),
            params=(tid, "user", user_id, msg, now),
            id_col="message_id",
        )

        conn.execute(
            """
            UPDATE support_threads
            SET updated_at=?, last_message_at=?
            WHERE thread_id=?
            """,
            (now, now, tid),
        )

        return {"ok": True, "thread_id": tid, "message_id": mid, "created_at": now}


@app.get("/admin/support/threads")
def admin_support_threads(
    status: str | None = Query(None, description="open|closed"),
    limit: int = Query(50, ge=1, le=200),
    viewer: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    st = (status or "").strip().lower() or None
    if st is not None and st not in ("open", "closed"):
        raise HTTPException(status_code=400, detail="invalid_status")

    with connect(cfg.DB_DSN) as conn:
        where = ""
        params: list[Any] = []
        if st is not None:
            where = "WHERE t.status=?"
            params.append(st)

        rows = conn.execute(
            f"""
            SELECT
              t.thread_id,
              t.user_id,
              u.username,
              t.status,
              t.created_at,
              t.updated_at,
              t.last_message_at,
              (
                SELECT m.message
                FROM support_messages m
                WHERE m.thread_id=t.thread_id
                ORDER BY m.created_at DESC, m.message_id DESC
                LIMIT 1
              ) AS last_message,
              (
                SELECT m.sender_role
                FROM support_messages m
                WHERE m.thread_id=t.thread_id
                ORDER BY m.created_at DESC, m.message_id DESC
                LIMIT 1
              ) AS last_sender_role,
              (
                SELECT COUNT(*)
                FROM support_messages m
                WHERE m.thread_id=t.thread_id
              ) AS message_count
            FROM support_threads t
            JOIN users u ON u.user_id = t.user_id
            {where}
            ORDER BY COALESCE(t.last_message_at, t.updated_at) DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        threads = [dict(r) for r in rows]
        if _is_showcase_viewer(viewer):
            for t in threads:
                t["username"] = _mask_identity(t.get("username"))
                t["last_message"] = _scrub_free_text(t.get("last_message"))
        return {"threads": threads}


@app.get("/admin/support/thread/{thread_id}")
def admin_support_thread_detail(
    thread_id: int,
    viewer: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    tid = int(thread_id)
    with connect(cfg.DB_DSN) as conn:
        thread = conn.execute(
            """
            SELECT t.*, u.username
            FROM support_threads t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.thread_id=?
            """,
            (tid,),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="thread_not_found")

        msgs = conn.execute(
            """
            SELECT
              m.message_id,
              m.thread_id,
              m.sender_role,
              m.sender_user_id,
              su.username AS sender_username,
              m.message,
              m.created_at
            FROM support_messages m
            LEFT JOIN users su ON su.user_id = m.sender_user_id
            WHERE m.thread_id=?
            ORDER BY m.created_at ASC, m.message_id ASC
            """,
            (tid,),
        ).fetchall()

        thread_out = dict(thread)
        messages = [dict(m) for m in msgs]
        if _is_showcase_viewer(viewer):
            thread_out["username"] = _mask_identity(thread_out.get("username"))
            for m in messages:
                m["sender_username"] = _mask_identity(m.get("sender_username"))
                m["message"] = _scrub_free_text(m.get("message"))
        return {"thread": thread_out, "messages": messages}


@app.post("/admin/support/thread/{thread_id}/message")
def admin_support_reply(
    thread_id: int,
    payload: AdminSupportReplyRequest,
    admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    tid = int(thread_id)
    msg = (payload.message or "").strip()
    if len(msg) < 1:
        raise HTTPException(status_code=400, detail="message_too_short")
    if len(msg) > 4000:
        raise HTTPException(status_code=400, detail="message_too_long")

    now = utcnow_iso()
    admin_id = int(admin.get("user_id"))

    with connect(cfg.DB_DSN) as conn:
        thread = conn.execute(
            "SELECT * FROM support_threads WHERE thread_id=?",
            (tid,),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="thread_not_found")

        mid = _insert_row_id(
            conn,
            insert_sql="""
            INSERT INTO support_messages (thread_id, sender_role, sender_user_id, message, created_at)
            VALUES (?,?,?,?,?)
            """.strip(),
            params=(tid, "admin", admin_id, msg, now),
            id_col="message_id",
        )

        # Optionally close the thread
        close = payload.close_thread is True
        if close:
            conn.execute(
                """
                UPDATE support_threads
                SET status='closed', updated_at=?, last_message_at=?
                WHERE thread_id=?
                """,
                (now, now, tid),
            )
        else:
            conn.execute(
                """
                UPDATE support_threads
                SET updated_at=?, last_message_at=?
                WHERE thread_id=?
                """,
                (now, now, tid),
            )

        return {"ok": True, "thread_id": tid, "message_id": mid, "created_at": now, "closed": close}


# -----------------------------
# Tickers
# -----------------------------


@app.get("/tickers")
def list_tickers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=200000),
    q: Optional[str] = None,
    sector: Optional[str] = None,
    sort_by: str = Query("last_filing_desc"),
    include_total: bool = Query(False),
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    """List issuers (tickers) with summary stats.

    Pagination:
      - `limit` + `offset` (offset-based)
      - returns `next_offset` and `prev_offset`

    Design notes:
      - We page at the DB layer for scalability (do not fetch thousands of tickers into the SPA).
      - Search uses ILIKE (case-insensitive) across ticker, issuer name, CIK, and sector.
      - Counts are computed only for the tickers on the current page.

    NOTE: This endpoint relies on issuer_master.last_filing_date for ordering.
    The ingest pipeline updates this field as new filings arrive.
    """

    qn = (q or "").strip()
    like = f"%{qn}%" if qn else None
    sector_name = (sector or "").strip()

    sort_by = (sort_by or "last_filing_desc").strip().lower()
    if sort_by not in ("last_filing_desc", "ticker_asc", "sector_asc"):
        raise HTTPException(status_code=400, detail="invalid_sort_by")

    # Fetch one extra row to determine if there is a next page.
    page_limit = int(limit) + 1

    # Build ORDER BY used in both base and final SELECT.
    if sort_by == "ticker_asc":
        order_base = "ORDER BY im.current_ticker ASC NULLS LAST, im.issuer_cik ASC"
        order_final = "ORDER BY b.current_ticker ASC NULLS LAST, b.issuer_cik ASC"
    elif sort_by == "sector_asc":
        order_base = (
            "ORDER BY f.sector ASC NULLS LAST, im.last_filing_date DESC NULLS LAST, im.current_ticker ASC, im.issuer_cik ASC"
        )
        order_final = (
            "ORDER BY b.sector ASC NULLS LAST, b.last_filing_date DESC NULLS LAST, b.current_ticker ASC, b.issuer_cik ASC"
        )
    else:
        order_base = "ORDER BY im.last_filing_date DESC NULLS LAST, im.current_ticker ASC, im.issuer_cik ASC"
        order_final = "ORDER BY b.last_filing_date DESC NULLS LAST, b.current_ticker ASC, b.issuer_cik ASC"

    with connect(cfg.DB_DSN) as conn:
        total_count: Optional[int] = None
        total_pages: Optional[int] = None

        # Optional total count (for "Page X of Y" UI). We keep this behind a flag because
        # COUNT(*) can be expensive if requested on every page on very large universes.
        if include_total:
            count_sql = """
            SELECT COUNT(*)::bigint AS total_count
            FROM issuer_master im
            LEFT JOIN issuer_fundamentals_cache f ON f.ticker = im.current_ticker
            WHERE im.current_ticker IS NOT NULL
            """
            count_params: List[Any] = []
            if like is not None:
                count_sql += " AND (im.current_ticker ILIKE ? OR im.issuer_name ILIKE ? OR im.issuer_cik ILIKE ? OR f.sector ILIKE ?)"
                count_params.extend([like, like, like, like])
            if sector_name:
                count_sql += " AND f.sector = ?"
                count_params.append(sector_name)

            r = conn.execute(count_sql, tuple(count_params)).fetchone()
            try:
                total_count = int((r or {}).get("total_count") or 0)
            except Exception:
                total_count = 0

            # Avoid importing math; compute ceil(total_count / limit).
            total_pages = (total_count + int(limit) - 1) // int(limit) if int(limit) > 0 else 0
        sql = f"""
        WITH base AS (
            SELECT
                im.issuer_cik,
                im.current_ticker,
                im.issuer_name,
                im.last_filing_date,
                f.sector,
                f.beta
            FROM issuer_master im
            LEFT JOIN issuer_fundamentals_cache f ON f.ticker = im.current_ticker
            WHERE im.current_ticker IS NOT NULL
        """
        params: List[Any] = []

        if like is not None:
            sql += " AND (im.current_ticker ILIKE ? OR im.issuer_name ILIKE ? OR im.issuer_cik ILIKE ? OR f.sector ILIKE ?)"
            params.extend([like, like, like, like])

        if sector_name:
            sql += " AND f.sector = ?"
            params.append(sector_name)

        sql += f"""
            {order_base}
            LIMIT ? OFFSET ?
        ),
        event_counts AS (
            SELECT
                e.issuer_cik,
                COUNT(*) FILTER (WHERE (e.has_buy=1 OR e.has_sell=1)) AS open_market_event_count,
                COUNT(*) FILTER (WHERE (e.ai_buy_rating IS NOT NULL OR e.ai_sell_rating IS NOT NULL OR e.ai_confidence IS NOT NULL)) AS ai_event_count,
                MAX(
                    CASE
                        WHEN e.ai_buy_rating IS NULL AND e.ai_sell_rating IS NULL THEN NULL
                        ELSE GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1))
                    END
                ) AS best_event_ai_rating
            FROM insider_events e
            WHERE e.issuer_cik IN (SELECT issuer_cik FROM base)
            GROUP BY e.issuer_cik
        ),
        cluster_counts AS (
            SELECT
                c.ticker,
                COUNT(*) AS cluster_event_count
            FROM clusters c
            WHERE c.ticker IN (SELECT current_ticker FROM base)
            GROUP BY c.ticker
        )
        SELECT
            b.issuer_cik,
            b.current_ticker,
            b.issuer_name,
            b.last_filing_date,
            COALESCE(ec.open_market_event_count, 0) AS open_market_event_count,
            COALESCE(ec.ai_event_count, 0) AS ai_event_count,
            ec.best_event_ai_rating,
            COALESCE(cc.cluster_event_count, 0) AS cluster_event_count,
            m.market_cap,
            m.market_cap_bucket,
            m.market_cap_updated_at,
            b.sector,
            b.beta
        FROM base b
        LEFT JOIN event_counts ec ON ec.issuer_cik = b.issuer_cik
        LEFT JOIN cluster_counts cc ON cc.ticker = b.current_ticker
        LEFT JOIN market_cap_cache m ON m.ticker = b.current_ticker
        {order_final}
        """

        params.extend([page_limit, offset])
        rows = conn.execute(sql, tuple(params)).fetchall()

        tickers = [dict(r) for r in rows]
        has_next = len(tickers) > limit
        if has_next:
            tickers = tickers[:limit]

        next_offset = offset + limit if has_next else None
        prev_offset = max(offset - limit, 0) if offset > 0 else None

        return {
            "q": qn or None,
            "sector": sector_name or None,
            "sort_by": sort_by,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
            "total_count": total_count,
            "total_pages": total_pages,
            "tickers": tickers,
        }


# -----------------------------
# Events (ticker list)
# -----------------------------
@app.get("/ticker/{ticker}/events")
def ticker_events(
    ticker: str,
    days: Optional[int] = Query(None, ge=1, le=3650, description="Optional lookback window in days"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=50000),
    open_market_only: bool = True,
    cluster_only: bool = False,
    ai_only: bool = False,
    side: str = Query("both"),
    officer_only: bool = False,
    director_only: bool = False,
    ten_percent_only: bool = False,
    min_dollars: Optional[float] = None,
    dollars_side: str = Query("either"),
    sort_by: str = Query("filing_date_desc"),
    include_total: bool = False,
    auto_enqueue_reparse: bool = False,
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    """List events for a ticker.

    Security / product rules:
    - Non-admins are forced to open_market_only=True.
    - Only admins can enable auto_enqueue_reparse.
    """

    t = ticker.strip().upper()
    side = (side or "both").strip().lower()
    if side not in ("both", "buy", "sell"):
        raise HTTPException(status_code=400, detail="invalid_side")

    dollars_side = (dollars_side or "either").strip().lower()
    if dollars_side not in ("either", "buy", "sell"):
        raise HTTPException(status_code=400, detail="invalid_dollars_side")

    sort_by = (sort_by or "filing_date_desc").strip().lower()
    if sort_by not in ("filing_date_desc", "ai_best_desc"):
        raise HTTPException(status_code=400, detail="invalid_sort_by")

    if not user.get("is_admin"):
        open_market_only = True
        auto_enqueue_reparse = False

    with connect(cfg.DB_DSN) as conn:
        issuer = conn.execute(
            """
            SELECT issuer_cik, current_ticker, issuer_name
            FROM issuer_master
            WHERE current_ticker=?
            """,
            (t,),
        ).fetchone()

        market_cap = conn.execute(
            "SELECT * FROM market_cap_cache WHERE ticker=?",
            (t,),
        ).fetchone()

        # Detect stale parse version (do not enqueue unless admin explicitly asks)
        stale = conn.execute(
            "SELECT 1 FROM insider_events WHERE ticker=? AND parse_version<>? LIMIT 1",
            (t, cfg.CURRENT_PARSE_VERSION),
        ).fetchone()
        reparse_needed = stale is not None

        reparse_enqueued = False
        if reparse_needed and auto_enqueue_reparse and user.get("is_admin"):
            enqueue_job(
                conn,
                job_type="REPARSE_TICKER",
                dedupe_key=f"REPARSE|{t}|{cfg.CURRENT_PARSE_VERSION}",
                payload={"ticker": t},
                priority=1,
                max_attempts=1,
            )
            reparse_enqueued = True

        where = ["e.ticker=?"]
        params: List[Any] = [t]

        if days is not None:
            start_date = (date.today() - timedelta(days=int(days))).isoformat()
            where.append("e.filing_date >= ?")
            params.append(start_date)

        if open_market_only:
            where.append("(e.has_buy=1 OR e.has_sell=1)")

        if cluster_only:
            where.append("(e.cluster_flag_buy=1 OR e.cluster_flag_sell=1)")

        if ai_only:
            where.append("(e.ai_buy_rating IS NOT NULL OR e.ai_sell_rating IS NOT NULL OR e.ai_confidence IS NOT NULL)")

        if side == "buy":
            where.append("e.has_buy=1")
        elif side == "sell":
            where.append("e.has_sell=1")

        if officer_only:
            where.append("e.is_officer=1")
        if director_only:
            where.append("e.is_director=1")
        if ten_percent_only:
            where.append("e.is_ten_percent_owner=1")

        if min_dollars is not None:
            try:
                md = float(min_dollars)
            except Exception:
                raise HTTPException(status_code=400, detail="min_dollars_not_numeric")
            if dollars_side == "buy":
                where.append("COALESCE(e.buy_dollars_total,0) >= ?")
                params.append(md)
            elif dollars_side == "sell":
                where.append("COALESCE(e.sell_dollars_total,0) >= ?")
                params.append(md)
            else:
                where.append("(COALESCE(e.buy_dollars_total,0) >= ? OR COALESCE(e.sell_dollars_total,0) >= ?)")
                params.extend([md, md])


        where_sql = " AND ".join(where)

        # For sorting we historically treated "no AI rating" as -1.
        # But that sentinel should not leak into the API payload; use NULL for display.
        best_ai_expr = (
            "CASE WHEN e.ai_buy_rating IS NULL AND e.ai_sell_rating IS NULL "
            "THEN NULL "
            "ELSE GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) END"
        )

        order_sql = ""
        if sort_by == "filing_date_desc":
            order_sql = "ORDER BY e.filing_date DESC, e.event_trade_date DESC"
        else:
            # Sort missing ratings to the bottom, but keep the API value NULL.
            order_sql = f"""
            ORDER BY
              COALESCE(({best_ai_expr}), -1) DESC,
              COALESCE(e.ai_confidence,-1) DESC,
              e.filing_date DESC
            """

        total: Optional[int] = None
        if include_total:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM insider_events e WHERE {where_sql}",
                tuple(params),
            ).fetchone()["n"]

        rows = conn.execute(
            f"""
            SELECT
              e.*,
              {best_ai_expr} AS best_ai_rating,
              {best_ai_expr} AS ai_best,
              im.issuer_name AS issuer_name,
              f.sector AS sector,
              f.beta AS beta
            FROM insider_events e
            LEFT JOIN issuer_master im ON im.issuer_cik = e.issuer_cik
            LEFT JOIN issuer_fundamentals_cache f ON f.ticker = e.ticker
            WHERE {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        events = [_sanitize_event_row_for_viewer(dict(r), is_admin=bool(user.get("is_admin"))) for r in rows]
        next_offset = offset + len(events)
        if len(events) < limit:
            next_offset = None

        return {
            "ticker": t,
            "days": days,
            "issuer": dict(issuer) if issuer is not None else None,
            "market_cap": dict(market_cap) if market_cap is not None else None,
            "reparse_needed": reparse_needed,
            "reparse_enqueued": reparse_enqueued,
            "events": events,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "total": total,
        }


# -----------------------------
# Events (global feed)
# -----------------------------


@app.get("/events")
def list_events(
    days: int = Query(30, ge=1, le=3650, description="Lookback window in days"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=50000),
    open_market_only: bool = True,
    cluster_only: bool = False,
    ai_only: bool = False,
    side: str = Query("both"),
    sort_by: str = Query("filing_date_desc"),
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    """Global events feed, intended for "Top signals" style views.

    Defaults:
      - last 30 days
      - sorted by most recent filing
      - ai_only=False
      - open_market_only=True for non-admins
    """

    side = (side or "both").strip().lower()
    if side not in ("both", "buy", "sell"):
        raise HTTPException(status_code=400, detail="invalid_side")

    sort_by = (sort_by or "filing_date_desc").strip().lower()
    if sort_by not in ("ai_best_desc", "filing_date_desc", "sector_asc"):
        raise HTTPException(status_code=400, detail="invalid_sort_by")

    if not user.get("is_admin"):
        open_market_only = True

    start_date = (date.today() - timedelta(days=int(days))).isoformat()

    where = ["e.filing_date >= ?"]
    params: List[Any] = [start_date]

    if open_market_only:
        where.append("(e.has_buy=1 OR e.has_sell=1)")

    if cluster_only:
        where.append("(e.cluster_flag_buy=1 OR e.cluster_flag_sell=1)")

    if ai_only:
        where.append("(e.ai_buy_rating IS NOT NULL OR e.ai_sell_rating IS NOT NULL OR e.ai_confidence IS NOT NULL)")

    if side == "buy":
        where.append("e.has_buy=1")
    elif side == "sell":
        where.append("e.has_sell=1")

    where_sql = " AND ".join(where)

    # For sorting we historically treated "no AI rating" as -1.
    # But that sentinel should not leak into the API payload; use NULL for display.
    best_ai_expr = (
        "CASE WHEN e.ai_buy_rating IS NULL AND e.ai_sell_rating IS NULL "
        "THEN NULL "
        "ELSE GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) END"
    )

    if sort_by == "filing_date_desc":
        order_sql = "ORDER BY e.filing_date DESC, e.event_trade_date DESC"
    elif sort_by == "sector_asc":
        order_sql = "ORDER BY f.sector ASC NULLS LAST, e.filing_date DESC, e.event_trade_date DESC"
    else:
        order_sql = f"""
        ORDER BY
          COALESCE(({best_ai_expr}), -1) DESC,
          COALESCE(e.ai_confidence,-1) DESC,
          e.filing_date DESC
        """

    with connect(cfg.DB_DSN) as conn:
        rows = conn.execute(
            f"""
            SELECT
              e.*,
              {best_ai_expr} AS best_ai_rating,
              im.issuer_name AS issuer_name,
              f.sector AS sector,
              f.beta AS beta
            FROM insider_events e
            LEFT JOIN issuer_master im ON im.issuer_cik = e.issuer_cik
            LEFT JOIN issuer_fundamentals_cache f ON f.ticker = e.ticker
            WHERE {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        events = [_sanitize_event_row_for_viewer(dict(r), is_admin=bool(user.get("is_admin"))) for r in rows]
        next_offset = offset + len(events)
        if len(events) < limit:
            next_offset = None

        return {
            "days": days,
            "side": side,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "sort_by": sort_by,
            "events": events,
        }


# -----------------------------
# Event detail
# -----------------------------


@app.get("/event/{issuer_cik}/{owner_key}/{accession_number}")
def get_event(
    issuer_cik: str,
    owner_key: str,
    accession_number: str,
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        cik = issuer_cik.zfill(10)
        row = conn.execute(
            """
            SELECT * FROM insider_events
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (cik, owner_key, accession_number),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="event_not_found")

        event = _sanitize_event_row_for_viewer(dict(row), is_admin=bool(user.get("is_admin")))
        ticker_validation = None
        if event.get("ticker"):
            cached_validation = get_cached_validation(conn, cik, str(event.get("ticker") or ""))
            ticker_validation = cached_validation.__dict__ if cached_validation else None

        # Enforce open_market_only for non-admin users even on direct event access.
        # (Admins may browse non-open-market events.)
        if not user.get("is_admin"):
            if not (int(event.get("has_buy") or 0) == 1 or int(event.get("has_sell") or 0) == 1):
                raise HTTPException(status_code=403, detail="open_market_only")

        outcomes = conn.execute(
            """
            SELECT * FROM event_outcomes
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            """,
            (cik, owner_key, accession_number),
        ).fetchall()

        stats = conn.execute(
            """
            SELECT * FROM insider_issuer_stats
            WHERE issuer_cik=? AND owner_key=?
            """,
            (cik, owner_key),
        ).fetchall()
        if ticker_validation and ticker_validation.get("status") == "invalid":
            outcomes = []
            stats = []

        rows_raw = conn.execute(
            """
            SELECT
              row_id,
              is_derivative,
              transaction_code,
              transaction_date,
              shares_abs,
              price,
              shares_owned_following,
              parser_warnings_json
            FROM form4_rows_raw
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            ORDER BY (transaction_date IS NULL) ASC, transaction_date ASC, row_id ASC
            """,
            (cik, owner_key, accession_number),
        ).fetchall()

        # Cluster summaries (optional)
        buy_cluster = None
        sell_cluster = None
        if event.get("cluster_id_buy"):
            buy_cluster = conn.execute(
                "SELECT * FROM clusters WHERE cluster_id=?",
                (event["cluster_id_buy"],),
            ).fetchone()
        if event.get("cluster_id_sell"):
            sell_cluster = conn.execute(
                "SELECT * FROM clusters WHERE cluster_id=?",
                (event["cluster_id_sell"],),
            ).fetchone()

        ai = conn.execute(
            """
            SELECT * FROM ai_outputs
            WHERE issuer_cik=? AND owner_key=? AND accession_number=?
            ORDER BY ai_output_id DESC LIMIT 1
            """,
            (cik, owner_key, accession_number),
        ).fetchone()

        ai_latest = None
        if ai is not None:
            d = dict(ai)
            try:
                d["output"] = json.loads(d.get("output_json") or "null")
            except Exception:
                d["output"] = None
            try:
                d["input"] = json.loads(d.get("input_json") or "null")
            except Exception:
                d["input"] = None

            # Drop big raw strings (we provide parsed objects instead)
            d.pop("output_json", None)
            d.pop("input_json", None)

            ai_latest = _sanitize_ai_latest_for_viewer(d, is_admin=bool(user.get("can_view_admin")))

        # Trade plan (technicals-only) for eligible BUY signals.
        trade_plan = None
        try:
            trade_plan = compute_trade_plan_for_event(
                conn,
                cfg,
                event,
                ai_output=(ai_latest.get("output") if isinstance(ai_latest, dict) else None),
            )
        except Exception:
            trade_plan = None
        return {
            "event": event,
            "rows": [dict(r) for r in rows_raw],
            "outcomes": [dict(r) for r in outcomes],
            "stats": [dict(r) for r in stats],
            "clusters": {
                "buy": dict(buy_cluster) if buy_cluster is not None else None,
                "sell": dict(sell_cluster) if sell_cluster is not None else None,
            },
            "ai_latest": ai_latest,
            "trade_plan": trade_plan,
            "ticker_validation": ticker_validation,
        }


# -----------------------------
# Prices (for charts)
# -----------------------------


@app.get("/ticker/{ticker}/prices")
def ticker_prices(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=20000),
    user: Dict[str, Any] = Depends(require_subscription),
) -> Dict[str, Any]:
    t = ticker.strip().upper()

    def _parse_date(s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        try:
            # accept YYYY-MM-DD
            date.fromisoformat(s)
            return s
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid_date: {s}")

    start_s = _parse_date(start)
    end_s = _parse_date(end)

    today = datetime.now(timezone.utc).date().isoformat()
    if end_s is None:
        end_s = today
    if start_s is None:
        # default 1y lookback
        d = datetime.fromisoformat(end_s).date() - timedelta(days=365)
        start_s = d.isoformat()

    with connect(cfg.DB_DSN) as conn:
        issuer = conn.execute(
            "SELECT issuer_cik, current_ticker FROM issuer_master WHERE current_ticker=?",
            (t,),
        ).fetchone()

        issuer_cik = None
        if issuer is not None:
            issuer_cik = issuer["issuer_cik"]
        else:
            # Fallback: look up from events (if issuer_master isn't populated)
            r = conn.execute(
                "SELECT issuer_cik FROM insider_events WHERE ticker=? LIMIT 1",
                (t,),
            ).fetchone()
            if r is not None:
                issuer_cik = r["issuer_cik"]

        if not issuer_cik:
            raise HTTPException(status_code=404, detail="ticker_not_found")

        validation = get_cached_validation(conn, issuer_cik, t)
        if validation and validation.status == "invalid":
            return {
                "ticker": t,
                "issuer_cik": issuer_cik,
                "start": start_s,
                "end": end_s,
                "prices": [],
                "ticker_validation": validation.__dict__,
            }

        rows = conn.execute(
            """
            SELECT date, adj_close
            FROM issuer_prices_daily
            WHERE issuer_cik=? AND date>=? AND date<=?
            ORDER BY date ASC
            LIMIT ?
            """,
            (issuer_cik, start_s, end_s, limit),
        ).fetchall()

        return {
            "ticker": t,
            "issuer_cik": issuer_cik,
            "start": start_s,
            "end": end_s,
            "prices": [dict(r) for r in rows],
            "ticker_validation": validation.__dict__ if validation else None,
        }


# -----------------------------
# Admin-only ops endpoints (read-only for now)
# -----------------------------


@app.get("/admin/jobs")
def admin_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _admin: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        # Always return status counts for quick triage
        crows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status"
        ).fetchall()
        counts = {str(r["status"]): int(r["count"]) for r in crows}

        where = ""
        params: List[Any] = []
        if status:
            st = status.strip().lower()
            if st not in ("pending", "running", "success", "error"):
                raise HTTPException(status_code=400, detail="invalid_job_status")
            where = "WHERE status=?"
            params.append(st)

        rows = conn.execute(
            f"""
            SELECT *
            FROM jobs
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        jobs = [dict(r) for r in rows]
        for j in jobs:
            j["last_error"] = _scrub_secrets(j.get("last_error"))
        return {"jobs": jobs, "counts": counts}


@app.get("/admin/monitoring")
def admin_monitoring(
    window_hours: int = Query(24, ge=1, le=168),
    limit_types: int = Query(25, ge=1, le=200),
    _admin: Dict[str, Any] = Depends(require_admin_viewer),
) -> Dict[str, Any]:
    """Lightweight operational metrics for admins."""

    def _to_int(x: Any) -> int:
        try:
            return int(x or 0)
        except Exception:
            return 0

    def _to_float(x: Any) -> float | None:
        if x is None:
            return None
        try:
            return float(x)
        except Exception:
            return None

    with connect(cfg.DB_DSN) as conn:
        # Status counts
        srows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status"
        ).fetchall()
        status_counts = {str(r["status"]): _to_int(r["count"]) for r in srows}

        # Oldest pending age (seconds)
        oldest_pending_age_sec: float | None = None
        if status_counts.get("pending", 0) > 0:
            r = conn.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at::timestamptz))) AS age_sec
                FROM jobs
                WHERE status='pending'
                """
            ).fetchone()
            oldest_pending_age_sec = _to_float(r["age_sec"] if r else None)

        # Pending + error breakdown
        pending_by_type = conn.execute(
            """
            SELECT job_type, COUNT(*) AS count
            FROM jobs
            WHERE status='pending'
            GROUP BY job_type
            ORDER BY count DESC
            LIMIT ?
            """,
            (limit_types,),
        ).fetchall()

        error_by_type = conn.execute(
            """
            SELECT job_type, COUNT(*) AS count
            FROM jobs
            WHERE status='error'
            GROUP BY job_type
            ORDER BY count DESC
            LIMIT ?
            """,
            (limit_types,),
        ).fetchall()

        # Throughput per hour
        trows = conn.execute(
            """
            SELECT date_trunc('hour', updated_at::timestamptz) AS bucket,
                   status,
                   COUNT(*) AS count
            FROM jobs
            WHERE status IN ('success','error')
              AND updated_at::timestamptz >= (NOW() - (? * INTERVAL '1 hour'))
            GROUP BY bucket, status
            ORDER BY bucket ASC
            """,
            (window_hours,),
        ).fetchall()

        # Build full bucket list so the chart is stable.
        end_bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start_bucket = end_bucket - timedelta(hours=max(window_hours - 1, 0))
        buckets = [start_bucket + timedelta(hours=i) for i in range(window_hours)]
        points: Dict[str, Dict[str, Any]] = {
            b.isoformat().replace("+00:00", "Z"): {"hour": b.isoformat().replace("+00:00", "Z"), "success": 0, "error": 0}
            for b in buckets
        }

        for r in trows:
            st = str(r.get("status")) if r.get("status") is not None else ""
            if st not in ("success", "error"):
                continue

            bucket_val = r.get("bucket")
            if isinstance(bucket_val, datetime):
                bdt = bucket_val
            else:
                try:
                    bdt = datetime.fromisoformat(str(bucket_val).replace("Z", "+00:00"))
                except Exception:
                    continue

            bkey = (
                bdt.astimezone(timezone.utc)
                .replace(minute=0, second=0, microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            if bkey not in points:
                continue
            points[bkey][st] = _to_int(r.get("count"))

        throughput_hourly = [points[k] for k in sorted(points.keys())]

        # Latency (successful jobs only)
        lrows = conn.execute(
            """
            WITH base AS (
              SELECT job_type,
                     EXTRACT(EPOCH FROM (updated_at::timestamptz - created_at::timestamptz)) AS latency_sec
              FROM jobs
              WHERE status='success'
                AND updated_at::timestamptz >= (NOW() - (? * INTERVAL '1 hour'))
            )
            SELECT job_type,
                   COUNT(*) AS n,
                   AVG(latency_sec) AS avg_sec,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_sec) AS p50_sec,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_sec) AS p95_sec
            FROM base
            GROUP BY job_type
            ORDER BY n DESC
            LIMIT ?
            """,
            (window_hours, limit_types),
        ).fetchall()

        latency_by_type: List[Dict[str, Any]] = []
        for r in lrows:
            latency_by_type.append(
                {
                    "job_type": str(r.get("job_type")),
                    "n": _to_int(r.get("n")),
                    "avg_sec": _to_float(r.get("avg_sec")),
                    "p50_sec": _to_float(r.get("p50_sec")),
                    "p95_sec": _to_float(r.get("p95_sec")),
                }
            )

        # Backfill queue counts
        try:
            bq = conn.execute(
                "SELECT status, COUNT(*) AS count FROM backfill_queue GROUP BY status ORDER BY status"
            ).fetchall()
            backfill_counts = [{"status": str(r["status"]), "count": _to_int(r["count"])} for r in bq]
        except Exception:
            backfill_counts = []

        # Small table snapshots
        table_counts: Dict[str, int] = {}
        for table in ("issuer_master", "insider_events", "ai_outputs", "users"):
            try:
                r = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                table_counts[table] = _to_int(r.get("n") if r else 0)
            except Exception:
                table_counts[table] = 0

        # Recent errors
        erows = conn.execute(
            """
            SELECT job_id, job_type, status, dedupe_key, attempts, last_error, created_at, updated_at
            FROM jobs
            WHERE status='error'
            ORDER BY updated_at DESC
            LIMIT 50
            """
        ).fetchall()

        return {
            "now": utcnow_iso(),
            "window_hours": window_hours,
            "dialect": "postgres",
            "status_counts": status_counts,
            "oldest_pending_age_sec": oldest_pending_age_sec,
            "pending_by_type": [
                {"job_type": str(r["job_type"]), "count": _to_int(r["count"])} for r in pending_by_type
            ],
            "error_by_type": [
                {"job_type": str(r["job_type"]), "count": _to_int(r["count"])} for r in error_by_type
            ],
            "throughput_hourly": throughput_hourly,
            "latency_by_type": latency_by_type,
            "backfill_counts": backfill_counts,
            "table_counts": table_counts,
            "recent_errors": [{**dict(r), "last_error": _scrub_secrets(r.get("last_error"))} for r in erows],
        }


@app.post("/admin/enqueue/reparse_ticker")
def admin_reparse_ticker(
    payload: Dict[str, Any],
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    t = str(payload.get("ticker") or "").strip().upper()
    if not t:
        raise HTTPException(status_code=400, detail="missing_ticker")

    with connect(cfg.DB_DSN) as conn:
        enqueue_job(
            conn,
            job_type="REPARSE_TICKER",
            dedupe_key=f"REPARSE|{t}|{cfg.CURRENT_PARSE_VERSION}",
            payload={"ticker": t},
            priority=1,
            max_attempts=1,
        )
    return {"enqueued": True, "ticker": t}


@app.post("/ingest/accession")
def ingest_accession_endpoint(
    payload: Dict[str, Any],
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    accession = str(payload.get("accession_number") or "").strip()
    if not accession:
        raise HTTPException(status_code=400, detail="missing_accession_number")

    with connect(cfg.DB_DSN) as conn:
        enqueue_job(
            conn,
            job_type="FETCH_ACCESSION_DOCS",
            dedupe_key=f"FETCH|{accession}",
            payload={"accession_number": accession},
            priority=1,
        )
    return {"enqueued": True, "accession_number": accession}


class BackfillRequest(BaseModel):
    start_year: int | None = None
    batch_size: int | None = None


@app.post("/admin/backfill_ticker/{ticker}")
def admin_backfill_ticker(
    ticker: str,
    payload: BackfillRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    t = ticker.strip().upper()
    if not t:
        raise HTTPException(status_code=400, detail="missing_ticker")

    start_year = int(payload.start_year or cfg.BACKFILL_START_YEAR)
    batch_size = int(payload.batch_size or cfg.BACKFILL_BATCH_SIZE)

    with connect(cfg.DB_DSN) as conn:
        row = conn.execute(
            "SELECT issuer_cik FROM issuer_master WHERE current_ticker=?",
            (t,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="ticker_not_found")

        cik = str(row["issuer_cik"]).zfill(10)

        enqueue_job(
            conn,
            job_type="BACKFILL_DISCOVER_ISSUER",
            dedupe_key=f"BACKFILL_DISCOVER|{cik}|{start_year}",
            payload={"issuer_cik": cik, "start_year": start_year, "batch_size": batch_size},
            priority=3,
            requeue_if_exists=True,
        )

        # Ensure benchmark series exists for excess-return stats (optional but helpful)
        enqueue_job(
            conn,
            job_type="FETCH_BENCHMARK_PRICES",
            dedupe_key=f"BENCH_PRICES|{cfg.BENCHMARK_SYMBOL}",
            payload={"symbol": cfg.BENCHMARK_SYMBOL},
            priority=1,
            requeue_if_exists=True,
        )

    return {
        "enqueued": True,
        "ticker": t,
        "issuer_cik": cik,
        "start_year": start_year,
        "batch_size": batch_size,
    }


@app.post("/admin/fetch_benchmark_prices")
def admin_fetch_benchmark_prices(
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        enqueue_job(
            conn,
            job_type="FETCH_BENCHMARK_PRICES",
            dedupe_key=f"BENCH_PRICES|{cfg.BENCHMARK_SYMBOL}",
            payload={"symbol": cfg.BENCHMARK_SYMBOL},
            priority=1,
            requeue_if_exists=True,
        )
    return {"enqueued": True, "symbol": cfg.BENCHMARK_SYMBOL}


class RegenerateAIRequest(BaseModel):
    force: bool = True


@app.post("/admin/event/{issuer_cik}/{owner_key}/{accession_number}/regenerate_ai")
def admin_regenerate_ai(
    issuer_cik: str,
    owner_key: str,
    accession_number: str,
    payload: RegenerateAIRequest,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    cik = issuer_cik.zfill(10)
    acc = accession_number.strip()
    if not acc:
        raise HTTPException(status_code=400, detail="missing_accession_number")

    with connect(cfg.DB_DSN) as conn:
        if not is_ai_classification_enabled(conn):
            raise HTTPException(status_code=409, detail="ai_classification_paused")

    with connect(cfg.DB_DSN) as conn:
        enqueue_job(
            conn,
            job_type="RUN_AI_FOR_EVENT",
            dedupe_key=f"AI|{cik}|{owner_key}|{acc}|{cfg.PROMPT_VERSION}",
            payload={
                "issuer_cik": cik,
                "owner_key": owner_key,
                "accession_number": acc,
                "force": bool(payload.force),
                # Explicit admin action -> allow AI regardless of ingest source.
                "ingest_source": "admin",
                "ai_requested": True,
            },
            # Admin-triggered regenerate should jump to the front and overwrite
            # any existing pending non-force job for the same event.
            priority=1000,
            max_attempts=10,
            requeue_if_exists=True,
            promote_if_pending=True,
        )

    return {
        "enqueued": True,
        "event_key": {"issuer_cik": cik, "owner_key": owner_key, "accession_number": acc},
        "force": bool(payload.force),
    }


class SocialTemplateRequest(BaseModel):
    mode: str = "new_signal"  # new_signal|best_performing
    source_signal_id: str


def _social_signal_id(row: Dict[str, Any]) -> str:
    return f"{row.get('issuer_cik')}:{row.get('owner_key')}:{row.get('accession_number')}"


def _attach_social_post_status(conn: Any, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids: List[str] = []
    for row in rows:
        signal_ids = row.get("collapsed_signal_ids")
        if isinstance(signal_ids, list):
            ids.extend(str(x) for x in signal_ids if x)
        elif row.get("signal_id"):
            ids.append(str(row.get("signal_id")))

    unique_ids = sorted(set(ids))
    if not unique_ids:
        return rows

    placeholders = ",".join("?" for _ in unique_ids)
    post_rows = conn.execute(
        f"""
        SELECT source_signal_id, status, x_tweet_url, posted_at, created_at
        FROM social_posts
        WHERE source_signal_id IN ({placeholders})
        ORDER BY created_at DESC
        """,
        tuple(unique_ids),
    ).fetchall()
    posts_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in post_rows:
        sid = str(r["source_signal_id"])
        posts_by_id.setdefault(sid, []).append(dict(r))

    for row in rows:
        signal_ids = row.get("collapsed_signal_ids")
        candidate_ids = signal_ids if isinstance(signal_ids, list) else [row.get("signal_id")]
        matches = [post for x in candidate_ids if x for post in posts_by_id.get(str(x), [])]
        posted = next((m for m in matches if m.get("status") == "posted"), None)
        latest = posted or (matches[0] if matches else None)
        row["is_posted"] = bool(posted)
        row["social_status"] = latest.get("status") if latest else None
        row["social_posted_at"] = latest.get("posted_at") if latest else None
        row["social_tweet_url"] = latest.get("x_tweet_url") if latest else None
    return rows


def _query_recent_social_signals(conn: Any, *, limit: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.issuer_cik, e.owner_key, e.accession_number, e.ticker, e.filing_date, e.event_trade_date,
               e.owner_name_display AS insider_name, e.owner_title AS insider_role,
               COALESCE(e.buy_dollars_total, e.sell_dollars_total) AS transaction_dollar_value,
               CASE WHEN e.has_buy=1 THEN 'BUY' WHEN e.has_sell=1 THEN 'SELL' ELSE 'SIGNAL' END AS signal_side,
               GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) AS signal_score,
               im.issuer_name
        FROM insider_events e
        LEFT JOIN issuer_master im ON im.issuer_cik=e.issuer_cik
        WHERE (e.has_buy=1 OR e.has_sell=1)
          AND e.ticker IS NOT NULL AND BTRIM(e.ticker) <> ''
        ORDER BY COALESCE(NULLIF(e.filing_date,''), NULLIF(e.event_trade_date,'')) DESC,
                 GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["signal_id"] = _social_signal_id(d)
        d["detail_path"] = f"/app/event/{d.get('issuer_cik')}/{d.get('owner_key')}/{d.get('accession_number')}"
        d["collapsed_signal_ids"] = [d["signal_id"]]
        out.append(d)
    return out


def _get_signal_row_for_social(conn: Any, source_signal_id: str) -> Dict[str, Any] | None:
    try:
        cik, owner_key, acc = [x.strip() for x in str(source_signal_id).split(":", 2)]
    except Exception:
        return None
    row = conn.execute(
        """
        SELECT e.issuer_cik, e.owner_key, e.accession_number, e.ticker, e.filing_date, e.event_trade_date,
               e.owner_name_display, e.owner_title,
               COALESCE(e.buy_dollars_total, e.sell_dollars_total) AS transaction_dollar_value,
               CASE WHEN e.has_buy=1 THEN 'BUY' WHEN e.has_sell=1 THEN 'SELL' ELSE 'SIGNAL' END AS signal_side,
               GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) AS signal_score,
               im.issuer_name
        FROM insider_events e
        LEFT JOIN issuer_master im ON im.issuer_cik=e.issuer_cik
        WHERE e.issuer_cik=? AND e.owner_key=? AND e.accession_number=?
        """,
        (cik, owner_key, acc),
    ).fetchone()
    return dict(row) if row else None


def _load_signal_chart_payload(conn: Any, signal: Dict[str, Any]) -> Dict[str, Any] | None:
    issuer_cik = str(signal.get("issuer_cik") or "").strip()
    if not issuer_cik:
        return None
    ticker = str(signal.get("ticker") or "").strip().upper()
    if ticker and get_validation_status(conn, issuer_cik, ticker) == "invalid":
        return None
    signal_date = str(signal.get("filing_date") or signal.get("event_trade_date") or "").strip()[:10]
    if not signal_date:
        return None
    start = (date.fromisoformat(signal_date) - timedelta(days=5)).isoformat()
    rows = conn.execute(
        """
        SELECT date, adj_close
        FROM issuer_prices_daily
        WHERE issuer_cik=? AND date>=? AND adj_close IS NOT NULL
        ORDER BY date ASC
        LIMIT 800
        """,
        (issuer_cik, start),
    ).fetchall()
    if not rows:
        return None
    prices = [float(r["adj_close"]) for r in rows]
    dates = [str(r["date"]) for r in rows]
    start_idx = 0
    for i, d in enumerate(dates):
        if d >= signal_date:
            start_idx = i
            break
    signal_price = prices[start_idx]
    latest_price = prices[-1]
    ret = ((latest_price / signal_price) - 1.0) * 100.0 if signal_price else 0.0
    return {
        "ticker": str(signal.get("ticker") or ""),
        "dates": dates,
        "prices": prices,
        "signal_date": dates[start_idx],
        "signal_price": signal_price,
        "latest_price": latest_price,
        "return_pct": ret,
    }


def _build_social_template(signal: Dict[str, Any], mode: str) -> str:
    ticker = str(signal.get("ticker") or "").upper()
    company = str(signal.get("issuer_name") or "").strip()
    insider = str(signal.get("owner_name_display") or "Insider")
    role = str(signal.get("owner_title") or "")
    filed = str(signal.get("filing_date") or "")[:10]
    score = signal.get("signal_score")
    dollars = signal.get("transaction_dollar_value")
    side = str(signal.get("signal_side") or "SIGNAL")
    promo = "Try InsidrsAI free trial: https://insidrsai.com/pricing"
    if mode == "best_performing":
        head = f"Top performing insider signal: ${ticker}"
    else:
        head = f"New insider {side.lower()} signal detected: ${ticker}"
    lines = [head]
    if company:
        lines.append(company)
    detail = f"{insider}{(' / ' + role) if role else ''}"
    lines.append(detail)
    if dollars:
        lines.append(f"Transaction value: ~${float(dollars):,.0f}")
    if score is not None and float(score) >= 0:
        lines.append(f"Signal score: {float(score):.1f}/10")
    if filed:
        lines.append(f"Filed: {filed}")
    lines.append(promo)
    lines.append("Research signal only. Not financial advice.")
    return "\n".join(lines)

class SocialPostRequest(BaseModel):
    content: str | None = None
    link_url: str | None = None
    source_signal_id: str | None = None
    chart_image_data_url: str | None = None


@app.get("/me/entitlements")
def me_entitlements(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    # Showcase mode turns the paywall off, so everyone gets the paid entitlements.
    return build_entitlements(dict(user, is_paid=True) if cfg.SHOWCASE_MODE else user)


def _best_performing_response(days: int, limit: int) -> Dict[str, Any]:
    def load() -> Dict[str, Any]:
        with connect(cfg.DB_DSN) as conn:
            as_of = _market_data_as_of(conn)
            results = _query_best_performing_signals(conn, days=days, limit=limit)
        return {"days": days, "limit": limit, "as_of": as_of, "results": results}

    # Rankings only move when new prices land, so a short cache keeps the landing page fast.
    return _cached(("best_performing", days, limit), load)


@app.get("/signals/best-performing")
def best_performing_signals(
    days: int = Query(60, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    hard_limit = min(int(limit), 20)
    free_limit = None if cfg.SHOWCASE_MODE else get_result_limit_for_user(user, "best_performing_signals")
    if free_limit is not None:
        hard_limit = min(hard_limit, free_limit)

    out = _best_performing_response(int(days), hard_limit)
    return {**out, "is_limited": free_limit is not None}


@app.get("/public/signals/best-performing")
def public_best_performing_signals(
    days: int = Query(60, ge=1, le=365),
    limit: int = Query(5, ge=1, le=20),
) -> Dict[str, Any]:
    # Showcase mode shows the full top 20 publicly; the paid product previewed 5.
    hard_limit = min(int(limit), 20 if cfg.SHOWCASE_MODE else 5)
    return _best_performing_response(int(days), hard_limit)


@app.get("/admin/social/x/candidates")
def social_x_candidates(
    mode: str = Query("new_signal"),
    limit: int = Query(30, ge=1, le=50),
    user: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    mode = (mode or "new_signal").strip().lower()
    if mode not in ("new_signal", "best_performing"):
        raise HTTPException(status_code=400, detail="invalid_mode")
    with connect(cfg.DB_DSN) as conn:
        if mode == "best_performing":
            candidates = _query_best_performing_signals(conn, days=60, limit=min(int(limit), 20))
        else:
            candidates = _query_recent_social_signals(conn, limit=int(limit))
        candidates = _attach_social_post_status(conn, candidates)
    return {"mode": mode, "limit": int(limit), "candidates": candidates}


def _query_best_performing_signals(conn: Any, *, days: int, limit: int) -> List[Dict[str, Any]]:
    # Anchor the window on the last day we have prices for, not on today. Once price
    # ingestion stops (e.g. the market-data subscription lapses), a window counted back
    # from today only contains filings with no later prices, and the board goes empty.
    as_of_raw = _market_data_as_of(conn)
    try:
        as_of = min(date.fromisoformat(as_of_raw), date.today()) if as_of_raw else date.today()
    except ValueError:
        as_of = date.today()
    start_date = (as_of - timedelta(days=int(days))).isoformat()
    end_date = as_of.isoformat()
    candidate_limit = max(int(limit) * 20, 100)
    rows = conn.execute(
        """
        WITH event_base AS (
          SELECT
            e.issuer_cik, e.owner_key, e.accession_number, e.ticker, im.issuer_name,
            e.filing_date, e.event_trade_date AS transaction_date,
            COALESCE(NULLIF(e.filing_date,''), NULLIF(e.event_trade_date,'')) AS signal_date,
            e.owner_name_display AS insider_name,
            e.owner_title AS insider_role,
            CASE WHEN e.has_buy=1 THEN 'P' WHEN e.has_sell=1 THEN 'S' ELSE NULL END AS transaction_code,
            COALESCE(e.buy_dollars_total, e.sell_dollars_total) AS transaction_dollar_value,
            COALESCE(e.buy_shares_total, e.sell_shares_total) AS shares,
            COALESCE(e.buy_vwap_price, e.sell_vwap_price) AS transaction_price,
            GREATEST(COALESCE(e.ai_buy_rating,-1), COALESCE(e.ai_sell_rating,-1)) AS signal_score,
            COALESCE(e.cluster_flag_buy, e.cluster_flag_sell, 0) AS cluster_flag
          FROM insider_events e
          LEFT JOIN issuer_master im ON im.issuer_cik=e.issuer_cik
          WHERE COALESCE(NULLIF(e.filing_date,''), NULLIF(e.event_trade_date,'')) >= ?
            AND COALESCE(NULLIF(e.filing_date,''), NULLIF(e.event_trade_date,'')) <= ?
            AND e.ticker IS NOT NULL AND BTRIM(e.ticker) <> ''
        ), priced AS (
          SELECT
            b.*,
            sp0.date AS start_date_used,
            sp0.adj_close AS starting_price,
            sp1.date AS latest_date_used,
            sp1.adj_close AS latest_price,
            sp1.source_ticker AS source_ticker
          FROM event_base b
          JOIN LATERAL (
            SELECT p.date, p.adj_close
            FROM issuer_prices_daily p
            WHERE p.issuer_cik = b.issuer_cik
              AND p.date >= b.signal_date
              AND p.adj_close IS NOT NULL
            ORDER BY p.date ASC
            LIMIT 1
          ) sp0 ON TRUE
          JOIN LATERAL (
            SELECT p.date, p.adj_close, p.source_ticker
            FROM issuer_prices_daily p
            WHERE p.issuer_cik = b.issuer_cik
              AND p.adj_close IS NOT NULL
            ORDER BY p.date DESC
            LIMIT 1
          ) sp1 ON TRUE
        )
        SELECT
          *,
          (((latest_price / NULLIF(starting_price,0)) - 1.0) * 100.0) AS percent_return,
          GREATEST(0, ((latest_date_used::date) - (signal_date::date))) AS days_elapsed
        FROM priced
        WHERE starting_price IS NOT NULL AND latest_price IS NOT NULL
        ORDER BY percent_return DESC
        LIMIT ?
        """,
        (start_date, end_date, candidate_limit),
    ).fetchall()

    out: List[Dict[str, Any]] = []
    by_ticker: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        ticker = str(d.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        validation = _ensure_best_performer_ticker_validation(conn, d, ticker)
        if validation and validation.status == "invalid":
            continue
        if validation is None and abs(float(d.get("percent_return") or 0.0)) > 500.0:
            continue
        if validation and validation.status == "unknown" and abs(float(d.get("percent_return") or 0.0)) > 500.0:
            continue
        d["signal_id"] = f"{d.get('issuer_cik')}:{d.get('owner_key')}:{d.get('accession_number')}"
        d["detail_path"] = f"/app/event/{d.get('issuer_cik')}/{d.get('owner_key')}/{d.get('accession_number')}"
        d["ticker_validation"] = validation.__dict__ if validation else None
        insider_name = str(d.get("insider_name") or "").strip()
        existing = by_ticker.get(ticker)
        if existing is None:
            if len(out) >= int(limit):
                continue
            d["ticker"] = ticker
            d["signal_id"] = _social_signal_id(d)
            d["detail_path"] = f"/app/event/{d.get('issuer_cik')}/{d.get('owner_key')}/{d.get('accession_number')}"
            d["insider_count"] = 1 if insider_name else 0
            d["insider_names"] = [insider_name] if insider_name else []
            d["collapsed_signal_count"] = 1
            d["collapsed_signal_ids"] = [d["signal_id"]]
            d["is_collapsed_ticker"] = False
            by_ticker[ticker] = d
            out.append(d)
        else:
            signal_id = _social_signal_id(d)
            existing["collapsed_signal_count"] = int(existing.get("collapsed_signal_count") or 1) + 1
            if signal_id not in existing["collapsed_signal_ids"]:
                existing["collapsed_signal_ids"].append(signal_id)
            if insider_name and insider_name not in existing["insider_names"]:
                existing["insider_names"].append(insider_name)
            existing["insider_count"] = len(existing["insider_names"])
            existing["is_collapsed_ticker"] = int(existing.get("collapsed_signal_count") or 1) > 1
    return out


def _ensure_best_performer_ticker_validation(conn: Any, row: Dict[str, Any], ticker: str):
    issuer_cik = str(row.get("issuer_cik") or "").strip()
    if not issuer_cik or not ticker:
        return None

    cached = get_cached_validation(conn, issuer_cik, ticker)
    if cached is not None:
        return cached

    # Showcase mode has no live market-data provider; never block a page view on it.
    if cfg.SHOWCASE_MODE:
        return None

    try:
        return validate_issuer_ticker(
            conn,
            cfg,
            issuer_cik=issuer_cik,
            ticker=ticker,
            eodhd_symbol=str(row.get("source_ticker") or "").strip() or None,
        )
    except Exception as e:
        _debug(f"Ticker validation unavailable for best performer issuer_cik={issuer_cik} ticker={ticker}: {e}")
        return None



@app.post("/admin/social/x/template")
def social_x_template(payload: SocialTemplateRequest, user: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    mode = (payload.mode or "new_signal").strip().lower()
    if mode not in ("new_signal", "best_performing"):
        raise HTTPException(status_code=400, detail="invalid_mode")
    with connect(cfg.DB_DSN) as conn:
        signal = _get_signal_row_for_social(conn, payload.source_signal_id)
        chart = _load_signal_chart_payload(conn, signal) if signal else None
    if not signal:
        raise HTTPException(status_code=404, detail="source_signal_not_found")
    content = _build_social_template(signal, mode=mode)
    return {"content": ensure_disclaimer(content), "signal": signal, "chart": chart}

@app.post("/admin/social/x/preview")
def preview_x_post(payload: SocialPostRequest, user: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    content = (payload.content or "").strip()
    if not content and payload.source_signal_id:
        content = f"Unusual insider activity detected: signal {payload.source_signal_id}"
    return {"content": ensure_disclaimer(content), "has_chart": bool(payload.chart_image_data_url)}


def _decode_chart_image_data_url(value: str | None) -> bytes | None:
    if not value:
        return None
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise ValueError("invalid_chart_image")
    raw = base64.b64decode(value[len(prefix):], validate=True)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid_chart_image")
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("chart_image_too_large")
    return raw


@app.post("/admin/social/x/post")
def post_x(payload: SocialPostRequest, user: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content_required")
    settings = XSettings(cfg.X_API_KEY, cfg.X_API_SECRET, cfg.X_ACCESS_TOKEN, cfg.X_ACCESS_TOKEN_SECRET, cfg.X_POSTING_ENABLED, cfg.X_HANDLE)
    now = utcnow_iso()
    status = "failed"
    tweet_id = None
    tweet_url = None
    error = None
    final_content = ensure_disclaimer(content)
    try:
        media_id = None
        chart_png = _decode_chart_image_data_url(payload.chart_image_data_url)
        if chart_png:
            media_id = upload_media_to_x(settings, chart_png)
        posted = post_to_x_with_media(settings, final_content, media_id=media_id)
        status = posted.get("status") or "posted"
        tweet_id = posted.get("tweet_id")
        tweet_url = posted.get("tweet_url")
        final_content = posted.get("content") or final_content
    except Exception as e:
        error = str(e)
    with connect(cfg.DB_DSN) as conn:
        row = conn.execute(
            """INSERT INTO social_posts (platform,status,content,link_url,x_tweet_id,x_tweet_url,error_message,source_signal_id,created_by_user_id,created_at,posted_at)
            VALUES ('x',?,?,?,?,?,?,?,?,?,?) RETURNING *""",
            (status, final_content, payload.link_url, tweet_id, tweet_url, error, payload.source_signal_id, int(user["user_id"]), now, now if status in ("posted","dry_run") else None),
        ).fetchone()
    if error:
        raise HTTPException(status_code=400, detail={"error": error, "post": dict(row)})
    return {"post": dict(row)}


@app.get("/admin/social/posts")
def list_social_posts(limit: int = Query(30, ge=1, le=200), user: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    with connect(cfg.DB_DSN) as conn:
        rows = conn.execute("SELECT * FROM social_posts ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
    return {"posts": [dict(r) for r in rows]}
