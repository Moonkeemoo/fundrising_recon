"""Колектор новинних статей: fetch_article + parse_article.

parse_article(url, html) -> dict:
  url, title, published, amount_uah, raw_text

Дата береться з <time datetime=...> або <meta name="article:published_time">.
Суми — той самий robust-regex підхід з reports.py.
Tier-2 джерело (spec §3).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any


# --- HTML-парсери ---

class _MetaParser(HTMLParser):
    """Витягує <title>, <time datetime>, meta article:published_time."""

    def __init__(self):
        super().__init__()
        self._in_title = False
        self._in_time = False
        self.title: str | None = None
        self.published: str | None = None
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "time":
            self._in_time = True
            dt = attrs_dict.get("datetime")
            if dt and self.published is None:
                self.published = dt
        elif tag == "meta":
            name = attrs_dict.get("name", "") or attrs_dict.get("property", "")
            content = attrs_dict.get("content", "")
            if name in ("article:published_time", "og:article:published_time") and content:
                if self.published is None:
                    self.published = content
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "time":
            self._in_time = False
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if self._in_title and self.title is None:
            self.title = data.strip()
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._parts)


# --- Числа — повторно використовуємо логіку з reports.py ---

_NUM_PAT = r"[\d][\d\s ]{0,20}[\d]|[\d]+"


def _normalize_spaces(text: str) -> str:
    return text.replace("\xa0", " ").replace("&nbsp;", " ")


def _parse_number(num_str: str) -> float:
    cleaned = re.sub(r"[\s,]", "", num_str)
    return float(cleaned)


def _find_amount(text: str) -> float | None:
    """Перша значима сума (UAH) у тексті статті → float або None."""
    priority_patterns = [
        rf"(?:склала|зібрали|зібрав|зібрано(?:\s+вже)?|collected|raised)\s+({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH)",
        rf"сума\s+(?:\w+\s+)?(?:склала|становила|зборів)\s+({_NUM_PAT})\s*(?:грн|гривень|гривні|UAH)",
    ]
    for pattern in priority_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    return val
            except (ValueError, IndexError):
                continue

    # Fallback: "X грн" (виключаємо ціль/мета перед числом)
    for m in re.finditer(rf"({_NUM_PAT})\s*(?:грн|гривень|гривні)", text, re.IGNORECASE):
        prefix = text[max(0, m.start() - 30): m.start()].lower()
        if any(w in prefix for w in ("ціль", "мета", "goal", "target")):
            continue
        try:
            val = _parse_number(m.group(1))
            if val > 0:
                return val
        except ValueError:
            continue

    return None


# --- Публічний API ---

def parse_article(url: str, html: str) -> dict[str, Any]:
    """Парсить HTML новинної статті → dict."""
    html_norm = _normalize_spaces(html)
    parser = _MetaParser()
    parser.feed(html_norm)

    amount_uah = _find_amount(parser.text)

    return {
        "url": url,
        "title": parser.title,
        "published": parser.published,
        "amount_uah": amount_uah,
        "raw_text": parser.text,
    }


def fetch_article(url: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Завантажує статтю та парсить. _client інжектиться в тестах."""
    if _client is None:
        import httpx
        _client = httpx.Client(follow_redirects=True, timeout=20)
    resp = _client.get(url, timeout=20)
    resp.raise_for_status()
    return parse_article(url, resp.text)
