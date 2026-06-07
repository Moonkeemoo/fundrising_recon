"""Колектор Meta Ad Library API (Facebook / Instagram / Threads реклама).

parse_ad(ad) -> dict — чиста функція, тестується на фікстурі.
search_ads(search_terms, *, token, countries, _client, max_results) -> list[dict]
  — мережа ізольована через _client; graceful-skip без токена.

Примітка: повний програмний доступ до Ad Library API може потребувати
підтвердження особи (Meta identity verification). Комерційні/благодійні
оголошення можуть бути доступні частково — recon в фазі F6.
Веб-парсер публічного інтерфейсу Ad Library — майбутня робота (НЕ реалізовано).
"""
from __future__ import annotations

import sys
from typing import Any

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_AD_ARCHIVE_ENDPOINT = f"{_GRAPH_API_BASE}/ads_archive"

_AD_FIELDS = ",".join([
    "id",
    "ad_snapshot_url",
    "page_name",
    "ad_creative_bodies",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "publisher_platforms",
    "impressions",
    "spend",
    "currency",
])


def _range_str(bounds: dict[str, Any] | None) -> str | None:
    """Перетворює dict з lower_bound/upper_bound -> 'lower-upper' або None."""
    if not bounds:
        return None
    lower = bounds.get("lower_bound")
    upper = bounds.get("upper_bound")
    if lower is None and upper is None:
        return None
    return f"{lower}-{upper}"


def parse_ad(ad: dict[str, Any]) -> dict[str, Any]:
    """Нормалізує елемент ads_archive -> dict з провенансом.

    Honest null: impressions_range/spend_range = None якщо відсутні.
    Threads нормально обробляється у publisher_platforms.
    """
    impressions = ad.get("impressions")
    spend = ad.get("spend")

    return {
        "source_url": ad.get("ad_snapshot_url"),
        "platform": "meta_ads",
        "page_name": ad.get("page_name"),
        "ad_creative_bodies": ad.get("ad_creative_bodies") or [],
        "ad_delivery_start": ad.get("ad_delivery_start_time"),
        "ad_delivery_stop": ad.get("ad_delivery_stop_time"),
        "publisher_platforms": ad.get("publisher_platforms") or [],
        "impressions_range": _range_str(impressions),
        "spend_range": _range_str(spend),
        "currency": ad.get("currency"),
    }


def search_ads(
    search_terms: str,
    *,
    token: str | None = None,
    countries: tuple[str, ...] | list[str] = ("UA",),
    _client: Any | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Шукає рекламні оголошення у Meta Ad Library.

    Якщо token не задано (або порожній рядок) — graceful-skip: [] + лог.
    _client інжектиться в тестах (має метод .get(url, params=..., timeout=...)).

    Примітка: full API може потребувати identity verification.
    Web-page fallback парсер — майбутня робота (НЕ реалізовано).
    """
    import os  # pylint: disable=import-outside-toplevel

    if token is None:
        token = os.environ.get("META_ADS_TOKEN", "")

    if not token:
        print("meta_ads: нема токена, пропускаю", file=sys.stderr)
        return []

    if _client is None:
        import httpx  # pragma: no cover
        _client = httpx.Client(timeout=20)  # pragma: no cover

    params = {
        "search_terms": search_terms,
        "ad_reached_countries": list(countries),
        "fields": _AD_FIELDS,
        "limit": str(max_results),
        "access_token": token,
    }
    resp = _client.get(_AD_ARCHIVE_ENDPOINT, params=params, timeout=20)
    resp.raise_for_status()
    data: dict = resp.json()

    return [parse_ad(ad) for ad in data.get("data", [])]
