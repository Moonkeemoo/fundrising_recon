"""Перевірка доступності URL: probe_access(url) -> 'public' | 'paywalled' | 'auth' | 'dead'.

Інжектабельний клієнт для тестів (_client=None → httpx).
"""
from __future__ import annotations

from typing import Any

# Маркери paywall у тілі сторінки (нижній регістр)
_PAYWALL_MARKERS = (
    "subscribe to read",
    "paywall",
    "subscription required",
    "sign in to read",
    "premium content",
    "become a member to read",
    "підпишіться щоб читати",
    "лише для передплатників",
)


def probe_access(url: str, *, _client: Any | None = None) -> str:
    """Перевіряє доступність URL; повертає 'public' | 'paywalled' | 'auth' | 'dead'."""
    if _client is None:
        import httpx
        _client = httpx.Client(follow_redirects=True, timeout=15)

    try:
        resp = _client.get(url, timeout=15)
        code = resp.status_code
    except Exception:
        return "dead"

    if code == 402:
        return "paywalled"

    if code in (401, 403):
        return "auth"

    if code >= 400:
        return "dead"

    # 2xx/3xx — перевіряємо маркери paywall у тілі
    body_lower = getattr(resp, "text", "").lower()
    for marker in _PAYWALL_MARKERS:
        if marker in body_lower:
            return "paywalled"

    return "public"
