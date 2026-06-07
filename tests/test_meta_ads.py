"""Тести колектора Meta Ad Library API."""
from __future__ import annotations

import json
from pathlib import Path

from fundrec.collect import meta_ads

FIXTURES = Path(__file__).parent / "fixtures"
META_FIXTURE = json.loads((FIXTURES / "meta_ads.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# parse_ad
# ---------------------------------------------------------------------------

def test_parse_ad_full_fields():
    ad = META_FIXTURE["data"][0]
    result = meta_ads.parse_ad(ad)
    assert result["platform"] == "meta_ads"
    assert result["source_url"] == ad["ad_snapshot_url"]
    assert result["page_name"] == "Повернись живим"
    assert "Допомога пораненим" in result["ad_creative_bodies"][0]
    assert result["ad_delivery_start"] == "2023-08-01"
    assert result["ad_delivery_stop"] == "2023-08-31"
    assert "facebook" in result["publisher_platforms"]
    assert "instagram" in result["publisher_platforms"]
    assert result["impressions_range"] == "10000-49999"
    assert result["spend_range"] == "1000-4999"
    assert result["currency"] == "UAH"


def test_parse_ad_threads_in_publisher_platforms():
    """Threads має бути нормально у publisher_platforms."""
    ad = META_FIXTURE["data"][1]
    result = meta_ads.parse_ad(ad)
    assert "threads" in result["publisher_platforms"]
    assert result["page_name"] == "UNITED24"


def test_parse_ad_null_stop_time():
    ad = META_FIXTURE["data"][1]
    result = meta_ads.parse_ad(ad)
    assert result["ad_delivery_stop"] is None


def test_parse_ad_null_impressions_and_spend():
    """Якщо impressions/spend null — honest None, не рядок."""
    ad = META_FIXTURE["data"][2]
    result = meta_ads.parse_ad(ad)
    assert result["impressions_range"] is None
    assert result["spend_range"] is None


def test_parse_ad_multiple_creative_bodies():
    ad = META_FIXTURE["data"][1]
    result = meta_ads.parse_ad(ad)
    assert len(result["ad_creative_bodies"]) == 2


def test_parse_ad_empty_creative_bodies():
    ad = META_FIXTURE["data"][2]
    result = meta_ads.parse_ad(ad)
    assert result["ad_creative_bodies"] == []


def test_parse_ad_all_required_keys():
    ad = META_FIXTURE["data"][0]
    result = meta_ads.parse_ad(ad)
    required = (
        "source_url", "platform", "page_name", "ad_creative_bodies",
        "ad_delivery_start", "ad_delivery_stop", "publisher_platforms",
        "impressions_range", "spend_range", "currency",
    )
    for key in required:
        assert key in result, f"Missing key: {key}"


def test_parse_ad_impressions_range_format():
    """Формат range — рядок 'lower-upper'."""
    ad = META_FIXTURE["data"][0]
    result = meta_ads.parse_ad(ad)
    assert result["impressions_range"] == "10000-49999"
    assert result["spend_range"] == "1000-4999"


# ---------------------------------------------------------------------------
# search_ads — graceful-skip без токена
# ---------------------------------------------------------------------------

def test_search_ads_no_token_returns_empty(capsys):
    result = meta_ads.search_ads("збір на ЗСУ", token="")
    assert result == []
    captured = capsys.readouterr()
    assert "meta" in (captured.out + captured.err).lower()


def test_search_ads_none_token_returns_empty():
    result = meta_ads.search_ads("test", token=None)
    assert result == []


# ---------------------------------------------------------------------------
# search_ads — injected client
# ---------------------------------------------------------------------------

class _FakeMetaClient:
    def __init__(self, resp_data: dict):
        self._data = resp_data
        self.calls: list[tuple] = []

    def get(self, url: str, *, params: dict | None = None, timeout: int = 20):
        self.calls.append((url, params))
        return _FakeResp(self._data)


class _FakeResp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_search_ads_injected_client_returns_ads():
    client = _FakeMetaClient(META_FIXTURE)
    results = meta_ads.search_ads("збір", token="fake-token", _client=client)
    assert len(results) == 3
    assert results[0]["platform"] == "meta_ads"
    assert results[1]["page_name"] == "UNITED24"


def test_search_ads_default_token_from_config(monkeypatch):
    monkeypatch.delenv("META_ADS_TOKEN", raising=False)
    result = meta_ads.search_ads("test")
    assert result == []


def test_search_ads_all_fields_present():
    client = _FakeMetaClient(META_FIXTURE)
    results = meta_ads.search_ads("test", token="k", _client=client)
    required = (
        "source_url", "platform", "page_name", "ad_creative_bodies",
        "ad_delivery_start", "ad_delivery_stop", "publisher_platforms",
        "impressions_range", "spend_range", "currency",
    )
    for r in results:
        for key in required:
            assert key in r
