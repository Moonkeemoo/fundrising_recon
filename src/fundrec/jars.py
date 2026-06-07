"""Утиліти для роботи з банками Monobank: витяг jar-id, парсинг сторінки, fetch.

extract_jar_ids(text) -> list[str]
    Витягує унікальні jar-id з довільного тексту (regex по send/base.monobank.ua).

parse_jar_page(jar_id, html) -> dict
    Парсить HTML-сторінку банки. Пріоритет: вбудований JSON-блок (копійки → гривні).
    Fallback: regex по видимому тексту (грн, ₴). Honest null для відсутніх полів.

fetch_jar_data(jar_id, *, _client=None) -> dict | None
    GET https://send.monobank.ua/jar/<jar_id>, повертає parse_jar_page або None.
    _client інжектується в тестах; live-шлях # pragma: no cover.
"""

from __future__ import annotations

import json
import re
from typing import Any

JAR_URL = "https://send.monobank.ua/jar/{jar_id}"

# Regex для URL send.monobank.ua/jar/<id> та base.monobank.ua/jar/<id>
_JAR_ID_PAT = re.compile(
    r"(?:send|base)\.monobank\.ua/jar/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_NUM_PAT = r"[\d][\d\s]{0,20}[\d]|[\d]+"


def extract_jar_ids(text: str) -> list[str]:
    """Витягує унікальні jar-id з тексту (send.monobank.ua або base.monobank.ua).

    Порядок першої появи зберігається. Дублікати видаляються.
    Повертає [] якщо нічого не знайдено.
    """
    seen: set[str] = set()
    result: list[str] = []
    for m in _JAR_ID_PAT.finditer(text):
        jar_id = m.group(1)
        if jar_id not in seen:
            seen.add(jar_id)
            result.append(jar_id)
    return result


def _parse_number(num_str: str) -> float:
    """Очищає рядок числа (пробіли, коми) і повертає float."""
    return float(re.sub(r"[\s,]", "", num_str))


def _try_json_block(html: str) -> dict[str, Any] | None:
    """Шукає перший <script type="application/json" ...>...</script> блок і парсить."""
    m = re.search(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except (ValueError, json.JSONDecodeError):
        return None


def _extract_title_from_json_or_html(html: str, json_data: dict[str, Any] | None) -> str | None:
    """Витягує title з JSON-даних або з <title> тегу."""
    if json_data:
        title = json_data.get("title")
        if title:
            return str(title)
    # Fallback: <title> тег
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        raw = m.group(1).strip()
        # Прибираємо " | Monobank" суфікс якщо є
        raw = re.sub(r"\s*\|\s*Monobank.*$", "", raw, flags=re.IGNORECASE).strip()
        return raw or None
    return None


def parse_jar_page(jar_id: str, html: str) -> dict[str, Any]:
    """Парсить HTML-сторінку банки Monobank.

    Пріоритет 1: вбудований JSON-блок (amount/goal — у копійках → ділимо на 100).
    Пріоритет 2: regex по видимому тексту (числа у грн/₴).
    Honest null: відсутні поля = None.

    Повертає:
        {jar_id, url, title, amount_uah, goal_amount}
    """
    json_data = _try_json_block(html)

    # Спробуємо JSON-шлях
    amount_uah: float | None = None
    goal_amount: float | None = None

    if json_data:
        raw_amount = json_data.get("amount")
        raw_goal = json_data.get("goal")
        if raw_amount is not None:
            try:
                amount_uah = float(raw_amount) / 100.0
            except (TypeError, ValueError):
                pass
        if raw_goal is not None:
            try:
                goal_amount = float(raw_goal) / 100.0
            except (TypeError, ValueError):
                pass

    # Fallback: regex по видимому тексту якщо JSON не дав чисел
    if amount_uah is None or goal_amount is None:
        html_norm = html.replace("\xa0", " ").replace("&nbsp;", " ")
        text = re.sub(r"<[^>]+>", " ", html_norm)
        text = re.sub(r"\s+", " ", text)

        if amount_uah is None:
            for pattern in [
                rf"(?:зібрано|collected|raised)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|UAH)",
                rf"[₴]\s*({_NUM_PAT})",
                rf"({_NUM_PAT})\s*(?:грн|гривень)",
            ]:
                m_amt = re.search(pattern, text, re.IGNORECASE)
                if m_amt:
                    try:
                        val = _parse_number(m_amt.group(1))
                        if val > 0:
                            amount_uah = val
                            break
                    except ValueError:
                        continue

        if goal_amount is None:
            for pattern in [
                rf"(?:ціль|мета|goal|target)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|UAH|₴)?",
            ]:
                m_goal = re.search(pattern, text, re.IGNORECASE)
                if m_goal:
                    try:
                        val = _parse_number(m_goal.group(1))
                        if val > 0:
                            goal_amount = val
                            break
                    except ValueError:
                        continue

    title = _extract_title_from_json_or_html(html, json_data)

    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
    }


# Regex для ₴-суми у тексті body після JS-рендеру.
# Захоплює числа з пробілами/nbsp як роздільниками тисяч + ./, десятковий.
_RENDERED_AMOUNT_PAT = re.compile(
    r"([\d][\d\s\xa0]*(?:[.,]\d+)?)\s*₴",
)

# Рядки-шум які ігноруємо при пошуку title
_BOILERPLATE_PAT = re.compile(
    r"minimum amount|maximum amount|\+\d+\s*₴|monobank",
    re.IGNORECASE,
)


def _parse_rendered_amount(raw: str) -> float | None:
    """Очищає рядок суми (nbsp, пробіли → пусто; кома→крапка) → float."""
    cleaned = re.sub(r"[\s\xa0]", "", raw).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_rendered_jar(jar_id: str, body_text: str) -> dict[str, Any]:
    """Парсить inner_text body після JS-рендеру сторінки банки Monobank.

    Правило:
    - Перша «…\\xa0₴» або «… ₴» сума = зібрано (amount_uah).
    - Друга — ціль (goal_amount).
    - Title = перший непорожній рядок, що не є сумою і не є boilerplate.

    Повертає:
        {jar_id, url, title, amount_uah, goal_amount}
    Honest null: відсутні поля = None.
    """
    amounts: list[float] = []
    title: str | None = None

    for line in body_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Перевіряємо чи рядок містить ₴-суму
        m = _RENDERED_AMOUNT_PAT.search(stripped)
        if m:
            val = _parse_rendered_amount(m.group(1))
            if val is not None and val >= 0:
                amounts.append(val)
            continue  # рядок з сумою — не title

        # Ігноруємо boilerplate
        if _BOILERPLATE_PAT.search(stripped):
            continue

        # Перший залишений рядок = title
        if title is None:
            title = stripped

    amount_uah = amounts[0] if len(amounts) >= 1 else None
    goal_amount = amounts[1] if len(amounts) >= 2 else None
    # Title повертаємо лише якщо знайдено хоча б одну суму (є ₴ на сторінці = банка)
    resolved_title = title if amount_uah is not None else None

    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": resolved_title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
    }


def fetch_jar_data(jar_id: str, *, _client: Any | None = None) -> dict[str, Any] | None:
    """GET https://send.monobank.ua/jar/<jar_id> → parse_jar_page або None.

    Повертає None якщо виникла HTTP-помилка або виняток.
    _client інжектується в тестах; live httpx: # pragma: no cover.
    """
    if _client is None:  # pragma: no cover
        import httpx  # noqa: PLC0415  # pragma: no cover

        _client = httpx.Client(follow_redirects=True, timeout=20)  # pragma: no cover
    try:
        resp = _client.get(JAR_URL.format(jar_id=jar_id), timeout=20)
        resp.raise_for_status()
        return parse_jar_page(jar_id, resp.text)
    except Exception:  # noqa: BLE001
        return None
