"""Колектор публічних Telegram-каналів через t.me/s/<channel> (без логіну).

parse_tme_html(channel, html) -> list[dict] — чиста функція, тестується на фікстурі.
fetch_channel_web(channel, *, _client) -> list[dict] — GET t.me/s/<channel>.
search_channels(theme, *, channels, max_results, _client, keyword_filter) -> list[dict]
  — перебирає SEED_CHANNELS, фільтрує за ключовими словами, повертає flat-список.

Не потребує TELEGRAM_API_ID / TELEGRAM_API_HASH — читає лише публічні сторінки HTTPS.
PII-інваріант #6: лише публічні канали.
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from typing import Any

# ---------------------------------------------------------------------------
# Публічні seed-канали українських збірників (usernames Telegram)
# Редагуйте вільно — це лише стартовий список; помилки скіпаються graceful.
# ---------------------------------------------------------------------------
SEED_CHANNELS: list[str] = [
    "prytulafoundation",   # Фонд Притули
    "u24_gov_ua",          # UNITED24
    "backandalive",        # Повернись живим (Come Back Alive)
    "ssternenko",          # Сергій Стерненко
    "kpszsu",              # Сили підтримки / збори
    "signal_dnipro",       # волонтерський збір
    "dignitas_fund",       # фонд Dignitas
    "operativnoZSU",       # оперативні збори ЗСУ
    "butusovplus",         # Бутусов Плюс (збори)
    "zsu_donate",          # донати ЗСУ
    "lachenpyshe",         # волонтер
]
# Перевірено живими (t.me/s) 2026-06-07. Список публічний і редагований.

# Ключові слова, що сигналізують про збір коштів
_FUNDRAISING_KEYWORDS = [
    "збір", "банка", "реквізити", "монобанк", "донат",
    "на дрон", "jar", "mono.bank", "send.monobank", "monobank",
    "зібрано", "ціль", "задонатити",
]

_POST_URL_TMPL = "https://t.me/{channel}/{message_id}"


# ---------------------------------------------------------------------------
# HTML-парсер для t.me/s/<channel>
# ---------------------------------------------------------------------------

class _TmeParser(HTMLParser):
    """Парсить HTML t.me/s/<channel> → список повідомлень.

    Кожне повідомлення — div.tgme_widget_message з атрибутом data-post.
    Стратегія: відстежуємо глибину div-стеку; коли завершується div на тій
    же глибині, на якій було відкрито tgme_widget_message — зберігаємо пост.
    """

    def __init__(self, channel: str) -> None:
        super().__init__()
        self._channel = channel
        self.posts: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._msg_depth: int = 0      # глибина div на якій відкрито поточний пост
        self._div_depth: int = 0      # поточна глибина div-стека
        self._in_text: bool = False
        self._text_depth: int = 0     # глибина div коли ввійшли в text
        self._in_views: bool = False
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()

        if tag == "div":
            self._div_depth += 1

            if "tgme_widget_message" in classes and "tgme_widget_message_text" not in classes:
                # Новий пост — зберігаємо попередній якщо є
                if self._current is not None:
                    self._save_current()

                data_post = attrs_dict.get("data-post", "")
                message_id: int | None = None
                if data_post and "/" in data_post:
                    try:
                        message_id = int(data_post.rsplit("/", 1)[-1])
                    except ValueError:
                        pass
                self._current = {
                    "channel": self._channel,
                    "message_id": message_id,
                    "text": None,
                    "views": None,
                    "date": None,
                    "source_url": None,
                }
                self._msg_depth = self._div_depth
                self._text_parts = []

            elif "tgme_widget_message_text" in classes and self._current is not None:
                self._in_text = True
                self._text_depth = self._div_depth

        if self._current is None:
            return

        if self._in_text and tag in ("br", "p"):
            self._text_parts.append(" ")

        elif tag == "span" and "tgme_widget_message_views" in classes:
            self._in_views = True

        elif tag == "a" and "tgme_widget_message_date" in classes:
            href = attrs_dict.get("href")
            if href:
                self._current["source_url"] = href

        elif tag == "time":
            dt = attrs_dict.get("datetime")
            if dt and self._current["date"] is None:
                self._current["date"] = dt

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._in_text and self._div_depth <= self._text_depth:
                # Закрито div тексту
                self._in_text = False
                if self._current is not None and self._current["text"] is None:
                    self._current["text"] = " ".join(
                        p.strip() for p in self._text_parts if p.strip()
                    )

            if self._current is not None and self._div_depth <= self._msg_depth:
                # Закрито div поточного поста
                self._save_current()

            self._div_depth -= 1

        elif tag == "span" and self._in_views:
            self._in_views = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._in_text:
            self._text_parts.append(data)
        elif self._in_views:
            self._current["views"] = _parse_views(data.strip())

    def _save_current(self) -> None:
        """Фіналізує та зберігає поточний пост."""
        if self._current is None:
            return
        if self._current["text"] is None and self._text_parts:
            self._current["text"] = " ".join(
                p.strip() for p in self._text_parts if p.strip()
            )
        if self._current["source_url"] is None and self._current["message_id"] is not None:
            self._current["source_url"] = _POST_URL_TMPL.format(
                channel=self._channel, message_id=self._current["message_id"]
            )
        self.posts.append(self._current)
        self._current = None
        self._in_text = False
        self._in_views = False
        self._text_parts = []

    def close(self) -> None:
        if self._current is not None:
            self._save_current()
        super().close()


def _parse_views(raw: str) -> int | None:
    """Перетворює рядок перегляду ('12.3K', '1.2M', '500') на int або None."""
    if not raw:
        return None
    raw = raw.strip().replace(",", ".").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMm]?)$", raw)
    if not m:
        return None
    number, suffix = m.group(1), m.group(2).upper()
    try:
        val = float(number)
    except ValueError:
        return None
    if suffix == "K":
        return int(val * 1_000)
    if suffix == "M":
        return int(val * 1_000_000)
    return int(val)


# ---------------------------------------------------------------------------
# Публічний API
# ---------------------------------------------------------------------------

def parse_tme_html(channel: str, html: str) -> list[dict[str, Any]]:
    """Парсить HTML t.me/s/<channel> → list[dict] нормалізованих постів.

    Кожен dict містить:
      source_url, platform, channel, text, views, date, message_id.
    Honest null: views=None, date=None, text=None якщо відсутні.
    """
    parser = _TmeParser(channel)
    parser.feed(html)
    parser.close()

    results: list[dict[str, Any]] = []
    for post in parser.posts:
        source_url = post.get("source_url")
        message_id = post.get("message_id")
        # Fallback: будуємо URL з message_id якщо href не знайдено
        if not source_url and message_id is not None:
            source_url = _POST_URL_TMPL.format(channel=channel, message_id=message_id)
        results.append({
            "source_url": source_url,
            "platform": "telegram",
            "channel": channel,
            "text": post.get("text"),
            "views": post.get("views"),
            "date": post.get("date"),
            "message_id": message_id,
        })
    return results


def fetch_channel_web(
    channel: str,
    *,
    _client: Any | None = None,
) -> list[dict[str, Any]]:
    """Завантажує публічний канал через https://t.me/s/<channel> (без логіну).

    _client інжектиться в тестах.
    Live _client=None шлях: # pragma: no cover.
    """
    if _client is None:  # pragma: no cover
        import httpx  # noqa: PLC0415  # pragma: no cover
        _client = httpx.Client(timeout=20, follow_redirects=True)  # pragma: no cover
    url = f"https://t.me/s/{channel}"
    resp = _client.get(url, timeout=20)
    resp.raise_for_status()
    return parse_tme_html(channel, resp.text)


def _text_matches_fundraising(text: str | None) -> bool:
    """Перевіряє, чи містить текст сигнальні слова збору коштів."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in _FUNDRAISING_KEYWORDS)


def search_channels(
    theme: str,
    *,
    channels: list[str] | None = None,
    max_results: int = 25,
    _client: Any | None = None,
    keyword_filter: bool = True,
) -> list[dict[str, Any]]:
    """Шукає пости про збори в публічних Telegram-каналах без логіну.

    Перебирає channels (або SEED_CHANNELS), завантажує кожен через
    fetch_channel_web, за keyword_filter=True залишає лише пости зі словами
    збору АБО зі словами теми. Повертає flat-список до max_results постів.

    Помилки мережі для окремих каналів — graceful-skip (continue).
    """
    seed = channels if channels is not None else SEED_CHANNELS
    theme_words = [w.lower() for w in theme.split() if len(w) > 2]

    collected: list[dict[str, Any]] = []

    for ch in seed:
        if len(collected) >= max_results:
            break
        try:
            posts = fetch_channel_web(ch, _client=_client)
        except Exception as exc:  # noqa: BLE001
            print(f"telegram_web: канал '{ch}' — помилка: {exc}", file=sys.stderr)
            continue

        for post in posts:
            if len(collected) >= max_results:
                break
            if keyword_filter:
                text = post.get("text") or ""
                text_lower = text.lower()
                has_fundraising = _text_matches_fundraising(text)
                has_theme = any(w in text_lower for w in theme_words)
                if not has_fundraising and not has_theme:
                    continue
            collected.append(post)

    return collected
