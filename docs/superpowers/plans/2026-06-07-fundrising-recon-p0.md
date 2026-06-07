# fundrising_recon P0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin end-to-end vertical slice: seed → collect (Monobank jar) → LLM extract → SQLite store → export `data/cases.json`, with the typed `Case`/`Actor`/`Source` model and deterministic validation.

**Architecture:** Python package `fundrec`. Pure-Python typed model (dataclasses) is the contract. SQLite store with JSON columns for list/dict fields. One real collector (Monobank jar JSON). LLM extraction has a deterministic, testable surface (prompt build + response parse) with the network call isolated behind an injectable client. Deterministic validators enforce the discipline invariants. CLI wires the stages.

**Tech Stack:** Python 3.12, `httpx`, `sqlite3` (stdlib), `claude-agent-sdk` (live extraction only), `pytest`, `ruff`.

**Scope note:** This plan is P0 only (spec §9). P1 (more collectors + Discoverer + dedup), P2 (critic), P3 (analyze/axes), P4 (cockpit) get their own plans. P0 leaves the 4 axis fields (`volume_score`, `speed`, `virality_score`, `repeatability`) on `Case` as nullable, populated in P3.

---

## File Structure (P0)

| File | Responsibility |
|---|---|
| `pyproject.toml` | package metadata, deps, ruff/pytest config |
| `src/fundrec/__init__.py` | package marker |
| `src/fundrec/config.py` | paths, model ids, env loading |
| `src/fundrec/schema.py` | controlled vocabularies + `Provenance`/`Actor`/`Source`/`Case` dataclasses + serialization helpers |
| `src/fundrec/db/schema.sql` | SQLite DDL |
| `src/fundrec/store.py` | connect/init + upsert/load for actors, sources, cases |
| `src/fundrec/collect/__init__.py` | collect subpackage marker |
| `src/fundrec/collect/monobank.py` | fetch + parse a Monobank jar into a raw dict |
| `src/fundrec/extract.py` | build extraction prompt + parse LLM JSON → `Case`; live wrapper via Agent SDK |
| `src/fundrec/validate.py` | deterministic invariant validators for `Case` |
| `src/fundrec/export.py` | dump DB → `data/cases.json` |
| `src/fundrec/cli.py` | wire seed → collect → extract → store → export |
| `data/seeds/p0_seed.json` | ~10 hand-listed cases (URLs + actor + goal only) to drive the slice |
| `tests/` | one test module per source module |

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/fundrec/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
def test_package_imports():
    import fundrec
    assert fundrec.__name__ == "fundrec"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec'`

- [ ] **Step 3: Create the scaffold**

```toml
# pyproject.toml
[project]
name = "fundrec"
version = "0.0.1"
description = "Ukrainian wartime fundraising case database (2022->2026)"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
live = ["claude-agent-sdk>=0.1", "anthropic>=0.40"]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]
```

```python
# src/fundrec/__init__.py
"""fundrec — база кейсів фандрайзингу України (2022->2026)."""
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/fundrec/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: project scaffold (fundrec package + pytest)"
```

---

## Task 2: Config

**Files:**
- Create: `src/fundrec/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path
from fundrec import config

def test_paths_are_under_repo_root():
    assert config.DATA_DIR.name == "data"
    assert config.DB_PATH.suffix == ".sqlite"
    assert isinstance(config.ROOT, Path)

def test_models_defined():
    assert config.EXTRACT_MODEL
    assert config.JUDGE_MODEL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.config'`

- [ ] **Step 3: Write the implementation**

```python
# src/fundrec/config.py
"""Шляхи, моделі, env. Єдине джерело конфігурації."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEEDS_DIR = DATA_DIR / "seeds"
DB_PATH = DATA_DIR / "fundrec.sqlite"
CASES_JSON = DATA_DIR / "cases.json"

# Генератор/екстрактор — Claude Agent SDK на підписці (Opus). Критик — прямий API (Sonnet).
EXTRACT_MODEL = os.environ.get("FUNDREC_EXTRACT_MODEL", "claude-opus-4-8")
JUDGE_MODEL = os.environ.get("FUNDREC_JUDGE_MODEL", "claude-sonnet-4-6")
# Навмисно НЕ ANTHROPIC_API_KEY (інакше SDK перемкне екстрактор на платний API).
CRITIC_API_KEY = os.environ.get("FUNDREC_CRITIC_API_KEY", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/config.py tests/test_config.py
git commit -m "feat: config module (paths, model ids, env)"
```

---

## Task 3: Typed model + vocabularies

**Files:**
- Create: `src/fundrec/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
from fundrec import schema
from fundrec.schema import Actor, Source, Case

def test_vocabularies_present():
    assert "military" in schema.GOAL_CATEGORIES
    assert "monobank_jar" in schema.METHOD_TAGS
    assert "gamification" in schema.STYLE_TAGS
    assert "foundation" in schema.ACTOR_TYPES
    assert schema.VERIFICATION == {"auto", "cross-checked", "verified", "conflict"}

def test_case_roundtrips_through_dict():
    c = Case(
        id="c1", title="FPV для бригади", actor_id="a1",
        url="https://send.monobank.ua/jar/abc",
        goal="military/fpv", style=["urgency"], method=["monobank_jar"],
        year=2026, amount_uah=1000000.0,
        provenance={"amount_uah": {"source_url": "https://send.monobank.ua/jar/abc",
                                   "confidence": 0.95, "tier": 1, "note": "jar json"}},
    )
    d = schema.case_to_dict(c)
    assert d["style"] == ["urgency"]
    c2 = schema.case_from_dict(d)
    assert c2 == c

def test_actor_and_source_construct():
    a = Actor(id="a1", name="Сергій Притула", type="foundation")
    s = Source(url="https://prytulafoundation.org", type="structured", tier=1,
               access="public", license="unknown", actor_id="a1")
    assert a.links == []
    assert s.tier == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.schema'`

- [ ] **Step 3: Write the implementation**

```python
# src/fundrec/schema.py
"""Контракт даних: словники + Actor/Source/Case + (де)серіалізація.

Дисципліна (spec §4, §8): значущі числа несуть provenance; осі успіху
порожні до стадії ANALYZE (P3).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# --- контрольовані словники (spec §4) ---
GOAL_CATEGORIES = {
    "military", "medical", "humanitarian", "reconstruction",
    "energy", "animals", "science_education", "info_defense", "other",
}
STYLE_TAGS = {
    "emotional_personal", "data_transparent", "urgency", "gamification",
    "celebrity", "grassroots", "meme_satire",
}
METHOD_TAGS = {
    "monobank_jar", "bank_transfer", "crypto", "nft_merch", "auction",
    "telethon", "stream", "challenge", "corporate_match", "platform",
}
ACTOR_TYPES = {"foundation", "individual", "milblogger", "corporate", "diaspora", "state"}
SOURCE_TYPES = {"structured", "news", "social"}
VERIFICATION = {"auto", "cross-checked", "verified", "conflict"}


@dataclass
class Actor:
    id: str
    name: str
    type: str
    founded: str | None = None
    links: list[str] = field(default_factory=list)


@dataclass
class Source:
    url: str
    type: str
    tier: int
    access: str
    license: str
    actor_id: str | None = None


@dataclass
class Case:
    id: str
    title: str
    actor_id: str
    url: str
    goal: str                       # "category" або "category/subcategory"
    style: list[str] = field(default_factory=list)
    method: list[str] = field(default_factory=list)
    date_start: str | None = None
    date_end: str | None = None
    year: int | None = None
    amount_uah: float | None = None
    amount_usd: float | None = None
    goal_amount: float | None = None
    currency_raw: str | None = None
    # осі успіху — заповнюються в ANALYZE (P3)
    volume_score: float | None = None
    speed: float | None = None
    virality_score: float | None = None
    repeatability: float | None = None
    # дисципліна
    provenance: dict[str, dict] = field(default_factory=dict)
    confidence_overall: float = 0.0
    verification_status: str = "auto"
    extracted_at: str | None = None
    extracted_by_model: str | None = None


def case_to_dict(c: Case) -> dict:
    return asdict(c)


def case_from_dict(d: dict) -> Case:
    return Case(**d)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/schema.py tests/test_schema.py
git commit -m "feat: typed Case/Actor/Source model + controlled vocabularies"
```

---

## Task 4: SQLite store

**Files:**
- Create: `src/fundrec/db/__init__.py`
- Create: `src/fundrec/db/schema.sql`
- Create: `src/fundrec/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
from fundrec import store
from fundrec.schema import Actor, Source, Case

def _seed(conn):
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(url="https://x", type="structured",
                                     tier=1, access="public", license="unknown", actor_id="a1"))

def test_init_and_upsert_case_roundtrip(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c1", title="FPV", actor_id="a1", url="https://x",
             goal="military/fpv", style=["urgency"], method=["monobank_jar"],
             year=2026, amount_uah=500000.0,
             provenance={"amount_uah": {"source_url": "https://x", "confidence": 0.9,
                                        "tier": 1, "note": ""}})
    store.upsert_case(conn, c)
    loaded = store.load_cases(conn)
    assert len(loaded) == 1
    assert loaded[0] == c

def test_upsert_is_idempotent(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c1", title="FPV", actor_id="a1", url="https://x", goal="military")
    store.upsert_case(conn, c)
    c.title = "FPV (оновлено)"
    store.upsert_case(conn, c)
    loaded = store.load_cases(conn)
    assert len(loaded) == 1
    assert loaded[0].title == "FPV (оновлено)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.store'`

- [ ] **Step 3: Write the SQL and store**

```sql
-- src/fundrec/db/schema.sql
CREATE TABLE IF NOT EXISTS actors (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    type    TEXT NOT NULL,
    founded TEXT,
    links   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS sources (
    url      TEXT PRIMARY KEY,
    type     TEXT NOT NULL,
    tier     INTEGER NOT NULL,
    access   TEXT NOT NULL,
    license  TEXT NOT NULL,
    actor_id TEXT REFERENCES actors(id)
);

CREATE TABLE IF NOT EXISTS cases (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    actor_id            TEXT NOT NULL,
    url                 TEXT NOT NULL,
    goal                TEXT NOT NULL,
    style               TEXT NOT NULL DEFAULT '[]',
    method              TEXT NOT NULL DEFAULT '[]',
    date_start          TEXT,
    date_end            TEXT,
    year                INTEGER,
    amount_uah          REAL,
    amount_usd          REAL,
    goal_amount         REAL,
    currency_raw        TEXT,
    volume_score        REAL,
    speed               REAL,
    virality_score      REAL,
    repeatability       REAL,
    provenance          TEXT NOT NULL DEFAULT '{}',
    confidence_overall  REAL NOT NULL DEFAULT 0.0,
    verification_status TEXT NOT NULL DEFAULT 'auto',
    extracted_at        TEXT,
    extracted_by_model  TEXT
);
```

```python
# src/fundrec/db/__init__.py
```

```python
# src/fundrec/store.py
"""Сховище SQLite: connect/init + upsert/load для actors, sources, cases.

JSON-поля (links, style, method, provenance) серіалізуються в TEXT-колонки.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path

from . import config
from .schema import Actor, Case, Source

_SCHEMA_SQL = (Path(__file__).parent / "db" / "schema.sql").read_text(encoding="utf-8")
_JSON_CASE_FIELDS = ("style", "method", "provenance")


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def upsert_actor(conn: sqlite3.Connection, actor: Actor) -> None:
    conn.execute(
        "INSERT INTO actors (id, name, type, founded, links) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, type=excluded.type, "
        "founded=excluded.founded, links=excluded.links",
        (actor.id, actor.name, actor.type, actor.founded, json.dumps(actor.links, ensure_ascii=False)),
    )
    conn.commit()


def upsert_source(conn: sqlite3.Connection, source: Source) -> None:
    conn.execute(
        "INSERT INTO sources (url, type, tier, access, license, actor_id) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET type=excluded.type, tier=excluded.tier, "
        "access=excluded.access, license=excluded.license, actor_id=excluded.actor_id",
        (source.url, source.type, source.tier, source.access, source.license, source.actor_id),
    )
    conn.commit()


def _case_columns() -> list[str]:
    return [f.name for f in fields(Case)]


def upsert_case(conn: sqlite3.Connection, case: Case) -> None:
    cols = _case_columns()
    values = []
    for name in cols:
        val = getattr(case, name)
        if name in _JSON_CASE_FIELDS:
            val = json.dumps(val, ensure_ascii=False)
        values.append(val)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO cases ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _row_to_case(row: sqlite3.Row) -> Case:
    data = dict(row)
    for name in _JSON_CASE_FIELDS:
        data[name] = json.loads(data[name])
    return Case(**data)


def load_cases(conn: sqlite3.Connection) -> list[Case]:
    rows = conn.execute("SELECT * FROM cases ORDER BY id").fetchall()
    return [_row_to_case(r) for r in rows]


def get_case(conn: sqlite3.Connection, case_id: str) -> Case | None:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_case(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/db/__init__.py src/fundrec/db/schema.sql src/fundrec/store.py tests/test_store.py
git commit -m "feat: SQLite store (actors/sources/cases upsert+load)"
```

---

## Task 5: Monobank jar collector

**Files:**
- Create: `src/fundrec/collect/__init__.py`
- Create: `src/fundrec/collect/monobank.py`
- Create: `tests/fixtures/monobank_jar.json`
- Test: `tests/test_monobank.py`

Note: the live jar JSON shape must be confirmed on first real run (spec §10). `parse_jar` maps a payload dict to our raw fields; the fixture defines the shape the test pins. `fetch_jar` is isolated behind an injectable client so tests never hit the network.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_monobank.py
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
```

- [ ] **Step 2: Create the fixture**

```json
// tests/fixtures/monobank_jar.json
{
  "title": "На FPV для 3-ї бригади",
  "amount": 125000000,
  "goal": 200000000,
  "currency": "UAH"
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_monobank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.collect'`

- [ ] **Step 4: Write the implementation**

```python
# src/fundrec/collect/__init__.py
```

```python
# src/fundrec/collect/monobank.py
"""Колектор банок Monobank: дістає публічний JSON банки -> сирий dict.

amount/goal у JSON — у копійках; ділимо на 100 -> гривні. Реальний формат
ендпоінта підтвердити на першому живому запуску (spec §10).
"""
from __future__ import annotations

from typing import Any

JAR_URL = "https://send.monobank.ua/jar/{jar_id}"
JAR_JSON_URL = "https://send.monobank.ua/api/handler"  # підтвердити на живому запуску


def parse_jar(jar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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


def fetch_jar(jar_id: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Дістає банку. _client інжектиться в тестах; інакше httpx."""
    if _client is None:
        import httpx
        _client = httpx.Client(follow_redirects=True)
    resp = _client.get(JAR_URL.format(jar_id=jar_id), timeout=20)
    resp.raise_for_status()
    return parse_jar(jar_id, resp.json())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_monobank.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/fundrec/collect/__init__.py src/fundrec/collect/monobank.py tests/fixtures/monobank_jar.json tests/test_monobank.py
git commit -m "feat: Monobank jar collector (parse + injectable fetch)"
```

---

## Task 6: Deterministic validators

**Files:**
- Create: `src/fundrec/validate.py`
- Test: `tests/test_validate.py`

Enforces spec §8 invariants without an LLM: provenance present for non-null numbers; year in range; non-negative amounts; goal category and style/method tags in vocabulary. (The §8 #5 "virality null not 0" rule belongs to ANALYZE/P3, where axes are computed — not validated here.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate.py
from fundrec.schema import Case
from fundrec import validate

def _valid_case(**over):
    base = dict(
        id="c1", title="FPV", actor_id="a1", url="https://x",
        goal="military/fpv", style=["urgency"], method=["monobank_jar"],
        year=2026, amount_uah=500000.0,
        provenance={"amount_uah": {"source_url": "https://x", "confidence": 0.9,
                                   "tier": 1, "note": ""}},
    )
    base.update(over)
    return Case(**base)

def test_clean_case_has_no_problems():
    assert validate.validate_case(_valid_case()) == []

def test_amount_without_provenance_flagged():
    c = _valid_case(provenance={})
    problems = validate.validate_case(c)
    assert any("provenance" in p for p in problems)

def test_year_out_of_range_flagged():
    assert any("year" in p for p in validate.validate_case(_valid_case(year=2019)))

def test_negative_amount_flagged():
    assert any("amount_uah" in p for p in validate.validate_case(_valid_case(amount_uah=-5.0)))

def test_unknown_goal_category_flagged():
    assert any("goal" in p for p in validate.validate_case(_valid_case(goal="weapons/x")))

def test_unknown_style_tag_flagged():
    assert any("style" in p for p in validate.validate_case(_valid_case(style=["funny"])))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.validate'`

- [ ] **Step 3: Write the implementation**

```python
# src/fundrec/validate.py
"""Детерміновані валідатори інваріантів Case (spec §8). Без LLM.

validate_case повертає список текстових проблем; порожній список = валідно.
"""
from __future__ import annotations

from . import schema
from .schema import Case

YEAR_MIN, YEAR_MAX = 2022, 2026
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def validate_case(c: Case) -> list[str]:
    problems: list[str] = []

    # Інв.1: кожне непорожнє число має provenance
    for f in _NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and f not in c.provenance:
            problems.append(f"missing provenance for {f}")

    # Інв.5/числа: невідʼємні суми
    for f in _NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and val < 0:
            problems.append(f"negative {f}: {val}")

    # рік у межах війни
    if c.year is not None and not (YEAR_MIN <= c.year <= YEAR_MAX):
        problems.append(f"year out of range [{YEAR_MIN},{YEAR_MAX}]: {c.year}")

    # ціль: category[/subcategory], category у словнику
    category = c.goal.split("/", 1)[0]
    if category not in schema.GOAL_CATEGORIES:
        problems.append(f"unknown goal category: {category}")

    # стилі/способи у словниках
    for tag in c.style:
        if tag not in schema.STYLE_TAGS:
            problems.append(f"unknown style tag: {tag}")
    for tag in c.method:
        if tag not in schema.METHOD_TAGS:
            problems.append(f"unknown method tag: {tag}")

    # verification у словнику
    if c.verification_status not in schema.VERIFICATION:
        problems.append(f"unknown verification_status: {c.verification_status}")

    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/validate.py tests/test_validate.py
git commit -m "feat: deterministic Case validators (spec invariants)"
```

---

## Task 7: LLM extraction (testable surface)

**Files:**
- Create: `src/fundrec/extract.py`
- Test: `tests/test_extract.py`

The network/LLM call is isolated. We TDD two deterministic functions: `build_prompt(raw, source)` and `parse_extraction(llm_obj, raw, source, model)` → `Case` with provenance attached by tier. `extract_case(...)` wires them with an injectable `_complete` callable (live wrapper uses Agent SDK).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
from fundrec import extract
from fundrec.schema import Source

SRC = Source(url="https://send.monobank.ua/jar/abc", type="structured",
             tier=1, access="public", license="unknown", actor_id="a1")
RAW = {"jar_id": "abc", "url": "https://send.monobank.ua/jar/abc",
       "title": "FPV для бригади", "amount_uah": 1250000.0,
       "goal_amount": 2000000.0, "currency_raw": "UAH"}

def test_build_prompt_includes_raw_and_vocab():
    p = extract.build_prompt(RAW, SRC)
    assert "FPV для бригади" in p
    assert "military" in p          # словник цілей у промпті
    assert "monobank_jar" in p

def test_parse_extraction_attaches_provenance_by_tier():
    llm_obj = {
        "title": "FPV для бригади", "goal": "military/fpv",
        "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
        "amount_uah": 1250000.0, "goal_amount": 2000000.0, "currency_raw": "UAH",
    }
    case = extract.parse_extraction(llm_obj, RAW, SRC, model="claude-opus-4-8", case_id="c1", actor_id="a1")
    assert case.id == "c1"
    assert case.goal == "military/fpv"
    assert case.amount_uah == 1250000.0
    # provenance автоматично на кожне непорожнє число, tier із джерела
    assert case.provenance["amount_uah"]["source_url"] == SRC.url
    assert case.provenance["amount_uah"]["tier"] == 1
    assert case.provenance["amount_uah"]["confidence"] == 0.95   # tier1 -> 0.95
    assert case.extracted_by_model == "claude-opus-4-8"
    assert case.verification_status == "auto"

def test_parse_extraction_null_number_gets_no_provenance():
    llm_obj = {"title": "X", "goal": "military", "style": [], "method": ["monobank_jar"],
               "amount_uah": None}
    case = extract.parse_extraction(llm_obj, RAW, SRC, model="m", case_id="c2", actor_id="a1")
    assert case.amount_uah is None
    assert "amount_uah" not in case.provenance

def test_extract_case_uses_injected_complete():
    def fake_complete(prompt: str) -> dict:
        return {"title": "FPV для бригади", "goal": "military/fpv",
                "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
                "amount_uah": 1250000.0}
    case = extract.extract_case(RAW, SRC, case_id="c1", actor_id="a1",
                                model="m", _complete=fake_complete)
    assert case.goal == "military/fpv"
    assert case.provenance["amount_uah"]["tier"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.extract'`

- [ ] **Step 3: Write the implementation**

```python
# src/fundrec/extract.py
"""LLM-екстракція raw -> Case.

Детерміновані surface-функції (build_prompt / parse_extraction) — тестуються.
Мережевий виклик ізольований у extract_case(_complete=...). Жорстке правило
дисципліни: provenance ставиться на КОЖНЕ непорожнє число; tier береться з
джерела; confidence — за tier (spec §5).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from . import schema
from .schema import Case, Source

_TIER_CONFIDENCE = {1: 0.95, 2: 0.6, 3: 0.35}
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def build_prompt(raw: dict[str, Any], source: Source) -> str:
    return (
        "Витягни структуровані дані про збір коштів із сирого запису джерела.\n"
        "Поверни СТРОГО JSON з полями: title, goal, style[], method[], year, "
        "date_start, date_end, amount_uah, amount_usd, goal_amount, currency_raw.\n"
        "Не вигадуй чисел: якщо значення немає в джерелі — став null.\n\n"
        f"Дозволені goal (category або category/subcategory): {sorted(schema.GOAL_CATEGORIES)}\n"
        f"Дозволені style: {sorted(schema.STYLE_TAGS)}\n"
        f"Дозволені method: {sorted(schema.METHOD_TAGS)}\n\n"
        f"Джерело: {source.url} (tier {source.tier})\n"
        f"Сирий запис: {raw}\n"
    )


def parse_extraction(
    llm_obj: dict[str, Any], raw: dict[str, Any], source: Source,
    *, model: str, case_id: str, actor_id: str,
) -> Case:
    confidence = _TIER_CONFIDENCE.get(source.tier, 0.35)
    provenance: dict[str, dict] = {}
    for f in _NUMERIC_FIELDS:
        if llm_obj.get(f) is not None:
            provenance[f] = {
                "source_url": source.url, "confidence": confidence,
                "tier": source.tier, "note": "",
            }
    return Case(
        id=case_id,
        title=llm_obj.get("title") or raw.get("title") or "",
        actor_id=actor_id,
        url=source.url,
        goal=llm_obj.get("goal") or "other",
        style=list(llm_obj.get("style") or []),
        method=list(llm_obj.get("method") or []),
        date_start=llm_obj.get("date_start"),
        date_end=llm_obj.get("date_end"),
        year=llm_obj.get("year"),
        amount_uah=llm_obj.get("amount_uah"),
        amount_usd=llm_obj.get("amount_usd"),
        goal_amount=llm_obj.get("goal_amount"),
        currency_raw=llm_obj.get("currency_raw"),
        provenance=provenance,
        confidence_overall=confidence if provenance else 0.0,
        verification_status="auto",
        extracted_at=datetime.now(timezone.utc).isoformat(),
        extracted_by_model=model,
    )


def extract_case(
    raw: dict[str, Any], source: Source,
    *, case_id: str, actor_id: str, model: str,
    _complete: Callable[[str], dict] | None = None,
) -> Case:
    if _complete is None:
        _complete = _live_complete
    prompt = build_prompt(raw, source)
    llm_obj = _complete(prompt)
    return parse_extraction(llm_obj, raw, source, model=model, case_id=case_id, actor_id=actor_id)


def _live_complete(prompt: str) -> dict:  # pragma: no cover - мережа/LLM
    """Живий виклик через Claude Agent SDK (підписка). Повертає dict із JSON."""
    import json

    from claude_agent_sdk import query  # type: ignore

    chunks: list[str] = []
    for msg in query(prompt=prompt):
        text = getattr(msg, "text", None)
        if text:
            chunks.append(text)
    return json.loads("".join(chunks))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_extract.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/extract.py tests/test_extract.py
git commit -m "feat: LLM extraction surface (prompt build + provenance-attaching parse)"
```

---

## Task 8: JSON export

**Files:**
- Create: `src/fundrec/export.py`
- Test: `tests/test_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export.py
import json

from fundrec import export, store
from fundrec.schema import Actor, Case, Source

def test_export_writes_cases_json(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(url="https://x", type="structured", tier=1,
                                     access="public", license="unknown", actor_id="a1"))
    store.upsert_case(conn, Case(id="c1", title="FPV", actor_id="a1", url="https://x",
                                 goal="military", style=["urgency"], method=["monobank_jar"]))
    out = tmp_path / "cases.json"
    n = export.export_cases(conn, out)
    assert n == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["count"] == 1
    assert data["cases"][0]["id"] == "c1"
    assert data["cases"][0]["style"] == ["urgency"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.export'`

- [ ] **Step 3: Write the implementation**

```python
# src/fundrec/export.py
"""Дамп БД -> data/cases.json для дашборда (P4)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, schema, store


def export_cases(conn: sqlite3.Connection, out_path: Path | str = config.CASES_JSON) -> int:
    cases = store.load_cases(conn)
    payload = {
        "count": len(cases),
        "cases": [schema.case_to_dict(c) for c in cases],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cases)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/fundrec/export.py tests/test_export.py
git commit -m "feat: export DB -> data/cases.json"
```

---

## Task 9: Seed data + CLI wiring

**Files:**
- Create: `data/seeds/p0_seed.json`
- Create: `src/fundrec/cli.py`
- Test: `tests/test_cli.py`

The seed lists known cases as `{case_id, actor_id, actor_name, actor_type, jar_id, goal_hint}`. CLI builds actor+source, collects the jar, extracts, validates, stores, exports. Network + LLM injected in the test; live run uses real fetch + Agent SDK.

- [ ] **Step 1: Create the seed**

```json
// data/seeds/p0_seed.json
[
  {"case_id": "mono-fpv-3bri", "actor_id": "vol-anon-1", "actor_name": "Волонтерська банка",
   "actor_type": "individual", "jar_id": "abc123", "goal_hint": "military"}
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path

from fundrec import cli, store

FIXTURE = {"title": "На FPV для 3-ї бригади", "amount": 125000000,
           "goal": 200000000, "currency": "UAH"}

def test_run_pipeline_end_to_end(tmp_path):
    seed = [{"case_id": "c1", "actor_id": "a1", "actor_name": "Банка",
             "actor_type": "individual", "jar_id": "abc123", "goal_hint": "military"}]
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    db_path = tmp_path / "t.sqlite"
    out_path = tmp_path / "cases.json"

    def fake_fetch(jar_id, **_):
        from fundrec.collect import monobank
        return monobank.parse_jar(jar_id, FIXTURE)

    def fake_complete(prompt):
        return {"title": "На FPV для 3-ї бригади", "goal": "military/fpv",
                "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
                "amount_uah": 1250000.0, "goal_amount": 2000000.0, "currency_raw": "UAH"}

    result = cli.run_pipeline(seed_path, db_path=db_path, out_path=out_path,
                              _fetch=fake_fetch, _complete=fake_complete)
    assert result["stored"] == 1
    assert result["problems"] == {}

    conn = store.connect(db_path)
    cases = store.load_cases(conn)
    assert len(cases) == 1
    assert cases[0].amount_uah == 1250000.0
    assert cases[0].provenance["amount_uah"]["tier"] == 1
    assert json.loads(out_path.read_text(encoding="utf-8"))["count"] == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fundrec.cli'`

- [ ] **Step 4: Write the implementation**

```python
# src/fundrec/cli.py
"""CLI P0: seed -> collect (Monobank) -> extract -> validate -> store -> export.

Мережа й LLM інжектяться (_fetch/_complete) для тестів; за замовчуванням —
живі monobank.fetch_jar та extract._live_complete.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import config, export, extract, store, validate
from .collect import monobank
from .schema import Actor, Source


def run_pipeline(
    seed_path: Path | str,
    *,
    db_path: Path | str = config.DB_PATH,
    out_path: Path | str = config.CASES_JSON,
    model: str = config.EXTRACT_MODEL,
    _fetch: Callable[..., dict] | None = None,
    _complete: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    fetch = _fetch or monobank.fetch_jar
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    conn = store.connect(db_path)
    store.init_db(conn)

    stored = 0
    problems: dict[str, list[str]] = {}
    for entry in seed:
        actor = Actor(id=entry["actor_id"], name=entry["actor_name"], type=entry["actor_type"])
        store.upsert_actor(conn, actor)
        jar_id = entry["jar_id"]
        raw = fetch(jar_id)
        source = Source(url=raw["url"], type="structured", tier=1,
                        access="public", license="unknown", actor_id=actor.id)
        store.upsert_source(conn, source)
        case = extract.extract_case(raw, source, case_id=entry["case_id"],
                                    actor_id=actor.id, model=model, _complete=_complete)
        case_problems = validate.validate_case(case)
        if case_problems:
            problems[case.id] = case_problems
        store.upsert_case(conn, case)
        stored += 1

    exported = export.export_cases(conn, out_path)
    return {"stored": stored, "exported": exported, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    seed_path = Path(argv[0]) if argv else config.SEEDS_DIR / "p0_seed.json"
    result = run_pipeline(seed_path)
    print(f"stored={result['stored']} exported={result['exported']} "
          f"problems={len(result['problems'])}")
    for cid, probs in result["problems"].items():
        print(f"  [{cid}] {probs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add data/seeds/p0_seed.json src/fundrec/cli.py tests/test_cli.py
git commit -m "feat: P0 pipeline CLI (seed->collect->extract->validate->store->export)"
```

---

## Task 10: Full suite green + README + live-run note

**Files:**
- Create: `README.md`
- Modify: none

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1–9 green.

- [ ] **Step 2: Run ruff**

Run: `ruff check src tests`
Expected: no errors (fix any reported, re-run).

- [ ] **Step 3: Write README**

```markdown
# fundrising_recon

База кейсів фандрайзингу України часів війни (2022→2026) для маркет-ресьорчу:
що перформить у 2026, а що ні. Автозбір у дусі Recon — кожне число з провенансом
і рівнем довіри. Дизайн: `docs/superpowers/specs/2026-06-07-fundrising-recon-design.md`.

## Стек
Python 3.12, SQLite, httpx, Claude Agent SDK (екстракція). Тести: pytest.

## Розробка
```bash
pip install -e ".[dev]"
python -m pytest -v
```

## P0 пайплайн (наскрізний зріз)
```bash
python -m fundrec.cli data/seeds/p0_seed.json
# seed -> Monobank jar -> LLM extract -> validate -> SQLite -> data/cases.json
```

## Статус
P0 (кістяк) — наскрізний потік на 1 колекторі (Monobank jar). Далі: P1 (колектори
звітів/новин/соц + Discoverer + дедуп), P2 (критик), P3 (4 осі + тренди), P4 (кокпіт).

## Жива екстракція
`_live_complete` у `extract.py` викликає Claude Agent SDK на підписці. Перед першим
живим запуском підтвердити реальний формат JSON-ендпоінта банки Monobank (spec §10):
`JAR_JSON_URL` у `collect/monobank.py`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README + P0 status and live-run note"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-Review (виконано автором плану)

**Spec coverage:**
- §3 архітектура/стек → Tasks 1–9 (структура `fundrec`, SQLite, httpx, Agent SDK).
- §4 модель `Case`/`Actor`/`Source` + provenance → Task 3, 4.
- §5 COLLECT (Monobank) → Task 5; EXTRACT з обовʼязковим provenance → Task 7.
- §5 «4 рубежі»: дедуп (P1), крос-чек (P2), **детерміновані валідатори → Task 6**, критик (P2). P0 покриває рубіж 3; решта — наступні плани (зафіксовано у scope-note).
- §8 інваріант 1 (provenance на непорожні числа) + рік/суми/словники → Task 6 валідатори; інваріант 5 (virality null) — у P3/ANALYZE, де рахуються осі; 3/4 (access/license) присутні в `Source` (наповнюються повноцінно в P1 разом із `probe_access`).
- §6 осі/тренди, §7 кокпіт → P3/P4 (не в цьому плані; поля осей зарезервовані nullable у Task 3).
- §9 P0 обсяг → весь план.

**Placeholder scan:** код повний у кожному кроці; `_live_complete` і реальний JSON-ендпоінт Monobank свідомо позначені як live-recon (spec §10), не плейсхолдери логіки — тести не залежать від них.

**Type consistency:** `Case`/`Actor`/`Source` поля однакові скрізь; `parse_extraction(... case_id, actor_id, model)`, `extract_case(... case_id, actor_id, model, _complete)`, `run_pipeline(... _fetch, _complete)`, `monobank.parse_jar(jar_id, payload)`/`fetch_jar(jar_id, _client)`, `store.upsert_case/load_cases`, `export.export_cases(conn, out_path)`, `validate.validate_case(case) -> list[str]` — узгоджені між задачами.
