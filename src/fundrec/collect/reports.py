"""Колектор звітних/лендінгових сторінок: fetch_report + parse_report.

parse_report(url, html) -> dict з ключами:
  url, title, amount_uah, goal_amount, currency_raw, raw_text

Обсяги екстрагуються регекспами по Ukrainian text; числа у базових одиницях валюти.
Honest nulls: відсутні суми = None, НЕ 0 (spec §8, Інв.5).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any


# --- HTML-утилітки ---

class _TitleParser(HTMLParser):
    """Витягує вміст <title>."""

    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and self.title is None:
            self.title = data.strip()


class _TextExtractor(HTMLParser):
    """Витягує текст зі сторінки (без тегів)."""

    def __init__(self):
        super().__init__()
        self._skip = False
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def _extract_title(html: str) -> str | None:
    p = _TitleParser()
    p.feed(html)
    return p.title


def _extract_text(html: str) -> str:
    # Замінюємо &nbsp; та \xa0 на пробіли перед парсингом
    html = html.replace("&nbsp;", " ").replace("\xa0", " ")
    p = _TextExtractor()
    p.feed(html)
    return p.text


# --- Регекспи для сум ---

# Нормалізований текст: пробіли між цифрами = тисячний роздільник
# Формати: "12 500 000 грн", "₴3 200 000", "$150 000", "50 000 000 грн"

def _normalize_spaces(text: str) -> str:
    """Замінює &nbsp; / \xa0 на звичайний пробіл."""
    return text.replace("\xa0", " ").replace("&nbsp;", " ")


def _parse_number(num_str: str) -> float:
    """'12 500 000' → 12500000.0; '3,200,000' → 3200000.0."""
    cleaned = re.sub(r"[\s, ]", "", num_str)
    return float(cleaned)


# Число з пробілами між тисячами (до 15 цифр, 4 групи розрядів)
_NUM_PAT = r"[\d][\d\s ]{0,20}[\d]|[\d]+"

# UAH — "зібрано 12 500 000 грн", "₴ 3 200 000", "грн 50 000"
_UAH_PATTERNS = [
    # "зібрано/collected число грн/гривень/UAH"
    rf"(?:зібрано|collected|raised)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH|₴)",
    # "число грн"
    rf"({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH)",
    # "₴ число"
    rf"[₴]\s*({_NUM_PAT})",
    # USD
    rf"\$\s*({_NUM_PAT})",
]

_GOAL_PATTERNS = [
    rf"(?:ціль|мета|goal|target)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH|₴|грн\.)?",
    rf"(?:ціль|мета|goal)[\s:]*[₴$]?\s*({_NUM_PAT})",
]


def _find_amount(text: str) -> tuple[float | None, str | None]:
    """Перша знайдена сума → (value, currency_raw) або (None, None).

    Пріоритет: 'зібрано X грн' > '₴ X' > 'X грн' (виключаємо 'ціль/мета' перед числом) > '$ X'.
    """
    # 1. "зібрано / collected / raised X грн/₴/$"
    priority_patterns = [
        (rf"(?:зібрано(?:\s+вже)?|collected|raised)\s+({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH)", "грн"),
        (rf"[₴]\s*({_NUM_PAT})", "₴"),
    ]
    for pattern, currency in priority_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    return val, currency
            except (ValueError, IndexError):
                continue

    # 2. "X грн" — але не після ціль/мета/goal/target
    # Шукаємо всі "X грн" і беремо першу, де перед числом нема слів-маркерів цілі
    for m in re.finditer(rf"({_NUM_PAT})\s*(?:грн|гривень|гривні)", text, re.IGNORECASE):
        prefix = text[max(0, m.start() - 30): m.start()].lower()
        if any(w in prefix for w in ("ціль", "мета", "goal", "target", "ціль:")):
            continue
        try:
            val = _parse_number(m.group(1))
            if val > 0:
                return val, "грн"
        except ValueError:
            continue

    # 3. "$X"
    m = re.search(rf"\$\s*({_NUM_PAT})", text)
    if m:
        try:
            val = _parse_number(m.group(1))
            if val > 0:
                return val, "$"
        except ValueError:
            pass

    return None, None


def _find_goal(text: str) -> float | None:
    """Перша знайдена ціль → float або None."""
    for pattern in _GOAL_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    return val
            except (ValueError, IndexError):
                continue
    return None


# --- Публічний API ---

def parse_report(url: str, html: str) -> dict[str, Any]:
    """Парсить HTML звіту/лендінга → сирий dict."""
    html_norm = _normalize_spaces(html)
    text = _extract_text(html_norm)
    title = _extract_title(html_norm)

    amount_uah, currency_raw = _find_amount(text)
    goal_amount = _find_goal(text)

    # Якщо goal == amount (збіг), спробуємо знайти більший goal
    if goal_amount is not None and amount_uah is not None and goal_amount == amount_uah:
        # Шукаємо число більше за amount
        all_nums = re.findall(r"(\d[\d\s]{0,20}\d|\d)\s*(?:грн|гривень|гривні|UAH)?", text)
        candidates = []
        for n in all_nums:
            try:
                v = _parse_number(n)
                if v > amount_uah:
                    candidates.append(v)
            except ValueError:
                pass
        if candidates:
            goal_amount = max(candidates)

    return {
        "url": url,
        "title": title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
        "currency_raw": currency_raw,
        "raw_text": text,
    }


def fetch_report(url: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Завантажує сторінку та парсить як звіт. _client інжектиться в тестах."""
    if _client is None:
        import httpx
        _client = httpx.Client(follow_redirects=True, timeout=20)
    resp = _client.get(url, timeout=20)
    resp.raise_for_status()
    return parse_report(url, resp.text)
