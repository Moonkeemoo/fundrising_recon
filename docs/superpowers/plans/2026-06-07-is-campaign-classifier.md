# is_campaign Non-Destructive Relevance Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-destructive `is_campaign` flag to every Campaign that classifies it as a fundraising appeal (True) or topical/educational content (False/None-unknown), with the dashboard hiding explicit-false by default.

**Architecture:** Two-stage classification — deterministic keyword gate (`is_fundraising`) fires first for clear signals; ambiguous cases go to an injected LLM judge returning `{"is_campaign": bool}`. The flag is stored in SQLite as INTEGER NULL (mirrors `goal_reached` pattern). Dashboard default hides `is_campaign === false`; null stays visible with a `?` badge.

**Tech Stack:** Python 3.11, SQLite, `src/fundrec/` package, vanilla JS in `web/index.html`, pytest, ruff.

---

## File Map

| File | Change |
|---|---|
| `src/fundrec/schema.py` | Add `is_campaign: bool \| None = None` field to `Campaign` dataclass |
| `src/fundrec/db/schema.sql` | Add `is_campaign INTEGER` column to `campaigns` table |
| `src/fundrec/store.py` | `_row_to_campaign` conversion + `set_campaign_relevance()` |
| `src/fundrec/relevance.py` | `build_relevance_prompt`, `parse_relevance_verdict`, `classify_campaign`, `classify_relevance_db`, `_live_judge_relevance`, updated CLI |
| `src/fundrec/export.py` | Verify `is_campaign` included in campaign dicts (auto via `campaign_to_dict`) |
| `web/index.html` | `filteredCamps()` default filter, toggle UI, `?` badge on null |
| `tests/test_is_campaign_unit1.py` | NEW: schema field round-trip + `set_campaign_relevance` |
| `tests/test_is_campaign_unit2.py` | NEW: classifier functions |
| `tests/test_is_campaign_unit3.py` | NEW: DB classify pass + CLI |
| `tests/test_is_campaign_unit4.py` | NEW: export serialization |

---

## Task 1: Schema field `is_campaign` in `Campaign` dataclass

**Files:**
- Modify: `src/fundrec/schema.py` — add `is_campaign: bool | None = None` after `goal_reached`
- Test: `tests/test_is_campaign_unit1.py`

Context: `goal_reached: bool | None = None` is currently at line 196. Add `is_campaign` directly after it. `campaign_to_dict` uses `asdict(c)` so it will auto-include the new field.

- [ ] **Step 1: Write failing tests**

Create `tests/test_is_campaign_unit1.py`:

```python
"""Unit 1 — is_campaign: поле схеми, round-trip store, set_campaign_relevance.

TDD: тести написані ДО реалізації.
"""
from __future__ import annotations

import pytest
from fundrec.schema import Campaign


def _base_campaign(**kw) -> Campaign:
    defaults = dict(
        id="c1", actor_id="a1", title="тест", goal="military", type="mixed",
    )
    defaults.update(kw)
    return Campaign(**defaults)


# ---------------------------------------------------------------------------
# Schema: is_campaign field exists with default None
# ---------------------------------------------------------------------------

def test_campaign_has_is_campaign_field():
    c = _base_campaign()
    assert hasattr(c, "is_campaign")
    assert c.is_campaign is None


def test_campaign_is_campaign_true():
    c = _base_campaign(is_campaign=True)
    assert c.is_campaign is True


def test_campaign_is_campaign_false():
    c = _base_campaign(is_campaign=False)
    assert c.is_campaign is False


# ---------------------------------------------------------------------------
# store round-trip: bool/None ↔ INTEGER/NULL
# ---------------------------------------------------------------------------

def _seed(conn):
    from fundrec import store
    from fundrec.schema import Actor
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))


def test_store_roundtrip_is_campaign_true(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=True)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_store_roundtrip_is_campaign_false(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=False)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


def test_store_roundtrip_is_campaign_none(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is None


# ---------------------------------------------------------------------------
# set_campaign_relevance: UPDATE the column
# ---------------------------------------------------------------------------

def test_set_campaign_relevance_sets_true(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", True)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_set_campaign_relevance_sets_false(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", False)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


def test_set_campaign_relevance_overwrites(tmp_path):
    """set_campaign_relevance can flip True → False."""
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=True)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", False)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False
```

- [ ] **Step 2: Run to confirm all 8 tests fail**

```
cd C:/Users/tomoo/Documents/GitHub/fundrising_recon
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit1.py -v --tb=short
```

Expected: 8 FAILED (AttributeError or similar — field doesn't exist yet)

- [ ] **Step 3: Add `is_campaign` field to `Campaign` dataclass in `schema.py`**

In `src/fundrec/schema.py`, after line 196 (`goal_reached: bool | None = None`):

```python
    # прапор релевантності
    is_campaign: bool | None = None
```

- [ ] **Step 4: Add `is_campaign INTEGER` column to `db/schema.sql`**

In `src/fundrec/db/schema.sql`, after `goal_reached INTEGER,` (currently line 70):

```sql
    is_campaign         INTEGER,
```

- [ ] **Step 5: Update `_row_to_campaign` in `store.py` to convert NULL/0/1 → None/False/True**

In `src/fundrec/store.py`, after the `goal_reached` conversion block (currently lines 140–144):

```python
    # INTEGER NULL → bool | None for is_campaign
    ic = data.get("is_campaign")
    if ic is None:
        data["is_campaign"] = None
    else:
        data["is_campaign"] = bool(ic)
```

- [ ] **Step 6: Add `set_campaign_relevance` to `store.py`**

After `set_campaign_verification` (end of `store.py`):

```python
def set_campaign_relevance(
    conn: sqlite3.Connection,
    campaign_id: str,
    is_campaign: bool,
) -> None:
    """Встановлює прапор релевантності кампанії (чи це збір).

    Аналог set_campaign_verification — точкове UPDATE однієї колонки.
    """
    conn.execute(
        "UPDATE campaigns SET is_campaign = ? WHERE id = ?",
        (int(is_campaign), campaign_id),
    )
    conn.commit()
```

- [ ] **Step 7: Run unit 1 tests — expect all 8 PASS**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit1.py -v
```

Expected: 8 passed

- [ ] **Step 8: Run full suite — no regressions**

```
.venv/Scripts/python.exe -m pytest -q --tb=short
```

Expected: 762+8 = 770 passed (ignore known flaky `test_check_keys_cli_runs`)

- [ ] **Step 9: Run ruff**

```
.venv/Scripts/python.exe -m ruff check src/fundrec/schema.py src/fundrec/store.py src/fundrec/db/schema.sql
```

Expected: no errors (schema.sql is not Python — ruff will skip it gracefully)

- [ ] **Step 10: Commit**

```bash
git add src/fundrec/schema.py src/fundrec/store.py src/fundrec/db/schema.sql tests/test_is_campaign_unit1.py
git commit -m "$(cat <<'EOF'
feat: додати поле is_campaign до Campaign + store round-trip

- Campaign.is_campaign: bool | None = None (після goal_reached)
- db/schema.sql: is_campaign INTEGER (campaigns)
- _row_to_campaign: NULL/0/1 → None/False/True
- store.set_campaign_relevance(conn, id, bool) — точкове UPDATE
- тести: round-trip True/False/None + set_campaign_relevance

NOTE: реальна БД потребує міграції:
  ALTER TABLE campaigns ADD COLUMN is_campaign INTEGER;

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Classifier functions in `relevance.py`

**Files:**
- Modify: `src/fundrec/relevance.py`
- Test: `tests/test_is_campaign_unit2.py`

Context: `is_fundraising(raw)` already lives in `relevance.py`. `claude_cli` lives in `extract.py`. The new functions belong in `relevance.py` to keep classification logic co-located.

- [ ] **Step 1: Write failing tests**

Create `tests/test_is_campaign_unit2.py`:

```python
"""Unit 2 — classify_campaign: двоетапний класифікатор релевантності.

TDD: тести написані ДО реалізації. Жодного реального LLM — judge ін'єктується.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# build_relevance_prompt
# ---------------------------------------------------------------------------

def test_build_relevance_prompt_contains_title_and_text():
    from fundrec.relevance import build_relevance_prompt
    prompt = build_relevance_prompt("Збір на дрони", "Допоможіть нам зібрати кошти")
    assert "Збір на дрони" in prompt
    assert "Допоможіть нам зібрати кошти" in prompt


def test_build_relevance_prompt_requests_json():
    from fundrec.relevance import build_relevance_prompt
    prompt = build_relevance_prompt("test", "text")
    # Повинен містити інструкцію повернути JSON з is_campaign
    assert "is_campaign" in prompt
    assert "true" in prompt.lower() or "false" in prompt.lower()


def test_build_relevance_prompt_truncates_long_text():
    from fundrec.relevance import build_relevance_prompt
    long_text = "x" * 2000
    prompt = build_relevance_prompt("title", long_text)
    # Текст усічений до ~800 символів
    assert len(prompt) < 2500  # prompt сам по собі не надто довгий


# ---------------------------------------------------------------------------
# parse_relevance_verdict
# ---------------------------------------------------------------------------

def test_parse_relevance_verdict_true():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": True}) is True


def test_parse_relevance_verdict_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": False}) is False


def test_parse_relevance_verdict_missing_key_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({}) is False


def test_parse_relevance_verdict_garbage_value_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": "yes"}) is False


def test_parse_relevance_verdict_null_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": None}) is False


# ---------------------------------------------------------------------------
# classify_campaign: deterministic path
# ---------------------------------------------------------------------------

def _jar_raw():
    return {
        "title": "Збір на дрони",
        "text": "Банка: send.monobank.ua/jar/ABC123",
    }


def _topical_raw():
    return {
        "title": "Навчальний відео TCCC",
        "text": "Огляд тактичної аптечки для бійців. Стандарт MARCH.",
    }


def test_classify_campaign_is_fundraising_true_skips_judge():
    """Якщо is_fundraising(raw) → True, judge НЕ викликається, повертає True."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    judge_called = {"n": 0}

    def judge(prompt):
        judge_called["n"] += 1
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="Збір", goal="military", type="mixed")
    result = classify_campaign(c, _jar_raw(), judge=judge)
    assert result is True
    assert judge_called["n"] == 0, "judge не повинен викликатись для is_fundraising=True"


def test_classify_campaign_ambiguous_judge_returns_false():
    """Топічний raw → judge False → classify повертає False."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    def judge(prompt):
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="TCCC відео", goal="military", type="mixed")
    result = classify_campaign(c, _topical_raw(), judge=judge)
    assert result is False


def test_classify_campaign_ambiguous_judge_returns_true():
    """Топічний raw → judge True → classify повертає True."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    def judge(prompt):
        return {"is_campaign": True}

    c = Campaign(id="c1", actor_id="a1", title="Збір на планшети", goal="military", type="mixed")
    result = classify_campaign(c, _topical_raw(), judge=judge)
    assert result is True


def test_classify_campaign_judge_called_once_for_ambiguous():
    """Judge викликається рівно 1 раз для ambiguous raw."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    calls = {"n": 0}

    def judge(prompt):
        calls["n"] += 1
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="тест", goal="military", type="mixed")
    classify_campaign(c, _topical_raw(), judge=judge)
    assert calls["n"] == 1
```

- [ ] **Step 2: Run to confirm all 12 tests fail**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit2.py -v --tb=short
```

Expected: 12 FAILED (ImportError — functions don't exist yet)

- [ ] **Step 3: Add `build_relevance_prompt`, `parse_relevance_verdict`, `classify_campaign`, `_live_judge_relevance` to `relevance.py`**

Add after the `purge_non_fundraising` function and before `main()` in `src/fundrec/relevance.py`:

```python
# ---------------------------------------------------------------------------
# Двоетапний класифікатор is_campaign
# ---------------------------------------------------------------------------

def build_relevance_prompt(title: str, text: str) -> str:
    """Будує промпт для LLM-судді: це збір чи топічний контент?

    Args:
        title: заголовок допису/кампанії.
        text: тіло тексту (обрізається до ~800 символів).

    Returns:
        Рядок промпту — LLM повинен відповісти СТРОГО JSON {"is_campaign": true|false}.
    """
    snippet = text[:800] if text else ""
    return (
        "Визнач: чи є цей пост ФАНДРАЙЗИНГОВИМ ЗВЕРНЕННЯМ (збір коштів, запит на донат,\n"
        "збір на ЗСУ/медицину/гум.допомогу, є реквізити або посилання на оплату),\n"
        "чи це ТОПІЧНИЙ/ОСВІТНІЙ/НОВИННИЙ контент без прямого запиту на пожертву.\n\n"
        "Відповідай СТРОГО JSON, без зайвого тексту:\n"
        '{"is_campaign": true}   — якщо це ЗБІР (просить задонатити/перекинути кошти)\n'
        '{"is_campaign": false}  — якщо це топічний/освітній/новинний/оглядовий пост\n\n'
        f"Заголовок: {title}\n"
        f"Текст (до 800 символів):\n{snippet}\n"
    )


def parse_relevance_verdict(obj: dict) -> bool:
    """Зчитує is_campaign з відповіді LLM.

    Args:
        obj: розпарсений JSON-словник від судді.

    Returns:
        True якщо is_campaign is True (строго bool), False у всіх інших випадках
        (відсутній ключ, None, рядок, тощо).
    """
    return obj.get("is_campaign") is True


def _live_judge_relevance(prompt: str) -> dict:  # pragma: no cover
    """Жива LLM-класифікація через claude CLI (haiku — дешево і достатньо)."""
    from . import extract  # noqa: PLC0415
    return extract.claude_cli(prompt, "haiku")


def classify_campaign(campaign: Any, raw: dict[str, Any], *, judge: Any = None) -> bool:
    """Класифікує кампанію: True = збір, False = топічний контент.

    Алгоритм:
      1. is_fundraising(raw) → True → повертаємо True (детерміновано, без LLM).
      2. Інакше → judge(build_relevance_prompt(title, text)) → parse_relevance_verdict.

    Args:
        campaign: об'єкт Campaign (потрібен для fallback title).
        raw: сирий словник запису.
        judge: ін'єктована функція (prompt: str) -> dict; за замовч. _live_judge_relevance.

    Returns:
        bool — True якщо збір, False якщо топічний.
    """
    if judge is None:
        judge = _live_judge_relevance  # pragma: no cover

    # Детермінований гейт — без LLM
    if is_fundraising(raw):
        return True

    # Витягаємо title + text з raw
    title = raw.get("title") or campaign.title or ""
    text = raw.get("text") or raw.get("raw_text") or raw.get("description") or ""

    prompt = build_relevance_prompt(title, text)
    result = judge(prompt)
    return parse_relevance_verdict(result)
```

- [ ] **Step 4: Run unit 2 tests — expect all 12 PASS**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit2.py -v
```

Expected: 12 passed

- [ ] **Step 5: Run full suite — no regressions**

```
.venv/Scripts/python.exe -m pytest -q --tb=short
```

Expected: 770+12 = 782 passed

- [ ] **Step 6: Run ruff on `relevance.py`**

```
.venv/Scripts/python.exe -m ruff check src/fundrec/relevance.py
```

Fix any issues (likely none if `Any` is already imported).

- [ ] **Step 7: Commit**

```bash
git add src/fundrec/relevance.py tests/test_is_campaign_unit2.py
git commit -m "$(cat <<'EOF'
feat: classify_campaign + build_relevance_prompt + parse_relevance_verdict

- build_relevance_prompt(title, text) → промпт для LLM-судді
- parse_relevance_verdict(obj) → bool (False якщо garbage/missing)
- classify_campaign(campaign, raw, *, judge) — двоетапна класифікація:
    is_fundraising(raw) → True без LLM; інакше → judge
- _live_judge_relevance → claude_cli haiku (pragma: no cover)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: DB classify pass + CLI

**Files:**
- Modify: `src/fundrec/relevance.py` — add `classify_relevance_db`, update `main()`
- Test: `tests/test_is_campaign_unit3.py`

Context: `_find_raw_file` already exists in `relevance.py`. The new `classify_relevance_db` mirrors `purge_non_fundraising` but NEVER deletes — it only calls `store.set_campaign_relevance`. CLI gets `--classify` added alongside existing `--purge`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_is_campaign_unit3.py`:

```python
"""Unit 3 — classify_relevance_db + CLI --classify: non-destructive pass.

TDD. Hermetic (tmp sqlite + tmp raw dir + injected judge).

3 кампанії:
  - jar-збір (raw є, is_fundraising True) → is_campaign=True, no judge call
  - топічний (raw є, is_fundraising False, judge→False) → is_campaign=False
  - no-raw (raw немає) → is_campaign лишається None
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fundrec import store
from fundrec.schema import Actor, Campaign


# ---------------------------------------------------------------------------
# Helpers (дзеркало test_relevance_unit3.py)
# ---------------------------------------------------------------------------

def _make_campaign(url: str, **kwargs) -> Campaign:
    cid = "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]
    defaults = dict(
        id=cid, actor_id="act-1", title="Test", goal="military",
        type="organic_social", provenance={},
    )
    defaults.update(kwargs)
    return Campaign(**defaults)


def _write_raw(raw_dir: Path, url: str, payload: dict) -> None:
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    p = raw_dir / f"{file_id}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_db(conn, actor_id: str = "act-1") -> None:
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id=actor_id, name="Actor", type="foundation"))


# ---------------------------------------------------------------------------
# Тест 1: основна поведінка
# ---------------------------------------------------------------------------

def test_classify_relevance_db_three_campaigns(tmp_path):
    """jar→True (no judge); topical→False (judge False); no-raw→None."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url_jar = "https://example.com/jar_zbir"
    url_topical = "https://example.com/topical"
    url_no_raw = "https://example.com/no_raw"

    camp_jar = _make_campaign(url_jar, title="FPV збір")
    camp_topical = _make_campaign(url_topical, title="TCCC відео")
    camp_no_raw = _make_campaign(url_no_raw, title="Без raw")

    for c in (camp_jar, camp_topical, camp_no_raw):
        store.upsert_campaign(conn, c)

    _write_raw(raw_dir, url_jar, {
        "url": url_jar,
        "title": "FPV збір",
        "text": "Банка: send.monobank.ua/jar/FPVJAR",
    })
    _write_raw(raw_dir, url_topical, {
        "url": url_topical,
        "title": "TCCC відео",
        "text": "Навчальний контент, огляд аптечки.",
    })

    judge_calls = {"n": 0}

    def fake_judge(prompt):
        judge_calls["n"] += 1
        return {"is_campaign": False}

    summary = classify_relevance_db(conn, raw_dir, judge=fake_judge)

    # Перевіряємо прапори
    loaded = {c.id: c for c in store.load_campaigns(conn)}
    assert loaded[camp_jar.id].is_campaign is True
    assert loaded[camp_topical.id].is_campaign is False
    assert loaded[camp_no_raw.id].is_campaign is None

    # Жоден з jar-кампаній не пішов до судді
    assert judge_calls["n"] == 1  # тільки topical

    # Summary counts
    assert summary["relevant"] == 1
    assert summary["topical"] == 1
    assert summary["no_raw"] == 1
    assert summary["llm_calls"] == 1


def test_classify_relevance_db_only_unset_skips_already_set(tmp_path):
    """only_unset=True пропускає кампанії де is_campaign вже встановлено."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/already_set"
    camp = _make_campaign(url, title="Вже класифіковано", is_campaign=True)
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "Вже класифіковано",
        "text": "Навчальний контент.",
    })

    judge_calls = {"n": 0}

    def fake_judge(prompt):
        judge_calls["n"] += 1
        return {"is_campaign": False}

    summary = classify_relevance_db(conn, raw_dir, judge=fake_judge, only_unset=True)

    # Judge не повинен викликатись — кампанія вже класифікована
    assert judge_calls["n"] == 0
    # is_campaign не змінилось
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_classify_relevance_db_only_unset_false_reclassifies(tmp_path):
    """only_unset=False повторно класифікує навіть вже встановлені."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/reclassify"
    # Спочатку встановлено True
    camp = _make_campaign(url, title="Перекласифікація", is_campaign=True)
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "Перекласифікація",
        "text": "Навчальний контент.",
    })

    def fake_judge(prompt):
        return {"is_campaign": False}

    classify_relevance_db(conn, raw_dir, judge=fake_judge, only_unset=False)

    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


# ---------------------------------------------------------------------------
# Тест 2: CLI --classify
# ---------------------------------------------------------------------------

def test_cli_classify_runs_and_prints_summary(tmp_path, capsys):
    """CLI --classify запускається, виводить summary (relevant/topical/no_raw)."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    conn.close()

    result_code = main([
        "--classify",
        "--db", str(tmp_path / "t.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(tmp_path / "cases.json"),
    ])

    assert result_code == 0
    captured = capsys.readouterr()
    assert "relevant" in captured.out


def test_cli_classify_exports_cases_json(tmp_path):
    """CLI --classify записує cases.json після класифікації."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    conn.close()

    out_path = tmp_path / "cases.json"
    main([
        "--classify",
        "--db", str(tmp_path / "t.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(out_path),
    ])

    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "cases" in data
```

- [ ] **Step 2: Run to confirm all 5 tests fail**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit3.py -v --tb=short
```

Expected: 5 FAILED (ImportError — `classify_relevance_db` doesn't exist)

- [ ] **Step 3: Add `classify_relevance_db` to `relevance.py`**

Add after `classify_campaign` and before `main()` in `src/fundrec/relevance.py`:

```python
def classify_relevance_db(
    conn: Any,
    raw_dir: Path | str,
    *,
    judge: Any = None,
    only_unset: bool = True,
) -> dict[str, int]:
    """Класифікує всі кампанії в БД і зберігає is_campaign прапор.

    NON-DESTRUCTIVE: нічого не видаляє. None = невідомо (no raw) — залишається None.

    Args:
        conn: SQLite connection (ініціалізована БД).
        raw_dir: директорія сирих кешів.
        judge: ін'єктована LLM-функція (prompt: str) -> dict; за замовч. _live_judge_relevance.
        only_unset: якщо True — пропускає кампанії де is_campaign вже встановлено.

    Returns:
        {scanned, relevant, topical, no_raw, llm_calls}
    """
    from . import store  # noqa: PLC0415

    if judge is None:
        judge = _live_judge_relevance  # pragma: no cover

    raw_dir = Path(raw_dir)
    campaigns = store.load_campaigns(conn)

    scanned = 0
    relevant = 0
    topical = 0
    no_raw = 0
    llm_calls = 0

    for campaign in campaigns:
        if only_unset and campaign.is_campaign is not None:
            continue

        scanned += 1

        raw_file = _find_raw_file(campaign, raw_dir)
        if raw_file is None:
            no_raw += 1
            continue  # залишаємо None — невідомо

        try:
            raw_item: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"relevance: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            no_raw += 1
            continue

        # Рахуємо LLM-виклики: is_fundraising True — детерміновано, без LLM
        will_use_llm = not is_fundraising(raw_item)
        if will_use_llm:
            llm_calls += 1

        flag = classify_campaign(campaign, raw_item, judge=judge)
        store.set_campaign_relevance(conn, campaign.id, flag)

        if flag:
            relevant += 1
        else:
            topical += 1

    return {
        "scanned": scanned,
        "relevant": relevant,
        "topical": topical,
        "no_raw": no_raw,
        "llm_calls": llm_calls,
    }
```

- [ ] **Step 4: Update `main()` in `relevance.py` to add `--classify`**

Replace the existing `main()` function with one that handles both `--purge` and `--classify`. The key change is: add `--classify` argument, add a branch that calls `classify_relevance_db` with the live judge (no inject in CLI), print summary.

```python
def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.relevance [--purge | --classify] [--db] [--raw-dir] [--out]."""
    import argparse  # noqa: PLC0415

    from . import config, export, store  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec relevance: purge або classify кампаній"
    )
    parser.add_argument("--purge", action="store_true", help="Видалити нерелевантні кампанії")
    parser.add_argument("--classify", action="store_true", help="Встановити is_campaign прапор (non-destructive)")
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів"
    )
    parser.add_argument(
        "--out", default=str(config.CASES_JSON), help="Шлях до cases.json для re-export"
    )
    args = parser.parse_args(argv)

    if not args.purge and not args.classify:
        parser.print_help()
        return 1

    db_path = Path(args.db)
    raw_dir = Path(args.raw_dir)

    if not db_path.exists():
        print(f"relevance: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)

    if args.purge:
        result = purge_non_fundraising(conn, raw_dir)
        exported = export.export_cases(conn, args.out)
        print(
            f"purge: scanned={result['scanned']} deleted={result['deleted']} "
            f"kept={result['kept']} no_raw={result['no_raw']} exported={exported}",
            file=sys.stdout,
        )

    if args.classify:
        result = classify_relevance_db(conn, raw_dir)
        exported = export.export_cases(conn, args.out)
        print(
            f"classify: scanned={result['scanned']} relevant={result['relevant']} "
            f"topical={result['topical']} no_raw={result['no_raw']} "
            f"llm_calls={result['llm_calls']} exported={exported}",
            file=sys.stdout,
        )

    return 0
```

- [ ] **Step 5: Run unit 3 tests — expect all 5 PASS**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit3.py -v
```

Expected: 5 passed

- [ ] **Step 6: Run full suite — no regressions**

```
.venv/Scripts/python.exe -m pytest -q --tb=short
```

Expected: 782+5 = 787 passed

- [ ] **Step 7: Run ruff**

```
.venv/Scripts/python.exe -m ruff check src/fundrec/relevance.py
```

Fix any issues.

- [ ] **Step 8: Commit**

```bash
git add src/fundrec/relevance.py tests/test_is_campaign_unit3.py
git commit -m "$(cat <<'EOF'
feat: classify_relevance_db + CLI --classify (non-destructive)

- classify_relevance_db(conn, raw_dir, *, judge, only_unset=True)
    → для кожної кампанії: is_fundraising=True→relevant (no LLM);
      ambiguous→judge; no raw→None (unknown, залишаємо)
    → повертає {scanned, relevant, topical, no_raw, llm_calls}
- CLI: --classify запускає classify_relevance_db + re-export
- Стара --purge поведінка незмінна

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Export serialization + dashboard filter

**Files:**
- Modify: `web/index.html` — `filteredCamps()`, toggle UI, `?` badge
- Modify: `src/fundrec/export.py` — verify `is_campaign` is in campaign dict (no code change likely needed, but add export test)
- Test: `tests/test_is_campaign_unit4.py`

Context: `campaign_to_dict(c)` uses `asdict(c)` from dataclasses, so `is_campaign` will be automatically included once the schema field exists (Task 1). The export test verifies this. The HTML changes are in `filteredCamps()` (add one filter line) and the campaign explorer card (add badge).

- [ ] **Step 1: Write failing export test**

Create `tests/test_is_campaign_unit4.py`:

```python
"""Unit 4 — export серіалізує is_campaign; dashboard test_index_clean залишається green.

TDD. is_campaign має бути в кожному campaign dict у cases.json.
"""
from __future__ import annotations

import json

from fundrec import export, store
from fundrec.schema import Actor, Campaign


def _setup(tmp_path, is_campaign_val):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1", title="Тест", goal="military", type="mixed",
        is_campaign=is_campaign_val,
    ))
    return conn


def test_export_includes_is_campaign_true(tmp_path):
    conn = _setup(tmp_path, True)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "is_campaign" in data["campaigns"][0]
    assert data["campaigns"][0]["is_campaign"] is True


def test_export_includes_is_campaign_false(tmp_path):
    conn = _setup(tmp_path, False)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["campaigns"][0]["is_campaign"] is False


def test_export_includes_is_campaign_none(tmp_path):
    """None (unknown) теж серіалізується — null у JSON."""
    conn = _setup(tmp_path, None)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "is_campaign" in data["campaigns"][0]
    assert data["campaigns"][0]["is_campaign"] is None
```

- [ ] **Step 2: Run to confirm tests pass immediately**

```
.venv/Scripts/python.exe -m pytest tests/test_is_campaign_unit4.py -v
```

Expected: 3 passed — `asdict(c)` already includes `is_campaign` from Task 1.

If any FAIL, it means `is_campaign` is not in the dataclass yet (Task 1 incomplete). Fix Task 1 first.

- [ ] **Step 3: Add `is_campaign` default filter to `filteredCamps()` in `web/index.html`**

Locate the `filteredCamps()` function (around line 753). It currently reads:

```javascript
function filteredCamps(){
 return CAMPAIGNS.filter(c=>{
  if(!passesRecency(c))return false;
  if(CSEL.channels.size&&!(c.channels||[]).some(x=>CSEL.channels.has(x)))return false;
  if(CSEL.form_factor.size&&!(c.form_factor||[]).some(x=>CSEL.form_factor.has(x)))return false;
  if(CSEL.tone.size&&!(c.tone||[]).some(x=>CSEL.tone.has(x)))return false;
  if(CSEL.face.size&&!CSEL.face.has(c.face))return false;
  if(CSEL.type.size&&!CSEL.type.has(c.type))return false;
  if(!passesVerifCamp(c))return false;
  return true;});
}
```

Replace with:

```javascript
function filteredCamps(){
 return CAMPAIGNS.filter(c=>{
  if(!passesRecency(c))return false;
  // is_campaign фільтр: false=топічний прихований за замовч.; null=невідомо → видимий
  if(campRelevMode==="zbory"&&c.is_campaign===false)return false;
  if(campRelevMode==="topical"&&c.is_campaign!==false)return false;
  if(CSEL.channels.size&&!(c.channels||[]).some(x=>CSEL.channels.has(x)))return false;
  if(CSEL.form_factor.size&&!(c.form_factor||[]).some(x=>CSEL.form_factor.has(x)))return false;
  if(CSEL.tone.size&&!(c.tone||[]).some(x=>CSEL.tone.has(x)))return false;
  if(CSEL.face.size&&!CSEL.face.has(c.face))return false;
  if(CSEL.type.size&&!CSEL.type.has(c.type))return false;
  if(!passesVerifCamp(c))return false;
  return true;});
}
```

- [ ] **Step 4: Add `campRelevMode` state variable to the state block**

Locate the `// ── стан КАМПАНІЙ ──` block (around line 369). After `let recencyDays=30;` add:

```javascript
let campRelevMode="zbory"; // "zbory" | "all" | "topical"
```

- [ ] **Step 5: Add the toggle UI in the Кампанії sidebar**

In `web/index.html`, locate the campaigns sidebar `<aside class="side" id="side-c">`. After the `<h4>верифікація</h4>` block and before the `<button class="resetbtn" id="c-reset">`, insert:

```html
  <h4>тип контенту</h4>
  <div class="seg" id="relev-seg" style="margin-bottom:6px">
   <button data-relev="zbory" id="relev-zbory" class="on">лише збори</button>
   <button data-relev="all" id="relev-all">усі</button>
   <button data-relev="topical" id="relev-topical">тільки топічне</button>
  </div>
```

- [ ] **Step 6: Wire the toggle into `setupCampaignView()` in `web/index.html`**

In `setupCampaignView()` (around line 1040), after the recency seg binding block, add:

```javascript
 // Relev segmented control
 document.querySelectorAll("#relev-seg button").forEach(b=>b.onclick=()=>{
  campRelevMode=b.dataset.relev;
  document.querySelectorAll("#relev-seg button").forEach(x=>x.classList.toggle("on",x===b));
  updateCamp();});
```

Also update the `c-reset` handler to reset `campRelevMode`. The current reset onclick is:

```javascript
 document.getElementById("c-reset").onclick=()=>{
  Object.values(CSEL).forEach(s=>s.clear());cVerifMode="all";recencyDays=30;
  document.getElementById("cf-verif").value="all";
  document.querySelectorAll("#recency-seg button").forEach(b=>b.classList.toggle("on",b.dataset.days==="30"));
  renderCampChips("cf-channels",CHANNEL_ORDER,"channels");renderCampChips("cf-form",FORM_ORDER,"form_factor");
  renderCampChips("cf-tone",TONE_ORDER,"tone");renderCampChips("cf-face",FACE_ORDER,"face");renderCampChips("cf-type",CTYPE_ORDER,"type");
  bindCampChips();updateCamp();};
```

Replace with (adds `campRelevMode` reset):

```javascript
 document.getElementById("c-reset").onclick=()=>{
  Object.values(CSEL).forEach(s=>s.clear());cVerifMode="all";recencyDays=30;campRelevMode="zbory";
  document.getElementById("cf-verif").value="all";
  document.querySelectorAll("#recency-seg button").forEach(b=>b.classList.toggle("on",b.dataset.days==="30"));
  document.querySelectorAll("#relev-seg button").forEach(b=>b.classList.toggle("on",b.dataset.relev==="zbory"));
  renderCampChips("cf-channels",CHANNEL_ORDER,"channels");renderCampChips("cf-form",FORM_ORDER,"form_factor");
  renderCampChips("cf-tone",TONE_ORDER,"tone");renderCampChips("cf-face",FACE_ORDER,"face");renderCampChips("cf-type",CTYPE_ORDER,"type");
  bindCampChips();updateCamp();};
```

- [ ] **Step 7: Add `?` badge for `is_campaign === null` in `renderExplorer`**

In `renderExplorer(camps)` (around line 955), locate the campaign card `.crow` HTML. Currently it ends with:

```javascript
    <span class="badge ${esc(c.verification_status)}">${esc(c.verification_status)}</span>
```

Insert before that badge:

```javascript
    ${c.is_campaign===null?'<span class="badge auto" title="релевантність невідома">?</span>':""}
```

The full `.crow` return line currently reads (abbreviated):
```javascript
  return `<div class="ccard ${open?"open":""}" data-cid="${esc(c.id)}">
   <div class="crow">
    ...
    <span class="badge ${esc(c.verification_status)}">${esc(c.verification_status)}</span>
   </div>
```

Change to:
```javascript
  return `<div class="ccard ${open?"open":""}" data-cid="${esc(c.id)}">
   <div class="crow">
    ...
    ${c.is_campaign===null?'<span class="badge auto" title="релевантність невідома">?</span>':""}
    <span class="badge ${esc(c.verification_status)}">${esc(c.verification_status)}</span>
   </div>
```

- [ ] **Step 8: Run all tests including `test_index_clean`**

```
.venv/Scripts/python.exe -m pytest tests/test_index_clean.py tests/test_is_campaign_unit4.py -v
```

Expected: all pass (no NUL bytes, valid UTF-8)

- [ ] **Step 9: Run full suite — no regressions**

```
.venv/Scripts/python.exe -m pytest -q --tb=short
```

Expected: 787+3 = 790 passed

- [ ] **Step 10: Run ruff**

```
.venv/Scripts/python.exe -m ruff check src/
```

Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add tests/test_is_campaign_unit4.py web/index.html
git commit -m "$(cat <<'EOF'
feat: export is_campaign + dashboard toggle (лише збори / усі / тільки топічне)

- export: is_campaign автоматично в campaign dict (asdict)
- filteredCamps() за замовч. ховає is_campaign===false (лише збори)
- toggle «лише збори / усі / тільки топічне» в сайдбарі
- badge «?» для кампаній з is_campaign===null (невідомо)
- c-reset скидає campRelevMode до «збори»

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist

### Spec Coverage

| Requirement | Task |
|---|---|
| `is_campaign: bool \| None = None` dataclass field | Task 1 |
| `db/schema.sql` `is_campaign INTEGER` column | Task 1 |
| `_row_to_campaign` INTEGER↔bool/None round-trip | Task 1 |
| `upsert_campaign` stores bool→int | Task 1 (auto via existing loop — `is_campaign` is not in `_JSON_CAMPAIGN_FIELDS`, stored as int directly) |
| `store.set_campaign_relevance(conn, id, bool)` | Task 1 |
| `build_relevance_prompt(title, text) -> str` | Task 2 |
| `parse_relevance_verdict(obj) -> bool` | Task 2 |
| `classify_campaign(campaign, raw, *, judge=None) -> bool` | Task 2 |
| `_live_judge_relevance` → `claude_cli(prompt, "haiku")` | Task 2 |
| `classify_relevance_db(conn, raw_dir, *, judge, only_unset)` | Task 3 |
| CLI `--classify` | Task 3 |
| `--purge` still works | Task 3 (kept in updated `main()`) |
| Export: `is_campaign` in campaign dict | Task 4 |
| Dashboard: default hide `is_campaign===false` | Task 4 |
| Toggle «лише збори / усі / тільки топічне» | Task 4 |
| `?` badge on null campaigns | Task 4 |
| `test_index_clean` still green | Task 4 (step 8) |

### Potential Issues

1. **`upsert_campaign` + `is_campaign`**: The field is NOT in `_JSON_CAMPAIGN_FIELDS`, so it's stored as-is. SQLite accepts `None` as NULL and `True`/`False` as 1/0 via Python sqlite3. Verified this matches `goal_reached` behavior. No issue.

2. **`classify_campaign` calls `judge` with a prompt**: `_live_judge_relevance` is `# pragma: no cover`. Tests always inject `judge=`. No live LLM in tests.

3. **`classify_relevance_db` `llm_calls` count**: Incremented before calling `classify_campaign` (based on `not is_fundraising(raw_item)`). This is accurate because `classify_campaign` calls judge only when `is_fundraising` is False. The count is computed locally here so it doesn't require modifying `classify_campaign`'s signature.

4. **HTML toggle in `setupCampaignView`**: The relev-seg binding must be inside `if(!hasCamps)return;` block — if there are no campaigns the DOM elements don't exist. The binding code is placed after the `if(!hasCamps)return;` guard (per existing pattern for all other seg bindings), so it's safe.

5. **NUL bytes in index.html**: The `?` badge text uses ASCII only. No Unicode escape sequences that could produce NUL. `test_index_clean` will catch any regression.

---

## How to Run (after implementation)

```bash
# Classify all unset campaigns (human runs against real DB):
python -m fundrec.relevance --classify

# Classify all (re-classify already-set too):
python -m fundrec.relevance --classify --db data/fundrec.sqlite --raw-dir data/raw --out data/cases.json

# Purge (old behavior, unchanged):
python -m fundrec.relevance --purge
```

## ALTER TABLE Note

Existing `data/fundrec.sqlite` does NOT have the `is_campaign` column. Before running `--classify`, run:

```sql
ALTER TABLE campaigns ADD COLUMN is_campaign INTEGER;
```

Or delete and recreate the DB (loses all data). The `schema.sql` `CREATE TABLE IF NOT EXISTS` does NOT add new columns to existing tables.
