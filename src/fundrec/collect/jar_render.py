"""Playwright-рендер сторінки банки Monobank і кеш результатів.

render_jar(jar_id, *, _render=None, timeout=30000) -> dict | None
    Якщо _render задано (тести) — використовує його замість браузера.
    Інакше — _live_render (Playwright, # pragma: no cover).

render_jar_cached(jar_id, *, cache_path, _render=None, now=None) -> dict | None
    Читає JSON-кеш {jar_id: data}; при miss — render_jar, потім зберігає.
    Формат кешу: {jar_id: {...latest fields..., "history": [{"ts": iso, "amount_uah": x, "goal_amount": g}, ...]}}
    Після кожного успішного рендеру додає snapshot до history якщо:
      - сума змінилась; або
      - останній snapshot старший за MIN_SNAPSHOT_INTERVAL_H годин.
    now: ISO-рядок для ін'єкції часу в тестах (default: datetime.now(timezone.utc).isoformat()).

_live_render(jar_id, timeout) -> str | None  # pragma: no cover
    Запускає headless Chromium і повертає inner_text("body") сторінки банки.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..jars import JAR_URL, parse_rendered_jar

# Мінімальний інтервал між snapshot-ами (годин) якщо сума не змінилась
MIN_SNAPSHOT_INTERVAL_H = 6


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


def _now_iso() -> str:  # pragma: no cover
    """Повертає поточний час UTC у форматі ISO (для prod)."""
    return datetime.now(timezone.utc).isoformat()


def _should_append_snapshot(
    history: list[dict],
    new_amount: float | None,
    now_iso: str,
) -> bool:
    """Повертає True якщо потрібно додати новий snapshot.

    Додаємо якщо:
    - history порожня (перший snapshot); або
    - нова сума відрізняється від останньої; або
    - останній snapshot старший за MIN_SNAPSHOT_INTERVAL_H годин.
    """
    if not history:
        return True
    last = history[-1]
    last_amount = last.get("amount_uah")
    # Якщо сума змінилась — завжди додаємо
    if new_amount != last_amount:
        return True
    # Перевіряємо вік останнього snapshot
    try:
        last_ts = datetime.fromisoformat(last["ts"])
        now_dt = datetime.fromisoformat(now_iso)
        # Нормалізуємо timezone-aware порівняння
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        hours_diff = (now_dt - last_ts).total_seconds() / 3600.0
        if hours_diff >= MIN_SNAPSHOT_INTERVAL_H:
            return True
    except (KeyError, ValueError, TypeError):
        return True
    return False


def render_jar_cached(
    jar_id: str,
    *,
    cache_path: Path | str = config.JARS_CACHE_PATH,
    _render: Callable[[str], str | None] | None = None,
    timeout: int = 30000,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Повертає свіжі дані банки і оновлює кеш з history snapshot-ами.

    Кеш: JSON-файл {jar_id: {jar_id, url, title, amount_uah, goal_amount,
                              "history": [{"ts": iso, "amount_uah": x, "goal_amount": g}, ...]}}.
    Зворотна сумісність: повертає dict із тими самими полями (history — додатковий ключ).
    Якщо рендер повернув None — кеш НЕ оновлюється; повертає останні кешовані дані або None.

    now: ISO-рядок для ін'єкції часу в тестах. За замовч. — datetime.now(timezone.utc).
    """
    cache_path = Path(cache_path)
    now_iso: str = now if now is not None else _now_iso()  # pragma: no cover-branch

    # Читаємо кеш
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    # Рендеримо (завжди — щоб отримати свіжі дані і оновити history)
    result = render_jar(jar_id, _render=_render, timeout=timeout)

    if result is None:
        # Render невдалий — повертаємо кешовані дані без history або None
        if jar_id in cache:
            entry = dict(cache[jar_id])
            entry.pop("history", None)
            return entry
        return None

    # Мігруємо: якщо є стара запис без history — ініціалізуємо history
    existing = cache.get(jar_id, {})
    if isinstance(existing, dict):
        history: list[dict] = list(existing.get("history") or [])
    else:
        history = []

    # Додаємо snapshot якщо потрібно
    if _should_append_snapshot(history, result.get("amount_uah"), now_iso):
        history.append({
            "ts": now_iso,
            "amount_uah": result.get("amount_uah"),
            "goal_amount": result.get("goal_amount"),
        })

    # Оновлюємо запис: latest fields + history
    entry: dict[str, Any] = dict(result)
    entry["history"] = history
    cache[jar_id] = entry

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Повертаємо latest fields (без history — зворотна сумісність)
    out = dict(result)
    out["history"] = history
    return out
