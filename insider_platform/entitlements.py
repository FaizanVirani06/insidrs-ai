from __future__ import annotations

from typing import Any, Dict

PAID_STATUSES = {"active", "trialing"}
FEATURE_LIMITS_FREE = {
    "recent_signals": 10,
    "best_performing_signals": 5,
    "ticker_search": 10,
    "exports": 0,
    "alerts": 0,
}


def is_admin(user: Dict[str, Any]) -> bool:
    return str(user.get("role") or "").strip().lower() == "admin"


def is_paid_user(user: Dict[str, Any]) -> bool:
    if is_admin(user) or str(user.get("role") or "").strip().lower() == "showcase":
        return True
    status = str(user.get("subscription_status") or "").strip().lower()
    return status in PAID_STATUSES or bool(user.get("is_paid"))


def get_plan_for_user(user: Dict[str, Any]) -> str:
    if is_admin(user):
        return "admin"
    if is_paid_user(user):
        return "paid"
    return "free"


def has_full_access(user: Dict[str, Any]) -> bool:
    return get_plan_for_user(user) in {"paid", "admin"}


def get_result_limit_for_user(user: Dict[str, Any], feature: str) -> int | None:
    if has_full_access(user):
        return None
    return FEATURE_LIMITS_FREE.get(feature)


def build_entitlements(user: Dict[str, Any]) -> Dict[str, Any]:
    plan = get_plan_for_user(user)
    full = plan in {"paid", "admin"}
    return {
        "plan": plan,
        "is_admin": is_admin(user),
        "has_full_access": full,
        "limits": {
            "recent_signals": None if full else FEATURE_LIMITS_FREE["recent_signals"],
            "best_performing_signals": None if full else FEATURE_LIMITS_FREE["best_performing_signals"],
            "exports": None if full else FEATURE_LIMITS_FREE["exports"],
            "alerts": None if full else FEATURE_LIMITS_FREE["alerts"],
        },
        "features": {
            "advanced_filters": full,
            "watchlist_alerts": full,
            "exports": full,
            "social_posting": is_admin(user),
        },
    }
