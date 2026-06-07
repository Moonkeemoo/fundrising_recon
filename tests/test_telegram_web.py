"""Тести колектора Telegram Web (t.me/s/<channel>) — без логіну."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TME_FIXTURE_HTML = (FIXTURES / "tme_channel.html").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# parse_tme_html — чиста функція
# ---------------------------------------------------------------------------


def test_parse_tme_html_returns_list():
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert isinstance(results, list)


def test_parse_tme_html_correct_count():
    """Фікстура містить 3 пости."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert len(results) == 3


def test_parse_tme_html_post1_fields():
    """Перший пост: source_url, platform, channel, text, views, date."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    post = results[0]
    assert post["platform"] == "telegram"
    assert post["channel"] == "prytulafoundation"
    assert post["message_id"] == 101
    assert post["source_url"] == "https://t.me/prytulafoundation/101"


def test_parse_tme_html_post1_text_contains_fundraising():
    """Перший пост містить ключові слова збору."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    post = results[0]
    assert post["text"] is not None
    assert "дрон" in post["text"].lower() or "збір" in post["text"].lower()


def test_parse_tme_html_post1_views_int():
    """12.3K → 12300."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert results[0]["views"] == 12300


def test_parse_tme_html_post1_date():
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert results[0]["date"] == "2024-03-15T10:30:00+00:00"


def test_parse_tme_html_post2_views_int():
    """4.5K → 4500."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert results[1]["views"] == 4500


def test_parse_tme_html_post3_no_views_is_none():
    """Третій пост без тегу views → None (honest null)."""
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    assert results[2]["views"] is None


def test_parse_tme_html_all_required_keys():
    from fundrec.collect.telegram_web import parse_tme_html

    required = ("source_url", "platform", "channel", "text", "views", "date", "message_id")
    results = parse_tme_html("prytulafoundation", TME_FIXTURE_HTML)
    for post in results:
        for key in required:
            assert key in post, f"Відсутній ключ {key!r} у {post}"


def test_parse_tme_html_empty_html_returns_empty():
    from fundrec.collect.telegram_web import parse_tme_html

    results = parse_tme_html("anychannel", "<html><body></body></html>")
    assert results == []


# ---------------------------------------------------------------------------
# _parse_views — одиничні тести
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("12.3K", 12300),
    ("12.3k", 12300),
    ("1.2M", 1_200_000),
    ("1.2m", 1_200_000),
    ("500", 500),
    ("1000", 1000),
    ("", None),
    ("N/A", None),
])
def test_parse_views_variants(raw, expected):
    from fundrec.collect.telegram_web import _parse_views

    assert _parse_views(raw) == expected


# ---------------------------------------------------------------------------
# fetch_channel_web — injected client
# ---------------------------------------------------------------------------


class _FakeHttpxClient:
    """Симулює httpx.Client.get() — повертає фіксований HTML."""

    def __init__(self, html: str, status_code: int = 200):
        self._html = html
        self._status_code = status_code
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int = 20):
        self.calls.append(url)
        return _FakeResp(self._html, self._status_code)


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_channel_web_calls_correct_url():
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _FakeHttpxClient(TME_FIXTURE_HTML)
    fetch_channel_web("prytulafoundation", _client=client)
    assert client.calls[0] == "https://t.me/s/prytulafoundation"


def test_fetch_channel_web_returns_parsed_posts():
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _FakeHttpxClient(TME_FIXTURE_HTML)
    results = fetch_channel_web("prytulafoundation", _client=client)
    assert len(results) == 3
    assert results[0]["platform"] == "telegram"


def test_fetch_channel_web_http_error_propagates():
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _FakeHttpxClient("", status_code=404)
    with pytest.raises(RuntimeError):
        fetch_channel_web("missing_channel", _client=client)


# ---------------------------------------------------------------------------
# search_channels — injected client для 2 каналів
# ---------------------------------------------------------------------------


_CHANNEL2_HTML = """
<html><body>
<div class="tgme_widget_message" data-post="back_and_alive/201">
  <div class="tgme_widget_message_text">Банка на броньовик: mono.bank/send/xyz</div>
  <span class="tgme_widget_message_views">3.1K</span>
  <a class="tgme_widget_message_date" href="https://t.me/back_and_alive/201">
    <time datetime="2024-03-10T09:00:00+00:00">10 Mar</time>
  </a>
</div>
<div class="tgme_widget_message" data-post="back_and_alive/202">
  <div class="tgme_widget_message_text">Загальні новини про роботу фонду</div>
  <a class="tgme_widget_message_date" href="https://t.me/back_and_alive/202">
    <time datetime="2024-03-09T07:00:00+00:00">9 Mar</time>
  </a>
</div>
</body></html>
"""


class _MultiChannelClient:
    """Повертає різний HTML залежно від каналу в URL."""

    def __init__(self, html_map: dict[str, str]):
        self._html_map = html_map
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int = 20):
        self.calls.append(url)
        for channel, html in self._html_map.items():
            if channel in url:
                return _FakeResp(html)
        return _FakeResp("<html></html>")


def test_search_channels_returns_flat_list():
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({
        "prytulafoundation": TME_FIXTURE_HTML,
        "back_and_alive": _CHANNEL2_HTML,
    })
    results = search_channels(
        "дрони",
        channels=["prytulafoundation", "back_and_alive"],
        _client=client,
    )
    assert isinstance(results, list)
    # Після фільтрації: pry має 2 fundraising пости (101+103), back_and_alive має 1 (201)
    assert len(results) >= 1


def test_search_channels_keyword_filter_removes_non_fundraising():
    """Пост без ключових слів і без теми не потрапляє у результат."""
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({
        "prytulafoundation": TME_FIXTURE_HTML,
    })
    results = search_channels(
        "дрони",
        channels=["prytulafoundation"],
        _client=client,
        keyword_filter=True,
    )
    # Другий пост ("Звіт про роботу фонду") не має ключових слів збору і не містить "дрони"
    # Але перший і третій містять
    texts = [r["text"] or "" for r in results]
    # Звіт НЕ повинен потрапити
    assert not any("Звіт про роботу" in t for t in texts)


def test_search_channels_no_filter_returns_all():
    """keyword_filter=False → всі пости."""
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({
        "prytulafoundation": TME_FIXTURE_HTML,
    })
    results = search_channels(
        "дрони",
        channels=["prytulafoundation"],
        _client=client,
        keyword_filter=False,
    )
    assert len(results) == 3


def test_search_channels_max_results_cap():
    """max_results обрізає вивід."""
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({
        "prytulafoundation": TME_FIXTURE_HTML,
        "back_and_alive": _CHANNEL2_HTML,
    })
    results = search_channels(
        "дрони",
        channels=["prytulafoundation", "back_and_alive"],
        max_results=2,
        _client=client,
        keyword_filter=False,
    )
    assert len(results) <= 2


def test_search_channels_graceful_skip_on_error(capsys):
    """Помилка у одному каналі не зупиняє обробку решти."""
    from fundrec.collect.telegram_web import search_channels

    class _PartialFailClient:
        def get(self, url: str, *, timeout: int = 20):
            if "bad_channel" in url:
                raise ConnectionError("network down")
            return _FakeResp(TME_FIXTURE_HTML)

    results = search_channels(
        "дрони",
        channels=["bad_channel", "prytulafoundation"],
        _client=_PartialFailClient(),
        keyword_filter=False,
    )
    # prytulafoundation має 3 пости
    assert len(results) == 3
    captured = capsys.readouterr()
    assert "bad_channel" in captured.err


def test_search_channels_all_posts_have_source_url():
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({"prytulafoundation": TME_FIXTURE_HTML})
    results = search_channels(
        "дрони",
        channels=["prytulafoundation"],
        _client=client,
        keyword_filter=False,
    )
    for post in results:
        assert post["source_url"] is not None
        assert post["source_url"].startswith("https://t.me/")


def test_search_channels_platform_is_telegram():
    from fundrec.collect.telegram_web import search_channels

    client = _MultiChannelClient({"prytulafoundation": TME_FIXTURE_HTML})
    results = search_channels(
        "збір",
        channels=["prytulafoundation"],
        _client=client,
        keyword_filter=False,
    )
    for post in results:
        assert post["platform"] == "telegram"


def test_search_channels_uses_seed_channels_by_default():
    """Без параметра channels використовує SEED_CHANNELS."""
    from fundrec.collect import telegram_web

    called = []

    class _RecordingClient:
        def get(self, url: str, *, timeout: int = 20):
            called.append(url)
            return _FakeResp("<html></html>")

    telegram_web.search_channels("test", _client=_RecordingClient(), keyword_filter=False)
    assert len(called) == len(telegram_web.SEED_CHANNELS)


# ---------------------------------------------------------------------------
# Unit 1 — пагінація fetch_channel_web(pages=N)
# ---------------------------------------------------------------------------

# Сторінка 1: пости з id 100–110 (11 постів)
_PAGE1_HTML = "".join([
    f"""<div class="tgme_widget_message" data-post="testchan/{i}">
      <div class="tgme_widget_message_text">Збір на дрони {i}</div>
      <a class="tgme_widget_message_date" href="https://t.me/testchan/{i}">
        <time datetime="2024-01-01T00:00:00+00:00">1 Jan</time>
      </a>
    </div>"""
    for i in range(100, 111)  # ids 100..110
])
_PAGE1_HTML = f"<html><body>{_PAGE1_HTML}</body></html>"

# Сторінка 2: пости з id 88–99 (12 постів), з'являється після ?before=100
_PAGE2_HTML = "".join([
    f"""<div class="tgme_widget_message" data-post="testchan/{i}">
      <div class="tgme_widget_message_text">Збір на дрони {i}</div>
      <a class="tgme_widget_message_date" href="https://t.me/testchan/{i}">
        <time datetime="2024-01-01T00:00:00+00:00">1 Jan</time>
      </a>
    </div>"""
    for i in range(88, 100)  # ids 88..99
])
_PAGE2_HTML = f"<html><body>{_PAGE2_HTML}</body></html>"


class _PaginatingClient:
    """Повертає page1 або page2 залежно від наявності before= у URL."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int = 20):
        self.calls.append(url)
        if "before=" in url:
            return _FakeResp(_PAGE2_HTML)
        return _FakeResp(_PAGE1_HTML)


def test_fetch_channel_web_pages1_returns_first_page_only():
    """pages=1 (за замовчуванням) — лише перша сторінка."""
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _PaginatingClient()
    results = fetch_channel_web("testchan", pages=1, _client=client)
    assert len(results) == 11  # 100..110
    assert len(client.calls) == 1
    # Немає before= у URL
    assert "before=" not in client.calls[0]


def test_fetch_channel_web_pages2_merges_two_pages():
    """pages=2 → 11+12=23 унікальних постів злито разом."""
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _PaginatingClient()
    results = fetch_channel_web("testchan", pages=2, _client=client)
    assert len(results) == 23  # 11 + 12
    ids = [p["message_id"] for p in results]
    assert len(set(ids)) == 23  # всі унікальні


def test_fetch_channel_web_pages2_cursor_uses_min_id():
    """Курсор before= = мін message_id першої сторінки (100)."""
    from fundrec.collect.telegram_web import fetch_channel_web

    client = _PaginatingClient()
    fetch_channel_web("testchan", pages=2, _client=client)
    assert len(client.calls) == 2
    # Другий запит має before=100 (мін id зі сторінки 1)
    assert "before=100" in client.calls[1]


def test_fetch_channel_web_stops_early_on_empty_page():
    """Якщо сторінка не повертає нових постів — зупиняємось достроково."""
    from fundrec.collect.telegram_web import fetch_channel_web

    # Клієнт, де друга сторінка порожня
    class _EmptyPage2Client:
        def __init__(self):
            self.calls: list[str] = []

        def get(self, url: str, *, timeout: int = 20):
            self.calls.append(url)
            if "before=" in url:
                return _FakeResp("<html><body></body></html>")
            return _FakeResp(_PAGE1_HTML)

    client = _EmptyPage2Client()
    results = fetch_channel_web("testchan", pages=5, _client=client)
    # Зупиняємось після 2 запитів (1 реальний + 1 порожній)
    assert len(client.calls) == 2
    assert len(results) == 11


def test_fetch_channel_web_dedup_overlapping_pages():
    """Якщо дві сторінки мають спільні message_id — дедуп (кожен id один раз)."""
    from fundrec.collect.telegram_web import fetch_channel_web

    # Обидві сторінки повертають ОДНАКОВИЙ HTML
    class _SamePageClient:
        def get(self, url: str, *, timeout: int = 20):
            return _FakeResp(_PAGE1_HTML)

    results = fetch_channel_web("testchan", pages=2, _client=_SamePageClient())
    ids = [p["message_id"] for p in results]
    assert len(set(ids)) == len(ids)  # немає дублів


def test_search_channels_passes_pages_to_fetch():
    """search_channels(pages=2) передає pages у fetch_channel_web."""
    from fundrec.collect.telegram_web import search_channels

    client = _PaginatingClient()
    results = search_channels(
        "дрони",
        channels=["testchan"],
        pages=2,
        _client=client,
        keyword_filter=False,
    )
    # Має бути 2 виклики: сторінка 1 і сторінка 2
    assert len(client.calls) == 2
    assert len(results) == 23
