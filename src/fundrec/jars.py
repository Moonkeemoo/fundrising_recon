"""Утиліти для роботи з банками Monobank: витяг jar-id, парсинг сторінки, fetch, velocity.

extract_jar_ids(text) -> list[str]
    Витягує унікальні jar-id з довільного тексту (regex по send/base.monobank.ua).

parse_jar_page(jar_id, html) -> dict
    Парсить HTML-сторінку банки. Пріоритет: вбудований JSON-блок (копійки → гривні).
    Fallback: regex по видимому тексту (грн, ₴). Honest null для відсутніх полів.

fetch_jar_data(jar_id, *, _client=None) -> dict | None
    GET https://send.monobank.ua/jar/<jar_id>, повертає parse_jar_page або None.
    _client інжектується в тестах; live-шлях # pragma: no cover.

jar_velocity(history) -> dict
    Обчислює velocity (₴/день) зі списку timestamped snapshot-ів (history).
    Потребує ≥2 snapshots; повертає None-значення якщо недостатньо даних.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

# Мінімальний знаменник часу (секунди) щоб уникнути ділення на ~0
_MIN_SPAN_SECONDS = 1.0

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


def jar_ids_from_raw(raw: dict) -> list[str]:
    """Витягує унікальні jar-id з усіх полів raw-запису.

    Сканує raw.get('text'), кожен елемент raw.get('links') і
    raw.get('description'). Порядок: text → links → description.
    Дублікати (між полями) видаляються; зберігається порядок першої появи.

    Повертає [] якщо jar-id не знайдено або raw порожній.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add_from(text: str | None) -> None:
        if not text:
            return
        for jar_id in extract_jar_ids(text):
            if jar_id not in seen:
                seen.add(jar_id)
                result.append(jar_id)

    _add_from(raw.get("text"))
    for link in raw.get("links") or []:
        _add_from(link)
    _add_from(raw.get("description"))

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


def _parse_snapshot_ts(ts_str: str) -> datetime | None:
    """Парсить ISO timestamp → datetime (UTC-aware). None якщо не вдалось."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def jar_velocity(history: list[dict]) -> dict[str, Any]:
    """Обчислює velocity (₴/день) зі списку timestamped snapshot-ів.

    Алгоритм: (last.amount_uah - first.amount_uah) / span_days,
    де span_days = (last.ts - first.ts) в днях.

    Повертає:
        {
          "uah_per_day": float | None,   — ₴/день (може бути 0 або від'ємне)
          "delta_uah": float | None,     — різниця сум (last - first)
          "span_days": float | None,     — проміжок між першим і останнім snapshot
          "pct_per_day": float | None,   — uah_per_day / goal_amount * 100 (None якщо goal невідомий)
        }

    Повертає None-значення коли:
      - history порожня або має 1 snapshot;
      - amount_uah відсутній (None) хоч у першому, хоч в останньому snapshot;
      - span занадто малий (< _MIN_SPAN_SECONDS) щоб запобігти ділення на ~0.
    """
    _NONE = {"uah_per_day": None, "delta_uah": None, "span_days": None, "pct_per_day": None}

    if not history or len(history) < 2:
        return _NONE

    first = history[0]
    last = history[-1]

    first_amount = first.get("amount_uah")
    last_amount = last.get("amount_uah")

    if first_amount is None or last_amount is None:
        return _NONE

    first_ts = _parse_snapshot_ts(first.get("ts", ""))
    last_ts = _parse_snapshot_ts(last.get("ts", ""))

    if first_ts is None or last_ts is None:
        return _NONE

    span_seconds = (last_ts - first_ts).total_seconds()
    if span_seconds < _MIN_SPAN_SECONDS:
        return _NONE

    span_days = span_seconds / 86400.0
    delta_uah = float(last_amount) - float(first_amount)
    uah_per_day = delta_uah / span_days

    # pct_per_day відносно goal (останнього відомого)
    goal = last.get("goal_amount") or first.get("goal_amount")
    pct_per_day: float | None = None
    if goal is not None and float(goal) > 0:
        pct_per_day = uah_per_day / float(goal) * 100.0

    return {
        "uah_per_day": uah_per_day,
        "delta_uah": delta_uah,
        "span_days": span_days,
        "pct_per_day": pct_per_day,
    }
