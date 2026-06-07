import json
from pathlib import Path

from fundrec.collect import monobank

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "monobank_jar.json").read_text(encoding="utf-8"))

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
