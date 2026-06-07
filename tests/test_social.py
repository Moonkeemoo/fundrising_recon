"""Тести для fundrec.collect.social — fetch_social_signals / parse_social."""
from __future__ import annotations

from fundrec.collect.social import fetch_social_signals, parse_social

URL = "https://t.me/savelife_in_ua/12345"


# --- parse_social тести ---

def test_parse_social_full_payload():
    """Коли дані є — повертаємо заповнений dict."""
    payload = {
        "url": URL,
        "mentions": 4200,
        "shares": 1800,
        "peak": "2024-03-15",
    }
    result = parse_social(payload)
    assert result["available"] is True
    assert result["mentions"] == 4200
    assert result["shares"] == 1800
    assert result["peak"] == "2024-03-15"
    assert result["url"] == URL


def test_parse_social_partial_payload():
    """Часткові дані — None лише для відсутніх полів."""
    payload = {"url": URL, "mentions": 100}
    result = parse_social(payload)
    assert result["available"] is True
    assert result["mentions"] == 100
    assert result["shares"] is None
    assert result["peak"] is None


def test_parse_social_empty_payload():
    """Порожній payload → available=False, всі поля None (НЕ 0)."""
    result = parse_social({})
    assert result["available"] is False
    assert result["mentions"] is None
    assert result["shares"] is None
    assert result["peak"] is None


def test_parse_social_zero_is_not_none():
    """Явний 0 у даних — НЕ None (0 = known zero, відрізняється від відсутності)."""
    payload = {"url": URL, "mentions": 0, "shares": 0}
    result = parse_social(payload)
    # 0 — дані присутні, але нульові (рідко, але можливо для нового поста)
    assert result["available"] is True
    assert result["mentions"] == 0
    assert result["shares"] == 0


def test_parse_social_result_keys():
    """Обов'язкові ключі завжди присутні."""
    result = parse_social({"url": URL, "mentions": 1})
    for key in ("url", "available", "mentions", "shares", "peak"):
        assert key in result


# --- fetch_social_signals тести ---

class _FakeClient:
    """Підробка клієнта — повертає заданий payload."""

    def __init__(self, payload: dict | None = None):
        self._payload = payload

    def get(self, url: str, **kwargs):
        return self

    @property
    def status_code(self):
        return 200 if self._payload is not None else 403

    def json(self):
        return self._payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_fetch_no_client_returns_unavailable():
    """Без клієнта (типова ситуація — соц-API потребує ключа) → available=False."""
    result = fetch_social_signals(URL)
    assert result["available"] is False
    assert result["mentions"] is None
    assert result["shares"] is None
    assert result["peak"] is None


def test_fetch_with_client_returns_data():
    payload = {"url": URL, "mentions": 500, "shares": 200, "peak": "2024-02-01"}
    client = _FakeClient(payload)
    result = fetch_social_signals(URL, _client=client)
    assert result["available"] is True
    assert result["mentions"] == 500


def test_fetch_honest_null_not_zero():
    """Перевіряємо, що відсутні дані = None, а не 0 (Інв.5)."""
    result = fetch_social_signals(URL)
    assert result["mentions"] is None
    assert result["shares"] is None
