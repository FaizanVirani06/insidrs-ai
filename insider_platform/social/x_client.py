from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from requests_oauthlib import OAuth1

DISCLAIMER = "Research signal only. Not financial advice."
MAX_POST_LEN = 280


@dataclass
class XSettings:
    api_key: str | None
    api_secret: str | None
    access_token: str | None
    access_token_secret: str | None
    posting_enabled: bool
    handle: str | None


def ensure_disclaimer(content: str) -> str:
    txt = (content or "").strip()
    if DISCLAIMER.lower() in txt.lower():
        return txt
    if txt:
        txt = f"{txt}\n\n{DISCLAIMER}"
    else:
        txt = DISCLAIMER
    return txt


def post_to_x(settings: XSettings, content: str) -> Dict[str, Any]:
    text = ensure_disclaimer(content)
    if len(text) > MAX_POST_LEN:
        raise ValueError(f"post_too_long:{len(text)}")
    if not settings.posting_enabled:
        return {"status": "dry_run", "tweet_id": None, "tweet_url": None, "content": text}

    required = [settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret]
    if not all(required):
        raise RuntimeError("x_credentials_missing")

    auth = OAuth1(settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret)
    res = requests.post(
        "https://api.x.com/2/tweets",
        json={"text": text},
        auth=auth,
        timeout=20,
    )
    if res.status_code >= 300:
        raise RuntimeError(f"x_post_failed:{res.status_code}:{res.text[:300]}")
    body = res.json() if res.content else {}
    tid = str((body.get("data") or {}).get("id") or "").strip() or None
    handle = (settings.handle or "").strip()
    turl = f"https://x.com/{handle}/status/{tid}" if (handle and tid) else None
    return {"status": "posted", "tweet_id": tid, "tweet_url": turl, "content": text}


def upload_media_to_x(settings: XSettings, media_bytes: bytes) -> Optional[str]:
    if not settings.posting_enabled:
        return None
    required = [settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret]
    if not all(required):
        raise RuntimeError("x_credentials_missing")
    auth = OAuth1(settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret)
    res = requests.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        files={"media": ("signal-chart.png", media_bytes, "image/png")},
        auth=auth,
        timeout=30,
    )
    if res.status_code >= 300:
        raise RuntimeError(f"x_media_upload_failed:{res.status_code}:{res.text[:300]}")
    body = res.json() if res.content else {}
    return str(body.get("media_id_string") or "").strip() or None


def post_to_x_with_media(settings: XSettings, content: str, media_id: str | None = None) -> Dict[str, Any]:
    text = ensure_disclaimer(content)
    if len(text) > MAX_POST_LEN:
        raise ValueError(f"post_too_long:{len(text)}")
    if not settings.posting_enabled:
        return {"status": "dry_run", "tweet_id": None, "tweet_url": None, "content": text}
    required = [settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret]
    if not all(required):
        raise RuntimeError("x_credentials_missing")
    auth = OAuth1(settings.api_key, settings.api_secret, settings.access_token, settings.access_token_secret)
    payload: Dict[str, Any] = {"text": text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
    res = requests.post("https://api.x.com/2/tweets", json=payload, auth=auth, timeout=20)
    if res.status_code >= 300:
        raise RuntimeError(f"x_post_failed:{res.status_code}:{res.text[:300]}")
    body = res.json() if res.content else {}
    tid = str((body.get("data") or {}).get("id") or "").strip() or None
    handle = (settings.handle or "").strip()
    turl = f"https://x.com/{handle}/status/{tid}" if (handle and tid) else None
    return {"status": "posted", "tweet_id": tid, "tweet_url": turl, "content": text}
