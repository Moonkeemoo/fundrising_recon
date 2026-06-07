"""Курс UAH→USD: NBU open API з fallback-таблицею по роках.

Все живе мережеве звернення ін'єктується через `_client` для тестабельності.
"""
from __future__ import annotations

from typing import Callable

# Приблизні річні середні за НБУ (2022–2026).  Використовуються:
#  • коли _client не передано (режим без мережі)
#  • коли клієнт кидає виняток або повертає порожній список
_FALLBACK_RATES: dict[int, float] = {
    2022: 29.5,
    2023: 36.6,
    2024: 39.0,
    2025: 41.5,
    2026: 42.0,
}


def _nbu_url(date_iso: str) -> str:
    """Перетворює '2024-03-15' → URL НБУ для USD на цю дату."""
    date_compact = date_iso.replace("-", "")
    return (
        "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
        f"?valcode=USD&date={date_compact}&json"
    )


def usd_rate(date_iso: str, *, _client: Callable[[str], list] | None = None) -> float:
    """Повертає курс UAH-за-USD для вказаної дати.

    Args:
        date_iso: дата у форматі 'YYYY-MM-DD'.
        _client: ін'єктований HTTP-клієнт (url -> list[dict]).
                 Якщо None — живий виклик НБУ API (pragma: no cover).

    Returns:
        float — курс UAH per 1 USD.
    """
    year = int(date_iso[:4])
    fallback = _FALLBACK_RATES.get(year, 40.0)

    if _client is None:
        return _live_fetch(date_iso, fallback)  # pragma: no cover

    try:
        data = _client(_nbu_url(date_iso))
        if data and isinstance(data, list):
            rate = data[0].get("rate")
            if rate:
                return float(rate)
    except Exception:
        pass
    return fallback


def _live_fetch(date_iso: str, fallback: float) -> float:  # pragma: no cover
    """Живий виклик НБУ API.  Не тестується (мережа)."""
    try:
        import httpx  # noqa: PLC0415

        url = _nbu_url(date_iso)
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            rate = data[0].get("rate")
            if rate:
                return float(rate)
    except Exception:
        pass
    return fallback


def to_usd(
    amount_uah: float | None,
    date_iso: str | None,
    *,
    _client: Callable[[str], list] | None = None,
) -> float | None:
    """Конвертує UAH → USD, None-safe.

    Returns:
        float | None — None якщо будь-який вхід None.
    """
    if amount_uah is None or date_iso is None:
        return None
    rate = usd_rate(date_iso, _client=_client)
    return amount_uah / rate
