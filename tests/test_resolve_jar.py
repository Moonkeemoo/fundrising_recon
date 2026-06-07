"""Unit 2 — resolve_jar_id та jar_ids_from_raw_resolved.

Всі мережеві виклики ін'єктовані через fake _client.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class _FakeResp:
    """Fake httpx Response."""

    def __init__(self, final_url: str, status_code: int = 200):
        self.url = final_url
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRedirectClient:
    """Повертає відповідь з final_url після HEAD/GET."""

    def __init__(self, redirect_map: dict[str, str], *, raise_head: bool = False):
        self._map = redirect_map
        self._raise_head = raise_head
        self.calls: list[tuple[str, str]] = []  # (method, url)

    def head(self, url: str, *, timeout: int = 10):
        self.calls.append(("HEAD", url))
        if self._raise_head:
            raise ConnectionError("HEAD not supported")
        final = self._map.get(url, url)
        return _FakeResp(final)

    def get(self, url: str, *, timeout: int = 10):
        self.calls.append(("GET", url))
        final = self._map.get(url, url)
        return _FakeResp(final)


# ---------------------------------------------------------------------------
# resolve_jar_id — прямий URL
# ---------------------------------------------------------------------------


def test_resolve_direct_jar_url_returns_id():
    """Прямий URL send.monobank.ua → id без мережевих викликів."""
    from fundrec.jars import resolve_jar_id

    result = resolve_jar_id("https://send.monobank.ua/jar/XYZ999")
    assert result == "XYZ999"


def test_resolve_direct_base_monobank_url():
    """base.monobank.ua теж розпізнається."""
    from fundrec.jars import resolve_jar_id

    result = resolve_jar_id("https://base.monobank.ua/jar/BASE111")
    assert result == "BASE111"


def test_resolve_direct_no_client_needed():
    """Прямий jar URL: _client не викликається."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({})
    resolve_jar_id("https://send.monobank.ua/jar/DIRECT", _client=client)
    assert client.calls == []


# ---------------------------------------------------------------------------
# resolve_jar_id — скорочений URL → jar
# ---------------------------------------------------------------------------


def test_resolve_surl_li_via_head():
    """surl.li/x → send.monobank.ua/jar/JARFOUND через HEAD."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://surl.li/abcde": "https://send.monobank.ua/jar/JARFOUND",
    })
    result = resolve_jar_id("https://surl.li/abcde", _client=client)
    assert result == "JARFOUND"
    assert any(m == "HEAD" for m, _ in client.calls)


def test_resolve_cutt_ly_via_head():
    """cutt.ly → jar."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://cutt.ly/xyz": "https://send.monobank.ua/jar/CUTTJAR",
    })
    result = resolve_jar_id("https://cutt.ly/xyz", _client=client)
    assert result == "CUTTJAR"


def test_resolve_bit_ly_via_head():
    """bit.ly → jar."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://bit.ly/xyz123": "https://send.monobank.ua/jar/BITLYJAR",
    })
    result = resolve_jar_id("https://bit.ly/xyz123", _client=client)
    assert result == "BITLYJAR"


def test_resolve_head_failure_falls_back_to_get():
    """HEAD кидає помилку → fallback на GET."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient(
        {"https://surl.li/fail": "https://send.monobank.ua/jar/GETJAR"},
        raise_head=True,
    )
    result = resolve_jar_id("https://surl.li/fail", _client=client)
    assert result == "GETJAR"
    methods = [m for m, _ in client.calls]
    assert "GET" in methods


def test_resolve_shortener_no_jar_redirect_returns_none():
    """Скорочений URL веде НЕ на банку → None."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://surl.li/nojar": "https://example.com/some-page",
    })
    result = resolve_jar_id("https://surl.li/nojar", _client=client)
    assert result is None


def test_resolve_unknown_host_returns_none():
    """Незнайомий хост, не скорочувач, не jar → None (без мережевих викликів)."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({})
    result = resolve_jar_id("https://example.com/donate", _client=client)
    assert result is None
    assert client.calls == []


# ---------------------------------------------------------------------------
# Кешування
# ---------------------------------------------------------------------------


def test_resolve_cache_avoids_second_fetch():
    """Кеш: повторний виклик з тим самим URL → другий запит не здійснюється."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://surl.li/once": "https://send.monobank.ua/jar/CACHED",
    })
    cache: dict = {}
    result1 = resolve_jar_id("https://surl.li/once", _client=client, _cache=cache)
    result2 = resolve_jar_id("https://surl.li/once", _client=client, _cache=cache)
    assert result1 == "CACHED"
    assert result2 == "CACHED"
    # Другий виклик НЕ повинен звертатись до клієнта
    head_calls = [u for m, u in client.calls if m == "HEAD"]
    assert head_calls.count("https://surl.li/once") == 1


def test_resolve_cache_stores_none():
    """None теж кешується (не ходимо в мережу вдруге для non-jar)."""
    from fundrec.jars import resolve_jar_id

    client = _FakeRedirectClient({
        "https://surl.li/none": "https://example.com/",
    })
    cache: dict = {}
    resolve_jar_id("https://surl.li/none", _client=client, _cache=cache)
    resolve_jar_id("https://surl.li/none", _client=client, _cache=cache)
    head_calls = [u for m, u in client.calls if m == "HEAD"]
    assert head_calls.count("https://surl.li/none") == 1


# ---------------------------------------------------------------------------
# jar_ids_from_raw_resolved
# ---------------------------------------------------------------------------


def test_raw_resolved_direct_jar_in_links():
    """links містить прямий jar URL → id повертається без мережі."""
    from fundrec.jars import jar_ids_from_raw_resolved

    raw = {
        "text": "Деталі нижче.",
        "links": ["https://send.monobank.ua/jar/LINKJAR"],
    }
    result = jar_ids_from_raw_resolved(raw)
    assert "LINKJAR" in result


def test_raw_resolved_shortener_in_links_resolved():
    """links містить скорочений URL → jar id через _client."""
    from fundrec.jars import jar_ids_from_raw_resolved

    client = _FakeRedirectClient({
        "https://surl.li/shortone": "https://send.monobank.ua/jar/SHORTJAR",
    })
    raw = {
        "text": "Підтримайте нас.",
        "links": ["https://surl.li/shortone"],
    }
    result = jar_ids_from_raw_resolved(raw, _client=client)
    assert "SHORTJAR" in result


def test_raw_resolved_dedup_across_text_and_links():
    """Той самий jar_id у тексті і в links → один раз."""
    from fundrec.jars import jar_ids_from_raw_resolved

    raw = {
        "text": "send.monobank.ua/jar/DUP",
        "links": ["https://send.monobank.ua/jar/DUP"],
    }
    result = jar_ids_from_raw_resolved(raw)
    assert result.count("DUP") == 1


def test_raw_resolved_non_jar_shortener_skipped():
    """Скорочений URL без jar → не включається в результат."""
    from fundrec.jars import jar_ids_from_raw_resolved

    client = _FakeRedirectClient({
        "https://surl.li/nojar": "https://example.com/page",
    })
    raw = {
        "text": "",
        "links": ["https://surl.li/nojar"],
    }
    result = jar_ids_from_raw_resolved(raw, _client=client)
    assert result == []


def test_raw_resolved_offline_direct_path_works():
    """Без _client прямий jar у text повертається (офлайн-шлях)."""
    from fundrec.jars import jar_ids_from_raw_resolved

    raw = {"text": "https://send.monobank.ua/jar/OFFLINE001", "links": []}
    result = jar_ids_from_raw_resolved(raw)
    assert "OFFLINE001" in result
