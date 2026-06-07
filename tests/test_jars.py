"""Тести fundrec.jars — витяг jar-ids, парсинг jar-сторінки, fetch_jar_data."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
JAR_PAGE_HTML = (FIXTURES / "monobank_jar_page.html").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# extract_jar_ids — чиста функція
# ---------------------------------------------------------------------------


def test_extract_jar_ids_single():
    from fundrec.jars import extract_jar_ids

    text = "Донатьте на банку: send.monobank.ua/jar/ABC123xyz"
    result = extract_jar_ids(text)
    assert result == ["ABC123xyz"]


def test_extract_jar_ids_multiple():
    from fundrec.jars import extract_jar_ids

    text = "Банка 1: send.monobank.ua/jar/AAA111 та банка 2: send.monobank.ua/jar/BBB222"
    result = extract_jar_ids(text)
    assert "AAA111" in result
    assert "BBB222" in result
    assert len(result) == 2


def test_extract_jar_ids_dedup():
    """Один і той самий jar_id зустрічається двічі — повертається раз."""
    from fundrec.jars import extract_jar_ids

    text = "send.monobank.ua/jar/DUP99 і знову send.monobank.ua/jar/DUP99"
    result = extract_jar_ids(text)
    assert result.count("DUP99") == 1


def test_extract_jar_ids_none():
    """Текст без посилань → порожній список."""
    from fundrec.jars import extract_jar_ids

    result = extract_jar_ids("Звіт про роботу фонду за лютий 2024")
    assert result == []


def test_extract_jar_ids_base_monobank():
    """Також розпізнає base.monobank.ua/... посилання."""
    from fundrec.jars import extract_jar_ids

    text = "Переходьте: base.monobank.ua/jar/XYZ789"
    result = extract_jar_ids(text)
    assert "XYZ789" in result


def test_extract_jar_ids_order_preserved():
    """Порядок унікальних id — порядок першої появи."""
    from fundrec.jars import extract_jar_ids

    text = "send.monobank.ua/jar/FIRST і send.monobank.ua/jar/SECOND"
    result = extract_jar_ids(text)
    assert result[0] == "FIRST"
    assert result[1] == "SECOND"


def test_extract_jar_ids_with_https():
    """Повний URL з https:// теж розпізнається."""
    from fundrec.jars import extract_jar_ids

    text = "https://send.monobank.ua/jar/HTTPS001"
    result = extract_jar_ids(text)
    assert "HTTPS001" in result


# ---------------------------------------------------------------------------
# parse_jar_page — парсинг HTML із вбудованим JSON (пріоритет) та fallback
# ---------------------------------------------------------------------------


def test_parse_jar_page_returns_jar_id():
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("ABC123xyz", JAR_PAGE_HTML)
    assert result["jar_id"] == "ABC123xyz"


def test_parse_jar_page_returns_url():
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("ABC123xyz", JAR_PAGE_HTML)
    assert result["url"] == "https://send.monobank.ua/jar/ABC123xyz"


def test_parse_jar_page_amount_from_json_copecks():
    """Вбудований JSON: amount=87650000 копійок → 876500.0 грн."""
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("ABC123xyz", JAR_PAGE_HTML)
    assert result["amount_uah"] == pytest.approx(876_500.0)


def test_parse_jar_page_goal_from_json_copecks():
    """Вбудований JSON: goal=200000000 копійок → 2000000.0 грн."""
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("ABC123xyz", JAR_PAGE_HTML)
    assert result["goal_amount"] == pytest.approx(2_000_000.0)


def test_parse_jar_page_title():
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("ABC123xyz", JAR_PAGE_HTML)
    assert result["title"] == "FPV дрони для 47-ї бригади"


def test_parse_jar_page_fallback_html_no_json():
    """Якщо JSON відсутній — парсимо через видимий HTML-текст."""
    from fundrec.jars import parse_jar_page

    html_no_json = """<!DOCTYPE html>
<html><head><title>Збір | Monobank</title></head>
<body>
  <h1>Збір на броньовик</h1>
  <p>Зібрано 12 500 грн</p>
  <p>Ціль: 100 000 грн</p>
</body></html>"""
    result = parse_jar_page("FALLBACK1", html_no_json)
    assert result["amount_uah"] == pytest.approx(12_500.0)
    assert result["goal_amount"] == pytest.approx(100_000.0)


def test_parse_jar_page_honest_null_if_missing():
    """Якщо amount/goal не знайдено → None (honest null)."""
    from fundrec.jars import parse_jar_page

    html_empty = (
        "<html><head><title>Банка | Monobank</title></head><body><p>Текст</p></body></html>"
    )
    result = parse_jar_page("EMPTY1", html_empty)
    assert result["amount_uah"] is None
    assert result["goal_amount"] is None


def test_parse_jar_page_returns_required_keys():
    from fundrec.jars import parse_jar_page

    result = parse_jar_page("TEST1", JAR_PAGE_HTML)
    for key in ("jar_id", "url", "title", "amount_uah", "goal_amount"):
        assert key in result, f"Відсутній ключ {key!r}"


# ---------------------------------------------------------------------------
# fetch_jar_data — injectable client
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, html: str, status_code: int = 200):
        self._html = html
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int = 20):
        self.calls.append(url)
        return _FakeResp(self._html)


def test_fetch_jar_data_calls_correct_url():
    from fundrec.jars import fetch_jar_data

    client = _FakeClient(JAR_PAGE_HTML)
    fetch_jar_data("ABC123xyz", _client=client)
    assert client.calls[0] == "https://send.monobank.ua/jar/ABC123xyz"


def test_fetch_jar_data_returns_parsed_dict():
    from fundrec.jars import fetch_jar_data

    client = _FakeClient(JAR_PAGE_HTML)
    result = fetch_jar_data("ABC123xyz", _client=client)
    assert result is not None
    assert result["amount_uah"] == pytest.approx(876_500.0)


def test_fetch_jar_data_returns_none_on_http_error():
    from fundrec.jars import fetch_jar_data

    class _ErrorClient:
        def get(self, url: str, *, timeout: int = 20):
            return _FakeResp("", 404)

    result = fetch_jar_data("NOTFOUND", _client=_ErrorClient())
    assert result is None


# ---------------------------------------------------------------------------
# parse_rendered_jar — парсинг тексту body після JS-рендеру
# ---------------------------------------------------------------------------

_RENDERED_BODY_FULL = """\
Постійна банка для закупівлі FPV. Наша мета — купувати мінімум 300 дронів
2 000 837.29 ₴
10 000 000 ₴
0
₴
Minimum amount: 10 ₴. Maximum amount: 29 999 ₴
+100 ₴
Monobank
"""

_RENDERED_BODY_NO_GOAL = """\
Збір на авто для бригади
125 000 ₴
"""

_RENDERED_BODY_GARBAGE = "404 not found"


def test_parse_rendered_jar_amounts_full():
    """Перший ₴-рядок = зібрано, другий = ціль."""
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("JAR001", _RENDERED_BODY_FULL)
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)


def test_parse_rendered_jar_title():
    """Title = перший не-порожній рядок, що не є сумою і не є boilerplate."""
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("JAR001", _RENDERED_BODY_FULL)
    assert result["title"] is not None
    assert result["title"].startswith("Постійна банка")


def test_parse_rendered_jar_url():
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("JAR001", _RENDERED_BODY_FULL)
    assert result["url"] == "https://send.monobank.ua/jar/JAR001"
    assert result["jar_id"] == "JAR001"


def test_parse_rendered_jar_no_goal():
    """Лише одна ₴-сума — goal = None."""
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("JAR002", _RENDERED_BODY_NO_GOAL)
    assert result["amount_uah"] == pytest.approx(125_000.0)
    assert result["goal_amount"] is None


def test_parse_rendered_jar_garbage_all_none():
    """Текст без сум — все None крім jar_id / url."""
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("JARGARBAGE", _RENDERED_BODY_GARBAGE)
    assert result["amount_uah"] is None
    assert result["goal_amount"] is None
    assert result["title"] is None


def test_parse_rendered_jar_returns_required_keys():
    from fundrec.jars import parse_rendered_jar

    result = parse_rendered_jar("TEST", _RENDERED_BODY_FULL)
    for key in ("jar_id", "url", "title", "amount_uah", "goal_amount"):
        assert key in result


def test_parse_rendered_jar_nbsp_thousands():
    """Роздільник тисяч — nbsp (\\xa0) і звичайний пробіл."""
    from fundrec.jars import parse_rendered_jar

    body = "Збір\n1\xa0500\xa0000 ₴\n5\xa0000\xa0000 ₴\n"
    result = parse_rendered_jar("NBSP", body)
    assert result["amount_uah"] == pytest.approx(1_500_000.0)
    assert result["goal_amount"] == pytest.approx(5_000_000.0)


def test_parse_rendered_jar_comma_decimal():
    """Десятковий роздільник — кома (напр. 1 234,56 ₴)."""
    from fundrec.jars import parse_rendered_jar

    body = "Збір\n1 234,56 ₴\n10 000 ₴\n"
    result = parse_rendered_jar("COMMA", body)
    assert result["amount_uah"] == pytest.approx(1_234.56)
