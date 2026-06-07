import json
from pathlib import Path

from fundrec.collect import monobank

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "monobank_jar.json").read_text(encoding="utf-8"))
HTML_FIXTURE = (Path(__file__).parent / "fixtures" / "monobank_jar.html").read_text(encoding="utf-8")


def test_parse_jar_maps_fields():
    raw = monobank.parse_jar("abc123", FIXTURE)
    assert raw["jar_id"] == "abc123"
    assert raw["url"] == "https://send.monobank.ua/jar/abc123"
    assert raw["title"] == "На FPV для 3-ї бригади"
    assert raw["amount_uah"] == 1250000.0      # копійки -> гривні
    assert raw["goal_amount"] == 2000000.0
    assert raw["currency_raw"] == "UAH"

def test_fetch_jar_uses_injected_client():
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return FIXTURE
    class FakeClient:
        def get(self, url, timeout=None): return FakeResp()
    raw = monobank.fetch_jar("abc123", _client=FakeClient())
    assert raw["amount_uah"] == 1250000.0


def test_parse_jar_html_extracts_title():
    from fundrec.collect.monobank import parse_jar_html
    result = parse_jar_html("abc123", HTML_FIXTURE)
    assert result["jar_id"] == "abc123"
    assert result["title"] == "На дрони для 3-ї бригади | Monobank"


def test_parse_jar_html_extracts_amount():
    from fundrec.collect.monobank import parse_jar_html
    result = parse_jar_html("abc123", HTML_FIXTURE)
    assert result["amount_uah"] == 1_250_000.0


def test_parse_jar_html_extracts_goal():
    from fundrec.collect.monobank import parse_jar_html
    result = parse_jar_html("abc123", HTML_FIXTURE)
    assert result["goal_amount"] == 2_000_000.0


def test_parse_jar_html_url_format():
    from fundrec.collect.monobank import parse_jar_html
    result = parse_jar_html("xyz999", HTML_FIXTURE)
    assert result["url"] == "https://send.monobank.ua/jar/xyz999"


def test_fetch_jar_falls_back_to_html_on_non_json():
    from fundrec.collect.monobank import fetch_jar

    class FakeRespHtml:
        text = HTML_FIXTURE
        def raise_for_status(self): pass
        def json(self): raise ValueError("not JSON")

    class FakeClient:
        def get(self, url, timeout=None): return FakeRespHtml()

    result = fetch_jar("abc123", _client=FakeClient())
    assert result["amount_uah"] == 1_250_000.0
    assert result["title"] is not None
