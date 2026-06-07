"""DuckDuckGo HTML пошуковий провайдер (без ключа).

parse_results(html) -> list[str]  — чиста функція, витягує результатні URLs.
search(query, *, max_results, _client) -> list[str]  — POST до DDG html endpoint;
  _client інжектується (має .post(url, data, headers, timeout)); за замовчуванням httpx.
  Живий виклик: # pragma: no cover.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_DDG_DOMAIN = "duckduckgo.com"


class _DDGResultParser(HTMLParser):
    """Витягує href з <a class="result__a"> що не є рекламою."""

    def __init__(self) -> None:
        super().__init__()
        self._in_ad = False
        self._depth_stack: list[tuple[str, list[str]]] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = (attr_map.get("class") or "").split()

        if tag == "div":
            self._depth_stack.append(("div", classes))
            if "result--ad" in classes:
                self._in_ad = True

        if tag == "a" and "result__a" in classes and not self._in_ad:
            href = attr_map.get("href") or ""
            url = _extract_uddg(href)
            if url and _DDG_DOMAIN not in urlparse(url).netloc:
                self.hrefs.append(url)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._depth_stack:
            _, classes = self._depth_stack.pop()
            if "result--ad" in classes:
                self._in_ad = False


def _extract_uddg(href: str) -> str | None:
    """Витягує реальний URL з DDG-редиректного href.

    Підтримує два формати:
    - //duckduckgo.com/l/?uddg=<encoded_url>&...
    - пряме https:// посилання (рідко)
    """
    if not href:
        return None
    # Normalize protocol-relative
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    # DDG redirect: extract uddg param
    if "duckduckgo.com" in parsed.netloc and parsed.path in ("/l/", "/l"):
        params = parse_qs(parsed.query)
        uddg = params.get("uddg", [None])[0]
        if uddg:
            return unquote(uddg)
        return None
    # Direct URL (non-DDG)
    if parsed.scheme in ("http", "https"):
        return href
    return None


def parse_results(html: str) -> list[str]:
    """Витягує результатні URLs зі сторінки DuckDuckGo HTML-пошуку.

    Пропускає рекламні блоки (result--ad), внутрішні DDG-посилання, дублікати.
    """
    parser = _DDGResultParser()
    parser.feed(html)
    seen: set[str] = set()
    result: list[str] = []
    for url in parser.hrefs:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def search(
    query: str,
    *,
    max_results: int = 10,
    _client: Any | None = None,
) -> list[str]:
    """Шукає в DuckDuckGo HTML і повертає список URLs.

    _client інжектується в тестах (має .post(url, data, headers, timeout)).
    За замовчуванням використовує httpx (lazy import).
    """
    if _client is None:
        _client = _live_client()  # pragma: no cover

    resp = _client.post(
        _DDG_HTML_URL,
        data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (fundrec recon bot)"},
        timeout=15,
    )
    resp.raise_for_status()
    urls = parse_results(resp.text)
    return urls[:max_results]


def _live_client():  # pragma: no cover
    """Повертає живий httpx.Client (lazy import)."""
    import httpx  # noqa: PLC0415
    return httpx.Client(follow_redirects=True, timeout=15)
