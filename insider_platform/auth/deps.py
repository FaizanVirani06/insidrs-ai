from __future__ import annotations

from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insider_platform.db import connect

from .crud import get_user_by_id, public_user
from .security import decode_access_token


_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Dict[str, Any]:
    """Authenticate a request.

    Supports both:
      - Authorization: Bearer <jwt>
      - Cookie-based sessions (httpOnly cookie set by /auth/login)

    This enables a static frontend (Vite/React) to authenticate without a
    server-side proxy that injects Authorization headers.
    """

    cfg = getattr(request.app.state, "cfg", None)
    if cfg is None:
        raise HTTPException(status_code=500, detail="server_config_missing")

    token: str | None = None

    # Prefer Bearer token when explicitly provided.
    if credentials is not None and credentials.credentials:
        token = credentials.credentials

    # Fall back to cookie.
    if not token:
        cookie_name = str(getattr(cfg, "AUTH_COOKIE_NAME", "ip_token") or "ip_token")
        token = request.cookies.get(cookie_name)
        # Back-compat: accept legacy cookie name if configured differently.
        if not token and cookie_name != "ip_token":
            token = request.cookies.get("ip_token")

    if not token:
        # Keep a single detail string so frontends can handle consistently.
        raise _unauthorized("missing_token")

    try:
        payload = decode_access_token(token=token, secret=cfg.AUTH_JWT_SECRET)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("token_expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("token_invalid")
    except Exception:
        raise _unauthorized("token_decode_error")

    sub = payload.get("sub")
    if not sub:
        raise _unauthorized("token_missing_sub")

    try:
        user_id = int(sub)
    except Exception:
        raise _unauthorized("token_sub_not_int")

    with connect(cfg.DB_DSN) as conn:
        row = get_user_by_id(conn, user_id)
        if row is None:
            raise _unauthorized("user_not_found")
        if int(row["is_active"] or 0) != 1:
            raise _unauthorized("user_inactive")
        user = public_user(row)

    # Convenience booleans
    role = str(user.get("role") or "").strip().lower()
    user["is_admin"] = role == "admin"
    user["is_showcase"] = role == "showcase"
    user["can_view_admin"] = role in ("admin", "showcase")
    return user


def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return user


def require_admin_viewer(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if str(user.get("role") or "").strip().lower() not in ("admin", "showcase"):
        raise HTTPException(status_code=403, detail="admin_view_required")
    return user


def require_subscription(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Require an active (paid) subscription.

    Admins are always allowed. For local development you can set BILLING_DEV_BYPASS=1.
    """

    cfg = getattr(request.app.state, "cfg", None)
    if cfg is None:
        raise HTTPException(status_code=500, detail="server_config_missing")

    # Admin/showcase bypass
    if str(user.get("role") or "").strip().lower() in ("admin", "showcase"):
        return user

    # Dev bypass
    if getattr(cfg, "BILLING_DEV_BYPASS", False):
        return user

    # Showcase mode: the paywall is off for everyone.
    if getattr(cfg, "SHOWCASE_MODE", False):
        return user

    status = (user.get("subscription_status") or "").strip().lower()
    if status in ("active", "trialing"):
        return user

    raise HTTPException(status_code=402, detail="subscription_required")
