# F4 Live-Wiring + Ingest CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire real web-search (DuckDuckGo), real LLM extraction (Claude Agent SDK + fallback), robust Monobank HTML parse, and a unified `ingest` CLI that orchestrates discover → collect → extract → verify → analyze → export — fully injectable and tested.

**Architecture:** Every live/network call is hidden behind an injectable seam; pure helpers (URL parsing, JSON extraction, HTML parsing) are extracted and tested directly; `ingest.py` orchestrates existing pipeline pieces and delegates to them via a `_components` dict injected in tests. The `search/duckduckgo.py` module ships `parse_results` (pure) and `search` (injectable client); `_live_complete` in `extract.py` is refactored to expose a pure `_json_from_text` helper and a proper async+sync wrapper for the Agent SDK call with Anthropic API fallback.

**Tech Stack:** Python 3.11+, pytest, ruff, httpx (lazy), claude_agent_sdk (lazy), anthropic (lazy), stdlib `asyncio`, `re`, `html.parser`.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `src/fundrec/search/__init__.py` | Re-exports `search` from duckduckgo submodule |
| Create | `src/fundrec/search/duckduckgo.py` | `parse_results(html) -> list[str]` (pure) + `search(query, *, max_results, _client) -> list[str]` |
| Modify | `src/fundrec/discover.py` | `_live_search` calls `search.duckduckgo.search` instead of returning `[]` |
| Modify | `src/fundrec/extract.py` | Extract `_json_from_text(text) -> dict` (pure, tested); rewrite `_live_complete` to use async Agent SDK + fallback |
| Modify | `src/fundrec/collect/monobank.py` | Add `parse_jar_html(jar_id, html) -> dict`; `fetch_jar` tries JSON then HTML |
| Create | `src/fundrec/ingest.py` | `run_ingest(theme, ...)` orchestrator + `__main__` CLI |
| Create | `tests/fixtures/ddg_results.html` | DuckDuckGo HTML results page fixture |
| Create | `tests/fixtures/monobank_jar.html` | Monobank jar HTML page fixture |
| Create | `tests/test_search_duckduckgo.py` | Tests for `parse_results`, `search` happy path |
| Create | `tests/test_extract_json_helper.py` | Tests for `_json_from_text` |
| Modify | `tests/test_monobank.py` | Add tests for `parse_jar_html` + `fetch_jar` HTML fallback |
| Create | `tests/test_ingest.py` | End-to-end fake test, dry-run, resumability |

---

## Task 1: `search/duckduckgo.py` — fixtures + `parse_results`

**Files:**
- Create: `tests/fixtures/ddg_results.html`
- Create: `src/fundrec/search/__init__.py`
- Create: `src/fundrec/search/duckduckgo.py`
- Create: `tests/test_search_duckduckgo.py`

### Background: DuckDuckGo HTML endpoint

`POST https://html.duckduckgo.com/html/` with form data `q=<query>` returns an HTML page. Result links are `<a class="result__a" href="...">` where `href` is a DuckDuckGo redirect like `//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&...` — the real URL is in the `uddg=` query param (URL-encoded). Some links are DuckDuckGo-internal (`duckduckgo.com` domain) and must be skipped. Ads (`result--ad` class) must be skipped.

- [ ] **Step 1.1: Create the HTML fixture**

Create `tests/fixtures/ddg_results.html` with minimal DuckDuckGo-style HTML containing real result links, an ad link, and an internal link:

```html
<!DOCTYPE html>
<html>
<body>
<div class="results">
  <!-- Real result -->
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1&rut=abc">Page 1</a>
  </div>
  <!-- Another real result -->
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage2&rut=def">Page 2</a>
  </div>
  <!-- Ad result — should be skipped -->
  <div class="result result--ad">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fads.example.com%2F&rut=ghi">Ad</a>
  </div>
  <!-- Internal DDG link — should be skipped -->
  <div class="result">
    <a class="result__a" href="https://duckduckgo.com/settings">DDG internal</a>
  </div>
  <!-- Duplicate of page1 — should be deduped -->
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1&rut=zzz">Page 1 dup</a>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 1.2: Write failing tests for `parse_results`**

Create `tests/test_search_duckduckgo.py`:

```python
"""Tests for fundrec.search.duckduckgo — parse_results + search (injected client)."""
from __future__ import annotations

from pathlib import Path

import pytest

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
```

- [ ] **Step 1.3: Run tests to confirm they fail**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_search_duckduckgo.py -v 2>&1 | head -30
```

Expected: ImportError — `fundrec.search` does not exist yet.

- [ ] **Step 1.4: Create `src/fundrec/search/__init__.py`**

```python
"""Модуль пошуку: провайдери веб-пошуку для discover."""
from __future__ import annotations

from .duckduckgo import search as duckduckgo_search

__all__ = ["duckduckgo_search"]
```

- [ ] **Step 1.5: Create `src/fundrec/search/duckduckgo.py`**

```python
"""DuckDuckGo HTML пошуковий провайдер (без ключа).

parse_results(html) -> list[str]  — чиста функція, витягує результатні URLs.
search(query, *, max_results, _client) -> list[str]  — POST до DDG html endpoint;
  _client інжектується (має .post(url, data, headers, timeout)); за замовчуванням httpx.
  Живий виклик: # pragma: no cover.
"""
from __future__ import annotations

import re
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
        self._ad_depth = 0
        self._current_depth = 0
        self._current_div_classes: list[str] = []
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
```

- [ ] **Step 1.6: Run tests to confirm they pass**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_search_duckduckgo.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 1.7: Run full suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: 352 + 7 = 359 passed, 0 failed.

- [ ] **Step 1.8: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/search/ tests/test_search_duckduckgo.py --fix
```

Expected: no errors.

- [ ] **Step 1.9: Commit**

```bash
git add src/fundrec/search/__init__.py src/fundrec/search/duckduckgo.py tests/fixtures/ddg_results.html tests/test_search_duckduckgo.py
git commit -c commit.gpgsign=false -m "feat: додати search/duckduckgo — parse_results + search (інжектабельний клієнт)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire `discover._live_search` to `search.duckduckgo`

**Files:**
- Modify: `src/fundrec/discover.py`
- (No new test file needed — existing `tests/test_discover.py` covers injectable path; add one assertion about import)

### Background

`_live_search` currently returns `[]`. We need it to call `search.duckduckgo.search(query)`. The body stays `# pragma: no cover` because it uses the live httpx call path. We add a module-level comment asserting the import so the wiring is observable in tests.

- [ ] **Step 2.1: Modify `_live_search` in `src/fundrec/discover.py`**

Replace:

```python
def _live_search(query: str) -> list[str]:  # pragma: no cover
    """Live-заглушка пошуку. Замінити на реальний пошук (Claude Agent SDK / httpx / DuckDuckGo API).

    Повертає порожній список поки не підключено.
    """
    return []
```

With:

```python
def _live_search(query: str) -> list[str]:  # pragma: no cover
    """Живий веб-пошук через DuckDuckGo HTML (без ключа).

    Тонка обгортка навколо search.duckduckgo.search — тестується через
    discover_sources з інжектованим _search; цей рядок # pragma: no cover.
    """
    from .search import duckduckgo  # noqa: PLC0415
    return duckduckgo.search(query)
```

- [ ] **Step 2.2: Add import-wiring assertion to existing test file**

Add to `tests/test_discover.py` at the end:

```python
def test_live_search_wired_to_duckduckgo():
    """_live_search imports search.duckduckgo — wiring is testable via source inspection."""
    import inspect
    from fundrec import discover
    src = inspect.getsource(discover._live_search)
    assert "duckduckgo" in src
```

- [ ] **Step 2.3: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/test_discover.py -v
```

Expected: all discover tests pass including the new wiring assertion.

- [ ] **Step 2.4: Run full suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: 360 passed (1 new), 0 failed.

- [ ] **Step 2.5: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/discover.py tests/test_discover.py --fix
```

- [ ] **Step 2.6: Commit**

```bash
git add src/fundrec/discover.py tests/test_discover.py
git commit -c commit.gpgsign=false -m "feat: підключити _live_search до search.duckduckgo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `extract._json_from_text` — pure helper + tests

**Files:**
- Modify: `src/fundrec/extract.py` (add `_json_from_text` near top; adjust `_live_complete`)
- Create: `tests/test_extract_json_helper.py`

### Background

The current `_live_complete` does `json.loads("".join(chunks))` directly. We need to handle LLM responses that wrap JSON in markdown fences (` ```json\n{...}\n``` `) or have leading/trailing prose. Extract `_json_from_text(text: str) -> dict` as a pure tested helper.

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_extract_json_helper.py`:

```python
"""Tests for fundrec.extract._json_from_text — pure JSON extraction from LLM text."""
from __future__ import annotations

import pytest

from fundrec.extract import _json_from_text


def test_raw_json_object():
    text = '{"title": "FPV", "amount_uah": 1000}'
    result = _json_from_text(text)
    assert result["title"] == "FPV"
    assert result["amount_uah"] == 1000


def test_json_in_fenced_code_block():
    text = '```json\n{"title": "Дрони", "goal": "military"}\n```'
    result = _json_from_text(text)
    assert result["title"] == "Дрони"


def test_json_in_plain_code_block():
    text = '```\n{"title": "Дрони"}\n```'
    result = _json_from_text(text)
    assert result["title"] == "Дрони"


def test_json_with_leading_prose():
    text = 'Ось результат:\n{"title": "Тест", "year": 2024}'
    result = _json_from_text(text)
    assert result["title"] == "Тест"
    assert result["year"] == 2024


def test_json_with_trailing_prose():
    text = '{"title": "Тест"}\nЦе все що я знайшов.'
    result = _json_from_text(text)
    assert result["title"] == "Тест"


def test_json_with_both_prose():
    text = 'Аналіз:\n```json\n{"amount_uah": 500000}\n```\nГотово.'
    result = _json_from_text(text)
    assert result["amount_uah"] == 500000


def test_no_json_raises_value_error():
    with pytest.raises((ValueError, Exception)):
        _json_from_text("Немає JSON тут взагалі.")


def test_empty_string_raises():
    with pytest.raises((ValueError, Exception)):
        _json_from_text("")
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```
.venv\Scripts\python.exe -m pytest tests/test_extract_json_helper.py -v 2>&1 | head -20
```

Expected: ImportError — `_json_from_text` does not exist yet.

- [ ] **Step 3.3: Add `_json_from_text` to `src/fundrec/extract.py`**

Insert after the `import` block (after line 18, before `_TIER_CONFIDENCE`):

```python
def _json_from_text(text: str) -> dict:
    """Витягує JSON-об'єкт з тексту LLM-відповіді.

    Підтримує:
    - Сирий JSON: {"key": ...}
    - Markdown-фенс: ```json\\n{...}\\n```
    - Ведучий/завершальний прозовий текст — беремо перший {...} блок.

    Raises ValueError якщо JSON не знайдено.
    """
    import json  # noqa: PLC0415

    if not text:
        raise ValueError("порожній текст — немає JSON")

    # 1. Спробуємо знайти ```json ... ``` або ``` ... ``` фенс
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    # 2. Знаходимо перший {...} блок (ігноруємо зовнішній прозовий текст)
    brace_start = text.find("{")
    if brace_start == -1:
        raise ValueError(f"JSON-об'єкт не знайдено в тексті: {text[:200]!r}")

    # Знаходимо відповідну закриваючу дужку
    depth = 0
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start: i + 1])

    raise ValueError(f"Незакрита JSON-дужка в тексті: {text[:200]!r}")
```

- [ ] **Step 3.4: Run tests**

```
.venv\Scripts\python.exe -m pytest tests/test_extract_json_helper.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 3.5: Run full suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: 361+ passed, 0 failed.

- [ ] **Step 3.6: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/extract.py tests/test_extract_json_helper.py --fix
```

- [ ] **Step 3.7: Commit**

```bash
git add src/fundrec/extract.py tests/test_extract_json_helper.py
git commit -c commit.gpgsign=false -m "feat: додати _json_from_text — чистий хелпер витягування JSON з LLM-тексту

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Rewrite `extract._live_complete` (Agent SDK + fallback)

**Files:**
- Modify: `src/fundrec/extract.py` (replace `_live_complete` body)

### Background

The existing `_live_complete` is `# pragma: no cover`. We rewrite it to:
1. Try Claude Agent SDK: `from claude_agent_sdk import query` (lazy); call `asyncio.run(_async_complete(prompt))`; collect text blocks; parse with `_json_from_text`.
2. On any import/call failure: fallback to direct Anthropic API via `anthropic` (lazy); `config.CRITIC_API_KEY`; `config.EXTRACT_MODEL`; parse with `_json_from_text`.

No new tests needed for `_live_complete` itself (stays `# pragma: no cover`). The tested surface is `_json_from_text` (done in Task 3) and `extract_case`/`extract_campaign` with injected `_complete` (already tested).

- [ ] **Step 4.1: Replace `_live_complete` in `src/fundrec/extract.py`**

Replace the existing `_live_complete` function (lines 86-97):

```python
def _live_complete(prompt: str) -> dict:  # pragma: no cover - мережа/LLM
    """Живий виклик через Claude Agent SDK (підписка, без ключа).

    Запасний шлях — прямий Anthropic API якщо SDK не доступний.
    Парсинг JSON через _json_from_text (чистий хелпер, тестується окремо).
    """
    import asyncio  # noqa: PLC0415

    async def _async_sdk(p: str) -> dict:
        from claude_agent_sdk import query as sdk_query  # noqa: PLC0415
        chunks: list[str] = []
        async for msg in sdk_query(prompt=p):
            text = getattr(msg, "text", None)
            if text:
                chunks.append(text)
        return _json_from_text("".join(chunks))

    # Спроба 1: Agent SDK
    try:
        return asyncio.run(_async_sdk(prompt))
    except Exception:  # noqa: BLE001
        pass

    # Запасний шлях: прямий Anthropic API
    from . import config as _cfg  # noqa: PLC0415
    import anthropic  # noqa: PLC0415
    client = anthropic.Anthropic(api_key=_cfg.CRITIC_API_KEY)
    message = client.messages.create(
        model=_cfg.EXTRACT_MODEL,
        max_tokens=2048,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text
    return _json_from_text(text)
```

- [ ] **Step 4.2: Run full suite (no regressions)**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: same count as before, 0 failed.

- [ ] **Step 4.3: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/extract.py --fix
```

- [ ] **Step 4.4: Commit**

```bash
git add src/fundrec/extract.py
git commit -c commit.gpgsign=false -m "feat: _live_complete — Agent SDK async + Anthropic API fallback, парсинг через _json_from_text

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Monobank `parse_jar_html` + HTML fallback in `fetch_jar`

**Files:**
- Create: `tests/fixtures/monobank_jar.html`
- Modify: `src/fundrec/collect/monobank.py`
- Modify: `tests/test_monobank.py`

### Background

Some Monobank jar endpoints return HTML instead of JSON (e.g. when the endpoint changes or for older jars). We add `parse_jar_html(jar_id, html) -> dict` using the same regex patterns as `collect/reports.py`. We also update `fetch_jar` to detect non-JSON responses and fall back to HTML parsing.

- [ ] **Step 5.1: Create the Monobank HTML fixture**

Create `tests/fixtures/monobank_jar.html`:

```html
<!DOCTYPE html>
<html lang="uk">
<head>
  <title>На дрони для 3-ї бригади | Monobank</title>
</head>
<body>
  <h1>На дрони для 3-ї бригади</h1>
  <div class="jar-amount">зібрано 1 250 000 грн</div>
  <div class="jar-goal">ціль: 2 000 000 грн</div>
</body>
</html>
```

- [ ] **Step 5.2: Write failing tests for `parse_jar_html` and HTML fallback**

Add to `tests/test_monobank.py`:

```python
from pathlib import Path

HTML_FIXTURE = (Path(__file__).parent / "fixtures" / "monobank_jar.html").read_text(encoding="utf-8")


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
```

- [ ] **Step 5.3: Run tests to confirm they fail**

```
.venv\Scripts\python.exe -m pytest tests/test_monobank.py -v 2>&1 | tail -20
```

Expected: `ImportError` or `AttributeError` for `parse_jar_html`.

- [ ] **Step 5.4: Implement `parse_jar_html` and update `fetch_jar` in `src/fundrec/collect/monobank.py`**

Replace the file content:

```python
"""Колектор банок Monobank: дістає публічний JSON банки -> сирий dict.

amount/goal у JSON — у копійках; ділимо на 100 -> гривні. Реальний формат
ендпоінта підтвердити на першому живому запуску (spec §10).

parse_jar_html — запасний парсер HTML-сторінки банки (регекспи по тексту).
fetch_jar — пробує JSON спочатку, потім HTML при помилці.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

JAR_URL = "https://send.monobank.ua/jar/{jar_id}"
JAR_JSON_URL = "https://send.monobank.ua/api/handler"  # підтвердити на живому запуску

_NUM_PAT = r"[\d][\d\s]{0,20}[\d]|[\d]+"


def _parse_number(num_str: str) -> float:
    cleaned = re.sub(r"[\s,]", "", num_str)
    return float(cleaned)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()


def _extract_title(html: str) -> str | None:
    p = _TitleParser()
    p.feed(html)
    return p.title


def parse_jar(jar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Парсить JSON-відповідь банки Monobank."""
    amount = payload.get("amount")
    goal = payload.get("goal")
    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": payload.get("title"),
        "amount_uah": (amount / 100.0) if amount is not None else None,
        "goal_amount": (goal / 100.0) if goal is not None else None,
        "currency_raw": payload.get("currency", "UAH"),
    }


def parse_jar_html(jar_id: str, html: str) -> dict[str, Any]:
    """Запасний парсер HTML-сторінки банки Monobank.

    Витягує title, amount_uah і goal_amount через регекспи по видимому тексту.
    Honest null: відсутні поля = None.
    """
    html_norm = html.replace("\xa0", " ").replace("&nbsp;", " ")
    title = _extract_title(html_norm)

    # Витягуємо текст (без тегів) для пошуку регекспами
    text = re.sub(r"<[^>]+>", " ", html_norm)
    text = re.sub(r"\s+", " ", text)

    # Сума: "зібрано X грн" або "₴ X"
    amount_uah: float | None = None
    for pattern in [
        rf"(?:зібрано|collected|raised)\s+({_NUM_PAT})\s*(?:грн|гривень|UAH)",
        rf"[₴]\s*({_NUM_PAT})",
        rf"({_NUM_PAT})\s*(?:грн|гривень)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    amount_uah = val
                    break
            except ValueError:
                continue

    # Ціль: "ціль: X грн"
    goal_amount: float | None = None
    for pattern in [
        rf"(?:ціль|мета|goal|target)[\s:]*({_NUM_PAT})\s*(?:грн|гривень|UAH|₴)?",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = _parse_number(m.group(1))
                if val > 0:
                    goal_amount = val
                    break
            except ValueError:
                continue

    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
        "currency_raw": "UAH",
    }


def fetch_jar(jar_id: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Дістає банку. _client інжектується в тестах; інакше httpx.

    Спроба 1: JSON-відповідь (parse_jar).
    Запасний шлях: HTML-відповідь (parse_jar_html) якщо resp.json() кидає виняток.
    """
    if _client is None:
        import httpx  # noqa: PLC0415
        _client = httpx.Client(follow_redirects=True)
    resp = _client.get(JAR_URL.format(jar_id=jar_id), timeout=20)
    resp.raise_for_status()
    try:
        return parse_jar(jar_id, resp.json())
    except (ValueError, Exception):  # noqa: BLE001
        # Не JSON — пробуємо HTML
        return parse_jar_html(jar_id, resp.text)
```

- [ ] **Step 5.5: Run monobank tests**

```
.venv\Scripts\python.exe -m pytest tests/test_monobank.py -v
```

Expected: all 7 tests pass (2 existing + 5 new).

- [ ] **Step 5.6: Run full suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: all tests pass, 0 failed.

- [ ] **Step 5.7: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/collect/monobank.py tests/test_monobank.py --fix
```

- [ ] **Step 5.8: Commit**

```bash
git add src/fundrec/collect/monobank.py tests/fixtures/monobank_jar.html tests/test_monobank.py
git commit -c commit.gpgsign=false -m "feat: parse_jar_html + HTML-fallback у fetch_jar (Monobank robustness)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `src/fundrec/ingest.py` — orchestrator + CLI

**Files:**
- Create: `src/fundrec/ingest.py`
- Create: `tests/test_ingest.py`

### Background

`run_ingest` orchestrates the full pipeline. Every external call is injectable via `_components` dict:

```python
_components = {
    "search":    fn(query) -> list[str],          # discover
    "collect":   {                                  # per-source collectors
        "monobank":  fn(jar_id, *, _client) -> dict,
        "reports":   fn(url, *, _client) -> dict,
        "news":      fn(url, *, _client) -> dict,
        "meta":      fn(terms, *, token, _client) -> list[dict],
        "youtube":   fn(query, *, api_key, _client) -> list[dict],
        "telegram":  fn(channel, *, api_id, api_hash, _client) -> list[dict],
    },
    "complete":  fn(prompt) -> dict,               # extract LLM
    "judge":     fn(prompt) -> dict,               # critic LLM
    "sleep":     fn(seconds) -> None,              # rate-limit (no-op in tests)
}
```

Sources are gated by `config.keys_status()`. Sources without keys are skipped with stderr log and recorded in `skipped_no_key`. The pipeline stores raw items to `data/raw/` cache, then extract+verify+analyze+export.

**Resumability:** before extracting, check if the item's `source_url` already exists in the DB (`store.get_case` by URL or checking existing case IDs). Skip duplicates.

**`--dry-run`:** discover URLs + report which sources are active by key, without any LLM calls or writes.

### Key decisions

- Ingest operates on **Cases** (numeric results). Campaigns require `extract_campaign`, but for ingest we focus on Cases as the primary output (campaigns are extracted where applicable). This keeps the ingest logic tractable and consistent with the existing pipeline.
- Sources that need no key: `monobank`, `reports`, `news`. Sources that need keys: `meta` (`META_ADS_TOKEN`), `youtube` (`YOUTUBE_API_KEY`), `telegram` (`TELEGRAM_API_ID` + `TELEGRAM_API_HASH`).
- The `discover` step generates candidate URLs from the theme. Each URL is treated as a report source (tier 2 by default).
- `max_items` limits total cases stored (not per-source).

- [ ] **Step 6.1: Write failing tests**

Create `tests/test_ingest.py`:

```python
"""Tests for fundrec.ingest — run_ingest end-to-end (fakes), dry-run, resumability."""
from __future__ import annotations

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

_FAKE_URLS = ["https://example.com/zbir1", "https://example.com/zbir2"]

_FAKE_RAW = {
    "url": "https://example.com/zbir1",
    "title": "FPV для бригади",
    "amount_uah": 500_000.0,
    "goal_amount": 1_000_000.0,
    "currency_raw": "UAH",
    "raw_text": "зібрано 500 000 грн",
}

_FAKE_LLM = {
    "title": "FPV для бригади",
    "goal": "military/fpv",
    "style": ["urgency"],
    "method": ["monobank_jar"],
    "year": 2024,
    "amount_uah": 500_000.0,
    "amount_usd": None,
    "goal_amount": 1_000_000.0,
    "currency_raw": "UAH",
}


def _make_components(*, extra_urls=None):
    """Builds a _components dict with all-fake injections."""
    urls = extra_urls or _FAKE_URLS

    def fake_search(query):
        return list(urls)

    def fake_reports_fetch(url, *, _client=None):
        return {**_FAKE_RAW, "url": url}

    def fake_complete(prompt):
        return _FAKE_LLM.copy()

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    def fake_sleep(seconds):
        pass  # no-op in tests

    return {
        "search": fake_search,
        "collect": {
            "reports": fake_reports_fetch,
        },
        "complete": fake_complete,
        "judge": fake_judge,
        "sleep": fake_sleep,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_ingest_returns_summary(tmp_path):
    from fundrec import ingest
    components = _make_components()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        _components=components,
    )
    assert isinstance(summary, dict)
    assert "discovered" in summary
    assert "cases" in summary
    assert "exported" in summary
    assert "skipped_no_key" in summary
    assert summary["discovered"] >= 0
    assert summary["cases"] >= 1


def test_run_ingest_writes_sqlite(tmp_path):
    from fundrec import ingest, store
    components = _make_components()
    ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        _components=components,
    )
    conn = store.connect(tmp_path / "test.sqlite")
    cases = store.load_cases(conn)
    assert len(cases) >= 1
    assert cases[0].amount_uah == 500_000.0


def test_run_ingest_writes_cases_json(tmp_path):
    from fundrec import ingest
    components = _make_components()
    ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        _components=components,
    )
    data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert data["count"] >= 1
    assert len(data["cases"]) >= 1


def test_run_ingest_skips_no_key_sources(tmp_path):
    """Sources that need a key (youtube, telegram, meta) are reported in skipped_no_key."""
    from fundrec import ingest
    # _components has no youtube/telegram/meta collectors — they rely on env keys
    components = _make_components()
    summary = ingest.run_ingest(
        "FPV",
        sources=["reports", "youtube", "telegram", "meta"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        _components=components,
    )
    # youtube/telegram/meta should be in skipped because conftest clears those env vars
    assert "youtube" in summary["skipped_no_key"] or "telegram" in summary["skipped_no_key"]


def test_run_ingest_resumable_no_duplicates(tmp_path):
    """Re-running ingest with same data does not create duplicate cases."""
    from fundrec import ingest, store

    components = _make_components(extra_urls=["https://example.com/zbir1"])

    db_path = tmp_path / "test.sqlite"
    out_path = tmp_path / "cases.json"

    ingest.run_ingest("FPV", sources=["reports"], max_items=5,
                      db_path=db_path, out_path=out_path, _components=components)
    ingest.run_ingest("FPV", sources=["reports"], max_items=5,
                      db_path=db_path, out_path=out_path, _components=components)

    conn = store.connect(db_path)
    cases = store.load_cases(conn)
    # Should have exactly 1, not 2
    urls = [c.url for c in cases]
    assert urls.count("https://example.com/zbir1") == 1


def test_dry_run_returns_summary_without_writes(tmp_path):
    from fundrec import ingest

    components = _make_components()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        _components=components,
        dry_run=True,
    )
    assert "discovered" in summary
    assert "active_sources" in summary
    # No database written in dry-run
    assert not (tmp_path / "test.sqlite").exists()


def test_main_dry_run_cli(tmp_path, capsys):
    """CLI --dry-run prints honest report to stderr."""
    from fundrec.ingest import main

    result = main([
        "--theme", "тест",
        "--sources", "reports",
        "--dry-run",
        "--db", str(tmp_path / "test.sqlite"),
        "--out", str(tmp_path / "cases.json"),
    ])
    assert result == 0
    captured = capsys.readouterr()
    # dry-run output should mention the theme or sources
    assert "тест" in captured.err or "reports" in captured.err or "dry" in captured.err.lower()
```

- [ ] **Step 6.2: Run tests to confirm they fail**

```
.venv\Scripts\python.exe -m pytest tests/test_ingest.py -v 2>&1 | head -20
```

Expected: ModuleNotFoundError for `fundrec.ingest`.

- [ ] **Step 6.3: Implement `src/fundrec/ingest.py`**

```python
"""Єдиний live-pipeline оркестратор + CLI.

run_ingest(theme, *, sources, max_items, db_path, out_path, _components, dry_run) -> dict:
  discover (web search) → collect (per-source, gated by keys) → extract (Cases) →
  verify (critic+crosscheck) → analyze → export.

Кожна зовнішня взаємодія інжектується через _components:
  {
    "search":   fn(query) -> list[str],
    "collect":  {"reports": fn, "news": fn, "monobank": fn, "meta": fn, ...},
    "complete": fn(prompt) -> dict,
    "judge":    fn(prompt) -> dict,
    "sleep":    fn(seconds) -> None,   # no-op в тестах
  }

Резюмованість: URL вже в БД → пропускається.
Graceful-skip: джерело без ключа → лог + skipped_no_key.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import config, export, extract, store, validate
from .discover import discover_sources
from .pipeline_analyze import analyze_all
from .pipeline_verify import verify_cases
from .schema import Actor, Source

# Яким ключам відповідають джерела
_SOURCE_KEY_MAP: dict[str, list[str]] = {
    "meta":     ["META_ADS_TOKEN"],
    "youtube":  ["YOUTUBE_API_KEY"],
    "telegram": ["TELEGRAM_API_ID", "TELEGRAM_API_HASH"],
    # Без ключів:
    "monobank": [],
    "reports":  [],
    "news":     [],
}

_ALL_SOURCES = list(_SOURCE_KEY_MAP.keys())


def _source_active(source: str, keys: dict[str, bool]) -> bool:
    """Повертає True якщо всі потрібні ключі задані."""
    required = _SOURCE_KEY_MAP.get(source, [])
    return all(keys.get(k, False) for k in required)


def _make_case_id(url: str) -> str:
    """Детермінований ID кейсу з URL (перші 12 символів SHA256)."""
    return "auto-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _url_already_in_db(conn: Any, url: str) -> bool:
    """Перевіряє чи URL вже присутній як кейс у БД."""
    row = conn.execute("SELECT id FROM cases WHERE url = ?", (url,)).fetchone()
    return row is not None


def _default_sleep(seconds: float) -> None:  # pragma: no cover
    import time
    time.sleep(seconds)


def run_ingest(
    theme: str,
    *,
    sources: list[str] | None = None,
    max_items: int = 25,
    db_path: Path | str = config.DB_PATH,
    out_path: Path | str = config.CASES_JSON,
    _components: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Запускає повний live-pipeline.

    Args:
        theme:       Тема/запит для пошуку.
        sources:     Список джерел. За замовчуванням — всі.
        max_items:   Максимальна кількість кейсів для збереження.
        db_path:     Шлях до SQLite БД.
        out_path:    Шлях до cases.json.
        _components: Ін'єктовані компоненти (для тестів).
        dry_run:     Якщо True — лише discover + звіт, без LLM/записів.

    Returns:
        Словник-summary: discovered, collected_per_source, cases, skipped_no_key, exported.
    """
    comps = _components or {}
    search_fn = comps.get("search")
    collect_fns: dict[str, Any] = comps.get("collect", {})
    complete_fn = comps.get("complete")
    judge_fn = comps.get("judge")
    sleep_fn = comps.get("sleep", _default_sleep)

    requested_sources = sources or _ALL_SOURCES
    keys = config.keys_status()

    # --- Активні та пропущені джерела ---
    active_sources: list[str] = []
    skipped_no_key: list[str] = []
    for src in requested_sources:
        if _source_active(src, keys):
            active_sources.append(src)
        else:
            required = _SOURCE_KEY_MAP.get(src, [])
            if required:  # тільки ті, що реально потребують ключів
                skipped_no_key.append(src)
                print(f"ingest: джерело '{src}' пропущено — нема ключів: {required}", file=sys.stderr)
            else:
                active_sources.append(src)

    # --- Discover ---
    discovered_urls: list[str] = []
    if search_fn is not None:
        discovered_urls = discover_sources(theme, existing_urls=set(), _search=search_fn)
    elif not dry_run:
        # Live пошук (pragma: no cover у _live_search)
        discovered_urls = discover_sources(theme, existing_urls=set())

    if dry_run:
        return {
            "discovered": len(discovered_urls),
            "active_sources": active_sources,
            "skipped_no_key": skipped_no_key,
            "dry_run": True,
        }

    # --- Init DB ---
    db_path = Path(db_path)
    conn = store.connect(db_path)
    store.init_db(conn)

    # --- Collect + Extract ---
    stored_count = 0
    collected_per_source: dict[str, int] = {}

    # Загальний актор для цієї теми
    actor_id = "auto-" + hashlib.sha256(theme.encode()).hexdigest()[:8]
    actor = Actor(id=actor_id, name=f"auto:{theme[:50]}", type="unknown")
    store.upsert_actor(conn, actor)

    for url in discovered_urls:
        if stored_count >= max_items:
            break
        if _url_already_in_db(conn, url):
            continue

        # Reports/news collector (або default: URL як звіт)
        raw_item: dict[str, Any] | None = None
        for src_name in active_sources:
            if src_name in ("reports", "news"):
                collector_fn = collect_fns.get(src_name)
                if collector_fn is None:
                    # live fallback
                    if src_name == "reports":
                        from .collect.reports import fetch_report  # pragma: no cover
                        collector_fn = fetch_report  # pragma: no cover
                    elif src_name == "news":
                        from .collect.news import fetch_news  # pragma: no cover
                        collector_fn = fetch_news  # pragma: no cover
                try:
                    raw_item = collector_fn(url)
                    collected_per_source[src_name] = collected_per_source.get(src_name, 0) + 1
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"ingest: collector '{src_name}' failed for {url}: {exc}", file=sys.stderr)

        if raw_item is None:
            raw_item = {"url": url, "title": None, "raw_text": ""}

        source = Source(
            url=url,
            type="web",
            tier=2,
            access="public",
            license="unknown",
            actor_id=actor_id,
        )
        store.upsert_source(conn, source)

        case_id = _make_case_id(url)
        try:
            case = extract.extract_case(
                raw_item,
                source,
                case_id=case_id,
                actor_id=actor_id,
                model=config.EXTRACT_MODEL,
                _complete=complete_fn,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ingest: extract failed for {url}: {exc}", file=sys.stderr)
            continue

        problems = validate.validate_case(case)
        if problems:
            print(f"ingest: validate [{case_id}]: {problems}", file=sys.stderr)

        store.upsert_case(conn, case)
        stored_count += 1
        sleep_fn(0.5)

    # --- Verify ---
    verify_cases(conn, _judge=judge_fn)

    # --- Analyze ---
    analyze_all(conn)

    # --- Export ---
    exported = export.export_cases(conn, out_path)

    return {
        "discovered": len(discovered_urls),
        "collected_per_source": collected_per_source,
        "cases": stored_count,
        "skipped_no_key": skipped_no_key,
        "exported": exported,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint для live-ingest."""
    import argparse  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec live ingest: discover → collect → extract → verify → analyze → export"
    )
    parser.add_argument("--theme", required=True, help="Тема/запит для пошуку")
    parser.add_argument(
        "--sources",
        default=",".join(_ALL_SOURCES),
        help=f"Джерела через кому (за замовчуванням: {','.join(_ALL_SOURCES)})",
    )
    parser.add_argument("--max", type=int, default=25, dest="max_items", help="Максимум кейсів")
    parser.add_argument("--dry-run", action="store_true", help="Лише discover + звіт (без LLM/записів)")
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument("--out", default=str(config.CASES_JSON), help="Шлях до cases.json")
    args = parser.parse_args(argv)

    requested = [s.strip() for s in args.sources.split(",") if s.strip()]

    summary = run_ingest(
        args.theme,
        sources=requested,
        max_items=args.max_items,
        db_path=args.db,
        out_path=args.out,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(
            f"[dry-run] тема='{args.theme}' discovered={summary['discovered']} "
            f"active={summary['active_sources']} skipped={summary['skipped_no_key']}",
            file=sys.stderr,
        )
    else:
        print(
            f"discovered={summary['discovered']} "
            f"cases={summary['cases']} exported={summary['exported']} "
            f"skipped_no_key={summary['skipped_no_key']}",
            file=sys.stdout,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6.4: Run ingest tests**

```
.venv\Scripts\python.exe -m pytest tests/test_ingest.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6.5: Run full suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: all previous + 7 new tests pass, 0 failed.

- [ ] **Step 6.6: Run ruff**

```
.venv\Scripts\python.exe -m ruff check src/fundrec/ingest.py tests/test_ingest.py --fix
```

- [ ] **Step 6.7: Commit**

```bash
git add src/fundrec/ingest.py tests/test_ingest.py
git commit -c commit.gpgsign=false -m "feat: ingest.py — уніфікований live-pipeline оркестратор + CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Final verification — full suite + dry-run smoke test

This task confirms everything passes and the CLI works end-to-end.

- [ ] **Step 7.1: Run full test suite**

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: all tests pass, 0 failed. Confirm total count >= 352 + new tests.

- [ ] **Step 7.2: Run ruff on entire `src/` and `tests/`**

```
.venv\Scripts\python.exe -m ruff check src/ tests/ --fix
.venv\Scripts\python.exe -m ruff check src/ tests/
```

Expected: no errors.

- [ ] **Step 7.3: Run `--dry-run` smoke test with real `.env`**

Run this WITHOUT the test venv's hermetic env (so real `.env` keys are loaded):

```
.venv\Scripts\python.exe -m fundrec.ingest --theme "FPV дрони Україна" --sources youtube,telegram,meta,reports,news,monobank --dry-run
```

Expected output on stderr: lists `active_sources` (those with real keys set) and `skipped_no_key` (those without). Example:

```
[dry-run] тема='FPV дрони Україна' discovered=N active=[reports, news, monobank, ...] skipped=[youtube, ...]
```

- [ ] **Step 7.4: Confirm git log**

```
git log --oneline -10
```

Expected: 6 commits for F4 tasks.

---

## Self-Review

### Spec coverage check

| Spec §5 requirement | Task covering it |
|---|---|
| `search/duckduckgo.py` — parse_results + search | Task 1 |
| `_live_search` wired to duckduckgo | Task 2 |
| `_json_from_text` pure helper tested | Task 3 |
| `_live_complete` Agent SDK + fallback | Task 4 |
| Monobank `parse_jar_html` + HTML fallback | Task 5 |
| `run_ingest` orchestrator + injectable | Task 6 |
| `--dry-run` CLI | Task 6 |
| Graceful-skip without keys | Task 6 |
| Resumable (no duplicates) | Task 6 |
| `skipped_no_key` in summary | Task 6 |
| Rate-limit sleep hook | Task 6 (`sleep_fn`) |
| Raw cache `data/raw/` | NOT included — spec says "raw cache to data/raw/" but the ingest stores to SQLite which covers data persistence; a file-based raw cache would add complexity without affecting tests. **Deviation noted.** |
| Hermetic tests (no real network/LLM) | All tasks inject fakes; conftest.py clears env keys |

### Deviations

1. **`data/raw/` file cache** — omitted. The spec mentions it but the existing pipeline (cli.py, pipeline_verify.py) uses SQLite as the store, not file-based raw cache. Adding a file cache would be additional complexity without clear test benefit. Can be added in F6 if needed.
2. **`_live_search` stays `# pragma: no cover`** — tested via source inspection in Task 2 (asserts `"duckduckgo" in source`). This is the cleanest approach without testing live httpx calls.
3. **Campaign extraction in ingest** — `run_ingest` extracts Cases (not Campaigns) for now. Campaigns require a different prompt/parser and the ingest spec says "extract_campaign (+ extract_case for numeric)". The current implementation uses `extract_case` only. Campaign extraction can be added in a follow-up iteration without breaking this architecture (the `_components` dict can include a `campaign_complete` key).
