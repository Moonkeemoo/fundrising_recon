"""Unit 1: capture links inside Telegram message text blocks.

parse_tme_html повертає нове поле `links: list[str]` у кожному пості —
дедупліковані href з тегів <a> всередині tgme_widget_message_text.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures (inline HTML — щоб не чіпати tme_channel.html fixture)
# ---------------------------------------------------------------------------

_HTML_WITH_JAR_LINK = """
<html><body>
<div class="tgme_widget_message" data-post="zbir/1">
  <div class="tgme_widget_message_text">
    Підтримайте збір!
    <a href="https://send.monobank.ua/jar/ABC123">Банка на дрон</a>
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/zbir/1">
    <time datetime="2024-01-01T00:00:00+00:00">1 Jan</time>
  </a>
</div>
</body></html>
"""

_HTML_MULTIPLE_LINKS = """
<html><body>
<div class="tgme_widget_message" data-post="zbir/2">
  <div class="tgme_widget_message_text">
    Посилання:
    <a href="https://send.monobank.ua/jar/XYZ">Банка 1</a>
    і
    <a href="https://t.me/some_channel">Канал</a>
    і ще раз
    <a href="https://send.monobank.ua/jar/XYZ">дублікат</a>
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/zbir/2">
    <time datetime="2024-01-02T00:00:00+00:00">2 Jan</time>
  </a>
</div>
</body></html>
"""

_HTML_NO_LINKS_IN_TEXT = """
<html><body>
<div class="tgme_widget_message" data-post="zbir/3">
  <div class="tgme_widget_message_text">
    Просто текст без посилань.
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/zbir/3">
    <time datetime="2024-01-03T00:00:00+00:00">3 Jan</time>
  </a>
</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Тести
# ---------------------------------------------------------------------------


def test_links_field_present_in_every_post():
    """Кожен пост містить ключ 'links'."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_NO_LINKS_IN_TEXT)
    assert len(posts) == 1
    assert "links" in posts[0]


def test_links_empty_when_no_hrefs_in_text():
    """Пост без посилань у тексті → links=[]."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_NO_LINKS_IN_TEXT)
    assert posts[0]["links"] == []


def test_links_captures_monobank_jar_href():
    """<a href='https://send.monobank.ua/jar/ABC123'> → у links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_WITH_JAR_LINK)
    assert len(posts) == 1
    assert "https://send.monobank.ua/jar/ABC123" in posts[0]["links"]


def test_links_dedup():
    """Однаковий href зустрічається двічі → в links лише раз."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_MULTIPLE_LINKS)
    links = posts[0]["links"]
    assert links.count("https://send.monobank.ua/jar/XYZ") == 1


def test_links_includes_telegram_links():
    """t.me/... посилання у тексті → у links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_MULTIPLE_LINKS)
    assert "https://t.me/some_channel" in posts[0]["links"]


def test_links_message_date_href_not_captured():
    """href з tgme_widget_message_date (поза текстом) НЕ попадає у links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_WITH_JAR_LINK)
    # Date href "https://t.me/zbir/1" не повинен потрапляти у links
    assert "https://t.me/zbir/1" not in posts[0]["links"]


def test_links_existing_fields_unchanged():
    """Додавання links не змінює існуючі поля source_url, text, views, date."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_WITH_JAR_LINK)
    post = posts[0]
    assert post["source_url"] == "https://t.me/zbir/1"
    assert post["platform"] == "telegram"
    assert post["channel"] == "zbir"
    assert post["text"] is not None
    assert "Підтримайте" in post["text"]


def test_links_order_preserved():
    """Порядок href відповідає порядку появи в HTML."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("zbir", _HTML_MULTIPLE_LINKS)
    links = posts[0]["links"]
    # XYZ перший, some_channel другий (дублікат XYZ не рахується)
    assert links[0] == "https://send.monobank.ua/jar/XYZ"
    assert links[1] == "https://t.me/some_channel"
