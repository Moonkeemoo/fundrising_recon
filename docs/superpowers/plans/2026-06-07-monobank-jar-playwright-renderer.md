# Monobank Jar Playwright Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Playwright-based headless renderer to parse real Monobank jar amounts from JS-rendered pages, wire it into ingest as the default tier-1 jar fetcher, and mark jar-backed campaigns as "verified".

**Architecture:** Three units — (1) a pure `parse_rendered_jar` function in `jars.py` that extracts title/amounts from body text, (2) a new `src/fundrec/collect/jar_render.py` module with injectable `_render` for tests, cache backed by `data/jars_cache.json`, and live Playwright path under `# pragma: no cover`, (3) `ingest.py` switches default jar fetcher to `render_jar_cached` and sets `verification_status="verified"` when tier-1 jar amount is applied.

**Tech Stack:** Python 3.12, pytest, Playwright (sync API), ruff, existing `fundrec` conventions (Ukrainian docstrings, `from __future__ import annotations`, injectable deps).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/fundrec/jars.py` | Add `parse_rendered_jar(jar_id, body_text) -> dict` |
| Create | `src/fundrec/collect/jar_render.py` | `render_jar`, `_live_render`, `render_jar_cached` |
| Modify | `src/fundrec/config.py` | Add `JARS_CACHE_PATH = DATA_DIR / "jars_cache.json"` |
| Modify | `src/fundrec/ingest.py` | Switch default jar fetcher; set `verification_status="verified"` |
| Modify | `pyproject.toml` | Add `playwright` to `[project.optional-dependencies] live` |
| Modify | `tests/test_jars.py` | Add `parse_rendered_jar` tests |
| Create | `tests/test_jar_render.py` | Tests for `render_jar` and `render_jar_cached` |
| Modify | `tests/test_ingest_jars.py` | Update to inject `_render` and assert `verification_status=="verified"` |

---

## Task 1 — Pure parser `parse_rendered_jar` in `jars.py`

**Files:**
- Modify: `src/fundrec/jars.py`
- Test: `tests/test_jars.py`

### Step 1.1 — Write the failing tests

- [ ] Open `tests/test_jars.py` and add the following tests at the end of the file:

```python
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
```

- [ ] Run tests to confirm they fail:

```
.venv\Scripts\python.exe -m pytest tests/test_jars.py::test_parse_rendered_jar_amounts_full -v
```

Expected: `FAILED` — `ImportError` or `AttributeError` since `parse_rendered_jar` does not exist yet.

### Step 1.2 — Implement `parse_rendered_jar` in `jars.py`

- [ ] Open `src/fundrec/jars.py` and add the following after the existing imports and before `extract_jar_ids`. Add the boilerplate pattern constant and the new function at the end of the file (after `fetch_jar_data`):

```python
# Regex для ₴-суми у тексті body після JS-рендеру.
# Захоплює числа з пробілами/nbsp як роздільниками тисяч + ./, десятковий.
_RENDERED_AMOUNT_PAT = re.compile(
    r"([\d][\d\s\xa0]*(?:[.,]\d+)?)\s*₴",
)

# Рядки-шум які ігноруємо при пошуку title
_BOILERPLATE_PAT = re.compile(
    r"minimum amount|maximum amount|\+\d+\s*₴|monobank",
    re.IGNORECASE,
)


def _parse_rendered_amount(raw: str) -> float | None:
    """Очищає рядок суми (nbsp, пробіли → пусто; кома→крапка) → float."""
    cleaned = re.sub(r"[\s\xa0]", "", raw).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_rendered_jar(jar_id: str, body_text: str) -> dict[str, Any]:
    """Парсить inner_text body після JS-рендеру сторінки банки Monobank.

    Правило:
    - Перша «…\xa0₴» або «… ₴» сума = зібрано (amount_uah).
    - Друга — ціль (goal_amount).
    - Title = перший непорожній рядок, що не є сумою і не є boilerplate.

    Повертає:
        {jar_id, url, title, amount_uah, goal_amount}
    Honest null: відсутні поля = None.
    """
    amounts: list[float] = []
    title: str | None = None

    for line in body_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Перевіряємо чи рядок містить ₴-суму
        m = _RENDERED_AMOUNT_PAT.search(stripped)
        if m:
            val = _parse_rendered_amount(m.group(1))
            if val is not None and val >= 0:
                amounts.append(val)
            continue  # рядок з сумою — не title

        # Ігноруємо boilerplate
        if _BOILERPLATE_PAT.search(stripped):
            continue

        # Перший залишений рядок = title
        if title is None:
            title = stripped

    amount_uah = amounts[0] if len(amounts) >= 1 else None
    goal_amount = amounts[1] if len(amounts) >= 2 else None

    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": title,
        "amount_uah": amount_uah,
        "goal_amount": goal_amount,
    }
```

### Step 1.3 — Run new tests (should pass)

- [ ] Run:

```
.venv\Scripts\python.exe -m pytest tests/test_jars.py -v
```

Expected: all tests in `test_jars.py` pass (existing + new 8 tests).

### Step 1.4 — Run full suite, fix ruff

- [ ] Run full suite:

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: ≥ 530 passed, 0 failed.

- [ ] Run ruff check and fix:

```
.venv\Scripts\python.exe -m ruff check src/fundrec/jars.py tests/test_jars.py --fix
.venv\Scripts\python.exe -m ruff format src/fundrec/jars.py tests/test_jars.py
```

Expected: no errors.

### Step 1.5 — Commit

- [ ] Stage and commit:

```bash
git add src/fundrec/jars.py tests/test_jars.py
git commit -m "$(cat <<'EOF'
feat: додати parse_rendered_jar — парсинг body_text після JS-рендеру банки

Перша ₴-сума = зібрано, друга = ціль. Robust parser: nbsp/пробіли як
роздільники тисяч, кома/крапка десятковий. Honest null для відсутніх полів.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Renderer module `src/fundrec/collect/jar_render.py`

**Files:**
- Modify: `src/fundrec/config.py`
- Create: `src/fundrec/collect/jar_render.py`
- Create: `tests/test_jar_render.py`
- Modify: `pyproject.toml`

### Step 2.1 — Add `JARS_CACHE_PATH` to `config.py`

- [ ] Open `src/fundrec/config.py`. After the line `CASES_JSON = DATA_DIR / "cases.json"`, add:

```python
JARS_CACHE_PATH = DATA_DIR / "jars_cache.json"
```

### Step 2.2 — Write failing tests for `jar_render`

- [ ] Create `tests/test_jar_render.py` with the following content:

```python
"""Тести fundrec.collect.jar_render — render_jar, render_jar_cached."""
from __future__ import annotations

import json

import pytest


_FIXTURE_BODY = """\
Постійна банка для закупівлі FPV. Наша мета — купувати мінімум 300 дронів
2 000 837.29 ₴
10 000 000 ₴
Minimum amount: 10 ₴. Maximum amount: 29 999 ₴
"""

_JAR_ID = "RENDERTEST1"


# ---------------------------------------------------------------------------
# render_jar — з ін'єктованим _render
# ---------------------------------------------------------------------------


def test_render_jar_parses_fixture():
    """render_jar з ін'єктованим _render повертає dict із правильними сумами."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: _FIXTURE_BODY)

    assert result is not None
    assert result["jar_id"] == _JAR_ID
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)
    assert result["title"] is not None
    assert result["title"].startswith("Постійна банка")


def test_render_jar_returns_none_when_render_fails():
    """render_jar повертає None якщо _render повертає None."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: None)
    assert result is None


def test_render_jar_returns_none_on_empty_body():
    """render_jar повертає None якщо _render повертає порожній рядок."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: "")
    assert result is None


def test_render_jar_url_correct():
    """URL у результаті вказує на правильний jar."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: _FIXTURE_BODY)
    assert result is not None
    assert result["url"] == f"https://send.monobank.ua/jar/{_JAR_ID}"


# ---------------------------------------------------------------------------
# render_jar_cached — cache hit / miss
# ---------------------------------------------------------------------------


def test_render_jar_cached_miss_then_hit(tmp_path):
    """Перший виклик: cache miss → _render викликається; другий: hit → _render НЕ викликається."""
    from fundrec.collect.jar_render import render_jar_cached

    call_count = {"n": 0}

    def counting_render(jar_id):
        call_count["n"] += 1
        return _FIXTURE_BODY

    cache_file = tmp_path / "jars_cache.json"

    # Miss
    result1 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render)
    assert result1 is not None
    assert call_count["n"] == 1

    # Hit
    result2 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render)
    assert result2 is not None
    assert call_count["n"] == 1  # НЕ збільшився


def test_render_jar_cached_persists_to_json(tmp_path):
    """Після cache miss результат зберігається у JSON-файлі."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert _JAR_ID in data
    assert data[_JAR_ID]["amount_uah"] == pytest.approx(2_000_837.29)


def test_render_jar_cached_none_not_stored(tmp_path):
    """Якщо render повертає None — нічого не зберігається у кеш."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: None)

    assert result is None
    # Файл або не існує, або не містить jar_id
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert _JAR_ID not in data


def test_render_jar_cached_returns_correct_amounts(tmp_path):
    """Кешована відповідь містить правильні суми."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY)

    assert result is not None
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)
```

- [ ] Run tests to confirm they fail:

```
.venv\Scripts\python.exe -m pytest tests/test_jar_render.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'fundrec.collect.jar_render'`.

### Step 2.3 — Implement `src/fundrec/collect/jar_render.py`

- [ ] Create `src/fundrec/collect/jar_render.py` with the following content:

```python
"""Playwright-рендер сторінки банки Monobank і кеш результатів.

render_jar(jar_id, *, _render=None, timeout=30000) -> dict | None
    Якщо _render задано (тести) — використовує його замість браузера.
    Інакше — _live_render (Playwright, # pragma: no cover).

render_jar_cached(jar_id, *, cache_path, _render=None) -> dict | None
    Читає JSON-кеш {jar_id: data}; при miss — render_jar, потім зберігає.

_live_render(jar_id, timeout) -> str | None  # pragma: no cover
    Запускає Playwright chromium headless, goto + networkidle + 2.5 s wait,
    повертає page.inner_text("body"). При будь-якій помилці → None.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..jars import JAR_URL, parse_rendered_jar


def _live_render(jar_id: str, timeout: int) -> str | None:  # pragma: no cover
    """Запускає headless Chromium і повертає inner_text("body") сторінки банки."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return None

    url = JAR_URL.format(jar_id=jar_id)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout)
                page.wait_for_timeout(2500)
                return page.inner_text("body")
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        return None


def render_jar(
    jar_id: str,
    *,
    _render: Callable[[str], str | None] | None = None,
    timeout: int = 30000,
) -> dict[str, Any] | None:
    """Рендерить сторінку банки і парсить результат.

    _render: ін'єктований виклик в тестах (jar_id -> body_text | None).
    Якщо не задано — використовується _live_render (Playwright).
    Повертає None якщо рендер не вдався або тіло порожнє.
    """
    if _render is not None:
        body = _render(jar_id)
    else:
        body = _live_render(jar_id, timeout)  # pragma: no cover

    if not body:
        return None

    return parse_rendered_jar(jar_id, body)


def render_jar_cached(
    jar_id: str,
    *,
    cache_path: Path | str = config.JARS_CACHE_PATH,
    _render: Callable[[str], str | None] | None = None,
    timeout: int = 30000,
) -> dict[str, Any] | None:
    """Повертає кешовані дані банки або рендерить і кешує.

    Кеш: JSON-файл {jar_id: {jar_id, url, title, amount_uah, goal_amount}}.
    Якщо рендер повернув None — кеш НЕ оновлюється.
    """
    cache_path = Path(cache_path)

    # Читаємо кеш
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    # Cache hit
    if jar_id in cache:
        return cache[jar_id]

    # Cache miss → рендер
    result = render_jar(jar_id, _render=_render, timeout=timeout)
    if result is None:
        return None

    # Зберігаємо
    cache[jar_id] = result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
```

### Step 2.4 — Add `playwright` to `pyproject.toml`

- [ ] Open `pyproject.toml`. Find the `[project.optional-dependencies]` section and update the `live` line:

```toml
[project.optional-dependencies]
live = ["claude-agent-sdk>=0.1", "anthropic>=0.40", "playwright>=1.40"]
```

### Step 2.5 — Run new tests (should pass)

- [ ] Run:

```
.venv\Scripts\python.exe -m pytest tests/test_jar_render.py -v
```

Expected: all 8 tests pass.

### Step 2.6 — Run full suite, fix ruff

- [ ] Run:

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: ≥ 538 passed, 0 failed.

- [ ] Run ruff:

```
.venv\Scripts\python.exe -m ruff check src/fundrec/config.py src/fundrec/collect/jar_render.py tests/test_jar_render.py --fix
.venv\Scripts\python.exe -m ruff format src/fundrec/config.py src/fundrec/collect/jar_render.py tests/test_jar_render.py
```

### Step 2.7 — Commit

- [ ] Stage and commit:

```bash
git add src/fundrec/config.py src/fundrec/collect/jar_render.py tests/test_jar_render.py pyproject.toml
git commit -m "$(cat <<'EOF'
feat: додати jar_render.py — Playwright-рендер банки з JSON-кешем

render_jar (ін'єктований _render в тестах, _live_render # pragma: no cover),
render_jar_cached (JSON-кеш; miss → render → persist). playwright у [live] deps.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Wire into ingest: tier-1 + `verification_status="verified"`

**Files:**
- Modify: `src/fundrec/ingest.py`
- Modify: `tests/test_ingest_jars.py`

### Step 3.1 — Write failing tests in `test_ingest_jars.py`

- [ ] Open `tests/test_ingest_jars.py`. The existing tests inject `fake_jar_fetch(jar_id, *, _client=None)` via `_components["collect"]["jar"]`. We need to:
  1. Add a test asserting `verification_status == "verified"` when jar amount is applied.
  2. Add a test asserting `goal_amount` is set on campaign when jar data has it.
  3. Update the `_make_jar_ingest_components` helper so `jar` key uses a `_render`-accepting signature to match `render_jar_cached`.

  The existing `fake_jar_fetch` already matches the calling convention in `_ingest_one` (`jar_fetch_fn(found_jar_ids[0])`) — no signature change needed since `render_jar_cached` is called as `render_jar_cached(jar_id)` (all other args are keyword-only defaults). **Do not modify existing tests** — only add new tests below the existing ones.

  Append to `tests/test_ingest_jars.py`:

```python
# ---------------------------------------------------------------------------
# Тест 5: verification_status == "verified" коли jar amount застосовано
# ---------------------------------------------------------------------------


def test_jar_amount_sets_verified_status(tmp_path):
    """Якщо jar amount застосовано (tier-1) → campaign.verification_status == 'verified'."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    camp = campaigns[0]
    assert camp.verification_status == "verified"


def test_jar_no_data_not_verified(tmp_path):
    """Якщо jar fetcher повернув None → verification_status НЕ 'verified' (залишається 'auto')."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=None,
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    # Без jar amount — статус НЕ 'verified' (буде 'auto' або 'cross-checked' після критика)
    assert campaigns[0].verification_status != "verified"


def test_jar_goal_amount_stored_on_campaign(tmp_path):
    """goal_amount з jar даних зберігається на campaign."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,  # goal_amount=500_000.0
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    assert campaigns[0].goal_amount == pytest.approx(500_000.0)
```

- [ ] Import `pytest` at the top of the test file if not already imported. Check line 1–10 of `tests/test_ingest_jars.py` — if there's no `import pytest`, add `import pytest` after the `from __future__ import annotations` line.

- [ ] Run to confirm new tests fail:

```
.venv\Scripts\python.exe -m pytest tests/test_ingest_jars.py::test_jar_amount_sets_verified_status tests/test_ingest_jars.py::test_jar_goal_amount_stored_on_campaign -v
```

Expected: FAILED.

### Step 3.2 — Update `ingest.py`: default jar fetcher + `goal_amount` + `verified` status

- [ ] Open `src/fundrec/ingest.py`. Make **three changes**:

**Change A — switch default jar fetcher** (around line 358):

Replace:
```python
    jar_fetch_fn: Any = collect_fns.get("jar") or jars.fetch_jar_data
```
With:
```python
    jar_fetch_fn: Any = collect_fns.get("jar") or _default_jar_fetch_fn()
```

And add this helper function near the other `_get_default_*` helpers (after `_get_default_search_collector`):

```python
def _default_jar_fetch_fn() -> Any:
    """Повертає live jar fetcher: render_jar_cached якщо playwright доступний,
    інакше — fetch_jar_data (HTTP fallback)."""
    try:
        from .collect.jar_render import render_jar_cached  # noqa: PLC0415
        return render_jar_cached
    except ImportError:  # pragma: no cover
        return jars.fetch_jar_data
```

**Change B — apply `goal_amount` on campaign** in `_apply_jar_to_campaign`:

Replace the existing `_apply_jar_to_campaign` function:

```python
def _apply_jar_to_campaign(campaign: Any, jar_data: dict[str, Any]) -> None:
    """Перезаписує campaign.amount_uah значенням банки і ставить tier-1 provenance.
    Також встановлює goal_amount якщо присутнє у jar_data."""
    amount = jar_data.get("amount_uah")
    if amount is None:
        return
    campaign.amount_uah = amount
    campaign.provenance["amount_uah"] = {
        "source_url": jar_data["url"],
        "confidence": _TIER1_CONFIDENCE,
        "tier": 1,
        "note": "monobank jar tier-1",
    }
    goal = jar_data.get("goal_amount")
    if goal is not None:
        campaign.goal_amount = goal
```

**Change C — set `verification_status="verified"` after jar amount applied** in `_ingest_one`:

Find the block in `_ingest_one` that applies jar data to campaign (around line 282–284):

```python
    if jar_data is not None:
        _apply_jar_to_campaign(campaign, jar_data)
```

Replace with:

```python
    jar_applied = False
    if jar_data is not None:
        _apply_jar_to_campaign(campaign, jar_data)
        if jar_data.get("amount_uah") is not None:
            jar_applied = True
```

Then, after `store.upsert_campaign(conn, campaign)` and before the case extraction block, add:

```python
    # Tier-1 jar amount = публічне перевірене джерело → статус "verified"
    if jar_applied:
        store.set_campaign_verification(conn, campaign_id, "verified", reason="monobank jar tier-1")
```

### Step 3.3 — Run new ingest tests (should pass)

- [ ] Run:

```
.venv\Scripts\python.exe -m pytest tests/test_ingest_jars.py -v
```

Expected: all tests pass (existing 8 + new 3 = 11 total).

### Step 3.4 — Run full suite, fix ruff

- [ ] Run:

```
.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: ≥ 541 passed, 0 failed.

- [ ] Run ruff:

```
.venv\Scripts\python.exe -m ruff check src/fundrec/ingest.py tests/test_ingest_jars.py --fix
.venv\Scripts\python.exe -m ruff format src/fundrec/ingest.py tests/test_ingest_jars.py
```

Expected: no errors.

### Step 3.5 — Commit

- [ ] Stage and commit:

```bash
git add src/fundrec/ingest.py tests/test_ingest_jars.py
git commit -m "$(cat <<'EOF'
feat: підключити render_jar_cached як дефолтний jar fetcher, verification_status=verified

Tier-1 jar amount → goal_amount на campaign + verification_status='verified' одразу в
_ingest_one. Дефолтний fetcher: render_jar_cached (Playwright), fallback fetch_jar_data.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist

### Spec Coverage

| Requirement | Task |
|-------------|------|
| `parse_rendered_jar` in `jars.py` | Task 1 |
| Return `{jar_id, url, title, amount_uah, goal_amount}` | Task 1 |
| Robust amount parser: regex, spaces/nbsp, comma→dot | Task 1 Step 1.2 |
| Title = first non-empty non-amount non-boilerplate line | Task 1 Step 1.2 |
| Tests: fixture → assert amounts+title; no-goal → None; garbage → all None | Task 1 Step 1.1 |
| `render_jar(jar_id, *, _render, timeout)` | Task 2 Step 2.3 |
| `_live_render` with `# pragma: no cover`, lazy playwright import | Task 2 Step 2.3 |
| Cache: `render_jar_cached` with `cache_path=config.JARS_CACHE_PATH` | Task 2 Step 2.3 |
| Cache hit → no second render call | Task 2 Step 2.2 `test_render_jar_cached_miss_then_hit` |
| `playwright` in `[project.optional-dependencies] live` | Task 2 Step 2.4 |
| Default jar fetcher = `render_jar_cached` | Task 3 Step 3.2 Change A |
| `goal_amount` applied to campaign from jar data | Task 3 Step 3.2 Change B |
| `verification_status="verified"` when jar amount applied | Task 3 Step 3.2 Change C |
| Tests inject `_render`; never launch real browser | All tasks — `_render` always injected |
| Hermetic (no real network/browser in tests) | All tasks |
| Commit per unit | Tasks 1/2/3 each commit |
| `JARS_CACHE_PATH` in `config.py` | Task 2 Step 2.1 |

### Placeholder Scan

No TBDs, TODOs, or "similar to" references. All code shown in full.

### Type Consistency

- `parse_rendered_jar(jar_id: str, body_text: str) -> dict` — used consistently in `jar_render.py` as `parse_rendered_jar(jar_id, body)`.
- `render_jar(jar_id, *, _render, timeout) -> dict | None` — `_render: Callable[[str], str | None] | None`.
- `render_jar_cached(jar_id, *, cache_path, _render, timeout) -> dict | None` — same `_render` signature flows through to `render_jar`.
- `_apply_jar_to_campaign` takes `campaign: Any` (matches existing `ingest.py` convention) and `jar_data: dict[str, Any]`.
- `store.set_campaign_verification(conn, campaign_id, status, reason=...)` — already used in `_verify_campaigns`; same call site pattern.
