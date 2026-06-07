"""Тести для fundrec.collect.news — fetch_article / parse_article."""
from __future__ import annotations

from pathlib import Path

from fundrec.collect.news import fetch_article, parse_article

FIXTURE = Path(__file__).parent / "fixtures" / "news_sample.html"
URL = "https://forbes.ua/news/fond-povernys-zhyvym-zibrav-200-mln"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, html: str, status_code: int = 200):
        self._html = html
        self._status_code = status_code

    def get(self, url: str, **kwargs):
        return _FakeResp(self._html, self._status_code)


# --- parse_article тести ---

def test_parse_url_preserved():
    result = parse_article(URL, _html())
    assert result["url"] == URL


def test_parse_title():
    result = parse_article(URL, _html())
    assert "Повернись живим" in result["title"] or "Forbes" in result["title"]


def test_parse_published_from_time_tag():
    """<time datetime=...> → поле published."""
    result = parse_article(URL, _html())
    assert result["published"] == "2024-03-15T10:30:00+02:00"


def test_parse_published_from_meta():
    """article:published_time meta → поле published."""
    html = (
        '<html><head><title>T</title>'
        '<meta name="article:published_time" content="2023-10-01T08:00:00Z">'
        '</head><body><p>Text without time tag.</p></body></html>'
    )
    result = parse_article(URL, html)
    assert result["published"] == "2023-10-01T08:00:00Z"


def test_parse_published_none_when_absent():
    html = "<html><head><title>T</title></head><body><p>No date here.</p></body></html>"
    result = parse_article(URL, html)
    assert result["published"] is None


def test_parse_amount_uah():
    """200 000 000 грн екстрагується як amount_uah."""
    result = parse_article(URL, _html())
    assert result["amount_uah"] == 200_000_000.0


def test_parse_raw_text_not_empty():
    result = parse_article(URL, _html())
    assert len(result["raw_text"]) > 20


def test_parse_no_amounts_returns_none():
    html = "<html><head><title>T</title></head><body><p>Без сум.</p></body></html>"
    result = parse_article(URL, html)
    assert result["amount_uah"] is None


def test_parse_result_keys():
    """Результат містить усі обов'язкові ключі."""
    result = parse_article(URL, _html())
    for key in ("url", "title", "published", "amount_uah", "raw_text"):
        assert key in result


# --- fetch_article тест ---

def test_fetch_article_uses_client():
    client = _FakeClient(_html())
    result = fetch_article(URL, _client=client)
    assert result["url"] == URL
    assert result["amount_uah"] == 200_000_000.0
