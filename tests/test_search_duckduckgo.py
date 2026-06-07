"""Tests for fundrec.search.duckduckgo — parse_results + search (injected client)."""
from __future__ import annotations

from pathlib import Path


FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "ddg_results.html").read_text(encoding="utf-8")


def test_parse_results_extracts_real_urls():
    from fundrec.search.duckduckgo import parse_results
    urls = parse_results(FIXTURE_HTML)
    assert "https://example.com/page1" in urls
    assert "https://example.org/page2" in urls


def test_parse_results_skips_ad_links():
    from fundrec.search.duckduckgo import parse_results
    urls = parse_results(FIXTURE_HTML)
    assert not any("ads.example.com" in u for u in urls)


def test_parse_results_skips_internal_duckduckgo_links():
    from fundrec.search.duckduckgo import parse_results
    urls = parse_results(FIXTURE_HTML)
    assert not any("duckduckgo.com" in u for u in urls)


def test_parse_results_deduplicates():
    from fundrec.search.duckduckgo import parse_results
    urls = parse_results(FIXTURE_HTML)
    assert urls.count("https://example.com/page1") == 1


def test_parse_results_empty_html_returns_empty():
    from fundrec.search.duckduckgo import parse_results
    assert parse_results("<html></html>") == []


def test_search_returns_urls_via_injected_client():
    from fundrec.search.duckduckgo import search

    class FakeResp:
        text = FIXTURE_HTML
        def raise_for_status(self): pass

    class FakeClient:
        def post(self, url, data=None, headers=None, timeout=None):
            return FakeResp()

    urls = search("FPV дрони", _client=FakeClient())
    assert isinstance(urls, list)
    assert "https://example.com/page1" in urls


def test_search_respects_max_results():
    from fundrec.search.duckduckgo import search

    # Build HTML with 15 unique results
    links = "\n".join(
        f'<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F{i}">R{i}</a></div>'
        for i in range(15)
    )
    html = f"<html><body>{links}</body></html>"

    class FakeResp:
        text = html
        def raise_for_status(self): pass

    class FakeClient:
        def post(self, url, data=None, headers=None, timeout=None):
            return FakeResp()

    urls = search("query", max_results=5, _client=FakeClient())
    assert len(urls) <= 5
