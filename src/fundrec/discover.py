"""Discoverer: discover_sources(theme, *, existing_urls, _search, max_results) -> list[str].

Знаходить нові URL-джерела для теми:
1. Викликає _search(query) -> list[str].
2. Фільтрує вже відомі (existing_urls) і дублікати.
3. Повертає до max_results нових унікальних URL.

_search інжектується для тестів. Live-заглушка (# pragma: no cover) — тонка обгортка
навколо веб-пошуку; підключення є питанням майбутньої реалізації.
"""
from __future__ import annotations

from typing import Callable


def _live_search(query: str) -> list[str]:  # pragma: no cover
    """Live-заглушка пошуку. Замінити на реальний пошук (Claude Agent SDK / httpx / DuckDuckGo API).

    Повертає порожній список поки не підключено.
    """
    return []


def discover_sources(
    theme: str,
    *,
    existing_urls: set[str],
    _search: Callable[[str], list[str]] | None = None,
    max_results: int = 10,
) -> list[str]:
    """Знаходить до max_results нових URLs для теми.

    Args:
        theme: Тема/запит для пошуку (наприклад "FPV дрони Україна 2024").
        existing_urls: Набір вже відомих URLs (фільтруємо дублікати).
        _search: Інжектована функція пошуку (query -> list[str]).
                 За замовчуванням — _live_search (stub).
        max_results: Максимальна кількість нових URLs у результаті.

    Returns:
        Список нових унікальних URLs (до max_results).
    """
    search_fn = _search if _search is not None else _live_search
    raw_urls = search_fn(theme)

    # Дедуплікація + фільтрація відомих
    seen: set[str] = set(existing_urls)
    result: list[str] = []

    for url in raw_urls:
        if not isinstance(url, str):
            continue
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
        if len(result) >= max_results:
            break

    return result
