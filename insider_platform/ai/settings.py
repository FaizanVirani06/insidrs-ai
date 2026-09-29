"""Runtime on/off switch for Gemini classification.

Stored in app_config so an admin can flip it from Site settings without a redeploy.
Off by default: a fresh database (or one that never set the key) makes no Gemini calls.
"""
from __future__ import annotations

from typing import Any, Dict

from insider_platform.db import get_app_config, upsert_app_config
from insider_platform.util.time import utcnow_iso

AI_ENABLED_KEY = "ai_classification_enabled"
AI_UPDATED_AT_KEY = "ai_classification_updated_at"


def is_ai_classification_enabled(conn: Any) -> bool:
    return str(get_app_config(conn, AI_ENABLED_KEY) or "").strip() == "1"


def get_ai_classification_settings(conn: Any) -> Dict[str, Any]:
    return {
        "enabled": is_ai_classification_enabled(conn),
        "updated_at": get_app_config(conn, AI_UPDATED_AT_KEY) or None,
    }


def set_ai_classification_enabled(conn: Any, enabled: bool) -> Dict[str, Any]:
    upsert_app_config(conn, AI_ENABLED_KEY, "1" if enabled else "0")
    upsert_app_config(conn, AI_UPDATED_AT_KEY, utcnow_iso())
    return get_ai_classification_settings(conn)
