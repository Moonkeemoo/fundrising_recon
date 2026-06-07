"""Колектор банок Monobank: дістає публічний JSON банки -> сирий dict.

amount/goal у JSON — у копійках; ділимо на 100 -> гривні. Реальний формат
ендпоінта підтвердити на першому живому запуску (spec §10).

parse_jar_html — запасний парсер HTML-сторінки банки (регекспи по тексту).
fetch_jar — пробує JSON спочатку, потім HTML при помилці.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

JAR_URL = "https://send.monobank.ua/jar/{jar_id}"
JAR_JSON_URL = "https://send.monobank.ua/api/handler"  # підтвердити на живому запуску

_NUM_PAT = r"[\d][\d\s]{0,20}[\d]|[\d]+"


def _parse_number(num_str: str) -> float:
    cleaned = re.sub(r"[\s,]", "", num_str)
    return float(cleaned)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()


def _extract_title(html: str) -> str | None:
    p = _TitleParser()
    p.feed(html)
    return p.title


def parse_jar(jar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Парсить JSON-відповідь банки Monobank."""
    amount = payload.get("amount")
    goal = payload.get("goal")
    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": payload.get("title"),
        "amount_uah": (amount / 100.0) if amount is not None else None,
        "goal_amount": (goal / 100.0) if goal is not None else None,
        "currency_raw": payload.get("currency", "UAH"),
    }


def parse_jar_html(jar_id: str, html: str) -> dict[str, Any]:
    """Запасний парсер HTML-сторінки банки Monobank.

    Витягує title, amount_uah і goal_amount через регекспи по видимому тексту.
    Honest null: відсутні поля = None.
    """
    html_norm = html.replace("\xa0", " ").replace("&nbsp;", " ")
    title = _extract_title(html_norm)

    # Витягуємо текст (без тегів) для пошуку регекспами
    text = re.sub(r"<[^>]+>", " ", html_norm)
    text = re.sub(r"\s+", " ", text)

    # Сума: "зібрано X грн" або "₴ X"
    amount_uah: float | None = None
    for pattern in [
        rf"(?:зібрано|collected|raised)\s+({_NUM_PAT})\s*(?:грн|гривень|UAH)",
        rf"[₴]\s*({_NUM_PAT})",
        rf"({_NUM_PAT})\s*(?:грн|гривень)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    amount_uah = val
                    break
            except ValueError:
                continue

    # Ціль: "ціль: X грн"
    goal_amount: float | None = None
    for pattern in [
        rf"(?:ціль|мета|goal|target)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|UAH|₴)?",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    goal_amount = val
                    break
            except ValueError:
                continue

    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
        "currency_raw": "UAH",
    }


def fetch_jar(jar_id: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Дістає банку. _client інжектується в тестах; інакше httpx.

    Спроба 1: JSON-відповідь (parse_jar).
    Запасний шлях: HTML-відповідь (parse_jar_html) якщо resp.json() кидає виняток.
    """
    if _client is None:
        import httpx  # noqa: PLC0415
        _client = httpx.Client(follow_redirects=True)
    resp = _client.get(JAR_URL.format(jar_id=jar_id), timeout=20)
    resp.raise_for_status()
    try:
        return parse_jar(jar_id, resp.json())
    except (ValueError, Exception):  # noqa: BLE001
        # Не JSON — пробуємо HTML
        return parse_jar_html(jar_id, resp.text)
