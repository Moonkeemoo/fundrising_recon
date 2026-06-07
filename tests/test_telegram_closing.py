"""Unit 3 — closing/milestone keywords у Telegram-фільтрі.

Тести підтверджують, що _CLOSING_KEYWORDS додані і пости з closing-
словами проходять фільтр search_channels навіть без fundraising-слів.
"""
from __future__ import annotations


def test_closing_keywords_defined():
    from fundrec.collect.telegram_web import _CLOSING_KEYWORDS
    assert isinstance(_CLOSING_KEYWORDS, list)
    assert len(_CLOSING_KEYWORDS) >= 5


def test_closing_post_passes_filter():
    """Пост ЛИШЕ з closing-словами (без збір/банка) проходить фільтр."""
    from fundrec.collect.telegram_web import _text_matches_fundraising

    closing_text = "Збір завершено, зібрали 2 млн, дякуємо!"
    assert _text_matches_fundraising(closing_text) is True


def test_closing_post_passes_search_channels(monkeypatch):
    """search_channels повертає closing-пост навіть без fundraising-слів."""
    from fundrec.collect import telegram_web

    closing_post = {
        "source_url": "https://t.me/ch/101",
        "platform": "telegram",
        "channel": "ch",
        "text": "Збір завершено, зібрали 2 млн, дякуємо!",
        "views": 5000,
        "date": "2024-03-15",
        "message_id": 101,
    }

    def fake_fetch(channel, pages=1, _client=None):
        return [closing_post]

    monkeypatch.setattr(telegram_web, "fetch_channel_web", fake_fetch)

    results = telegram_web.search_channels(
        "FPV дрони",
        channels=["ch"],
        max_results=10,
        keyword_filter=True,
    )
    assert len(results) == 1
    assert results[0]["text"] == closing_post["text"]


def test_non_fundraising_non_closing_post_filtered_out(monkeypatch):
    """Пост без fundraising І без closing-слів — не пропускається."""
    from fundrec.collect import telegram_web

    random_post = {
        "source_url": "https://t.me/ch/102",
        "platform": "telegram",
        "channel": "ch",
        "text": "Сьогодні сонячна погода у Kyiv",
        "views": 3000,
        "date": "2024-03-16",
        "message_id": 102,
    }

    def fake_fetch(channel, pages=1, _client=None):
        return [random_post]

    monkeypatch.setattr(telegram_web, "fetch_channel_web", fake_fetch)

    results = telegram_web.search_channels(
        "FPV дрони",
        channels=["ch"],
        max_results=10,
        keyword_filter=True,
    )
    assert results == []


def test_fundraising_post_still_passes(monkeypatch):
    """Класичний fundraising-пост (збір/банка) все ще проходить фільтр."""
    from fundrec.collect import telegram_web

    fundraising_post = {
        "source_url": "https://t.me/ch/103",
        "platform": "telegram",
        "channel": "ch",
        "text": "Запускаємо збір на FPV дрони! Монобанк jar 5375411200012345",
        "views": 8000,
        "date": "2024-03-17",
        "message_id": 103,
    }

    def fake_fetch(channel, pages=1, _client=None):
        return [fundraising_post]

    monkeypatch.setattr(telegram_web, "fetch_channel_web", fake_fetch)

    results = telegram_web.search_channels(
        "FPV",
        channels=["ch"],
        max_results=10,
        keyword_filter=True,
    )
    assert len(results) == 1


def test_100_percent_closing_passes():
    """'100%' як закриваючий сигнал проходить фільтр."""
    from fundrec.collect.telegram_web import _text_matches_fundraising

    assert _text_matches_fundraising("Зібрано 100%! Дякуємо всім донорам") is True


def test_meta_dosyagnuta_passes():
    """'мету досягнут' проходить фільтр."""
    from fundrec.collect.telegram_web import _text_matches_fundraising

    assert _text_matches_fundraising("Мету досягнуто! Техніка вже в дорозі") is True
