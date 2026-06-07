"""Тести для fundrec.collect.reports — fetch_report / parse_report."""
from __future__ import annotations

from pathlib import Path

from fundrec.collect.reports import fetch_report, parse_report

FIXTURE = Path(__file__).parent / "fixtures" / "report_sample.html"


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


URL = "https://savelife.in.ua/donate"


# --- parse_report тести (детерміністичні) ---

def test_parse_title_from_title_tag():
    result = parse_report(URL, _html())
    assert result["title"] == "Збір на FPV-дрони — Come Back Alive"


def test_parse_url_preserved():
    result = parse_report(URL, _html())
    assert result["url"] == URL


def test_parse_amount_uah_грн():
    """Зибирає першу суму в грн (12 500 000)."""
    result = parse_report(URL, _html())
    # 12 500 000 грн (перша з "зібрано")
    assert result["amount_uah"] == 12_500_000.0


def test_parse_goal_amount():
    """Ціль: 50 000 000 грн."""
    result = parse_report(URL, _html())
    assert result["goal_amount"] == 50_000_000.0


def test_parse_currency_raw():
    result = parse_report(URL, _html())
    assert result["currency_raw"] in ("грн", "UAH", "₴")


def test_parse_raw_text_not_empty():
    result = parse_report(URL, _html())
    assert len(result["raw_text"]) > 10


def test_parse_nbsp_thousands_separator():
    """Числа з &nbsp; / \xa0 між тисячами парсяться коректно."""
    html = "<html><head><title>T</title></head><body><p>Зібрано 12\xa0500\xa0000 грн. Ціль: 50\xa0000\xa0000 грн</p></body></html>"
    result = parse_report(URL, html)
    assert result["amount_uah"] == 12_500_000.0
    assert result["goal_amount"] == 50_000_000.0


def test_parse_hryvnia_sign():
    """₴ розпізнається як гривня."""
    html = "<html><head><title>T</title></head><body><p>₴3 200 000 зібрано</p></body></html>"
    result = parse_report(URL, html)
    assert result["amount_uah"] == 3_200_000.0


def test_parse_usd_amount():
    """$ долар розпізнається."""
    html = "<html><head><title>T</title></head><body><p>Зібрано $150 000 від діаспори</p></body></html>"
    result = parse_report(URL, html)
    assert result["amount_uah"] == 150_000.0  # зберігаємо як є (без конверсії)


def test_parse_no_amounts_returns_none():
    """Сторінка без сум → None, не 0."""
    html = "<html><head><title>T</title></head><body><p>Без грошей.</p></body></html>"
    result = parse_report(URL, html)
    assert result["amount_uah"] is None
    assert result["goal_amount"] is None


# --- fetch_report тест ---

def test_fetch_report_uses_client():
    client = _FakeClient(_html())
    result = fetch_report(URL, _client=client)
    assert result["url"] == URL
    assert result["title"] == "Збір на FPV-дрони — Come Back Alive"
