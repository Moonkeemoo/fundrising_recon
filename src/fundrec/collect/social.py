"""Колектор соціальних сигналів (Tier-3): fetch_social_signals + parse_social.

Соціальні API (X/Telegram/Instagram) зазвичай потребують автентифікації.
Коли даних нема — чесний None (НЕ 0, Інв.5/spec §8).

fetch_social_signals(url, *, _client=None) -> dict:
  {url, available: bool, mentions, shares, peak}

parse_social(payload: dict) -> dict — ті самі ключі з нормалізацією.
"""
from __future__ import annotations

from typing import Any

_ABSENT = object()  # sentinel для "ключ відсутній"


def parse_social(payload: dict[str, Any]) -> dict[str, Any]:
    """Нормалізує payload соц-даних → dict з чесними None.

    Якщо payload порожній → available=False, всі поля None.
    Якщо є хоча б одне поле даних (навіть = 0) → available=True.
    """
    if not payload:
        return {
            "url": None,
            "available": False,
            "mentions": None,
            "shares": None,
            "peak": None,
        }

    url = payload.get("url")
    mentions = payload.get("mentions", _ABSENT)
    shares = payload.get("shares", _ABSENT)
    peak = payload.get("peak", _ABSENT)

    # available = True якщо хоча б одне поле даних присутнє (навіть 0)
    has_data = any(v is not _ABSENT for v in (mentions, shares, peak))

    return {
        "url": url,
        "available": has_data,
        "mentions": None if mentions is _ABSENT else mentions,
        "shares": None if shares is _ABSENT else shares,
        "peak": None if peak is _ABSENT else peak,
    }


def fetch_social_signals(url: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Дістає соціальні сигнали для URL.

    Без клієнта (_client=None) → честний unavailable dict (API потребує ключа).
    З клієнтом → викликає get(url), парсить JSON через parse_social.

    Live-реалізація для X/Telegram/Instagram — майбутня робота після отримання доступу.
    """
    if _client is None:
        # Без автентифікованого клієнта — чесно повертаємо недоступно
        return {
            "url": url,
            "available": False,
            "mentions": None,
            "shares": None,
            "peak": None,
        }

    try:
        resp = _client.get(url, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("url", url)
        return parse_social(payload)
    except Exception:
        return {
            "url": url,
            "available": False,
            "mentions": None,
            "shares": None,
            "peak": None,
        }
