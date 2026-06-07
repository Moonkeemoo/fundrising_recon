"""Playwright-рендер сторінки банки Monobank і кеш результатів.

render_jar(jar_id, *, _render=None, timeout=30000) -> dict | None
    Якщо _render задано (тести) — використовує його замість браузера.
    Інакше — _live_render (Playwright, # pragma: no cover).

render_jar_cached(jar_id, *, cache_path, _render=None) -> dict | None
    Читає JSON-кеш {jar_id: data}; при miss — render_jar, потім зберігає.

_live_render(jar_id, timeout) -> str | None  # pragma: no cover
    Запускає Playwright chromium headless, goto + networkidle + 2.5 s wait,
    повертає page.inner_text("body"). При будь-якій помилці → None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..jars import JAR_URL, parse_rendered_jar


def _live_render(jar_id: str, timeout: int) -> str | None:  # pragma: no cover
    """Запускає headless Chromium і повертає inner_text("body") сторінки банки."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return None

    url = JAR_URL.format(jar_id=jar_id)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout)
                page.wait_for_timeout(2500)
                return page.inner_text("body")
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        return None


def render_jar(
    jar_id: str,
    *,
    _render: Callable[[str], str | None] | None = None,
    timeout: int = 30000,
) -> dict[str, Any] | None:
    """Рендерить сторінку банки і парсить результат.

    _render: ін'єктований виклик в тестах (jar_id -> body_text | None).
    Якщо не задано — використовується _live_render (Playwright).
    Повертає None якщо рендер не вдався або тіло порожнє.
    """
    if _render is not None:
        body = _render(jar_id)
    else:
        body = _live_render(jar_id, timeout)  # pragma: no cover

    if not body:
        return None

    return parse_rendered_jar(jar_id, body)


def render_jar_cached(
    jar_id: str,
    *,
    cache_path: Path | str = config.JARS_CACHE_PATH,
    _render: Callable[[str], str | None] | None = None,
    timeout: int = 30000,
) -> dict[str, Any] | None:
    """Повертає кешовані дані банки або рендерить і кешує.

    Кеш: JSON-файл {jar_id: {jar_id, url, title, amount_uah, goal_amount}}.
    Якщо рендер повернув None — кеш НЕ оновлюється.
    """
    cache_path = Path(cache_path)

    # Читаємо кеш
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    # Cache hit
    if jar_id in cache:
        return cache[jar_id]

    # Cache miss → рендер
    result = render_jar(jar_id, _render=_render, timeout=timeout)
    if result is None:
        return None

    # Зберігаємо
    cache[jar_id] = result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
