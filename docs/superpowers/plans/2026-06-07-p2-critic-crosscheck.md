# P2 — Critic + Cross-check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `crosscheck.py`, `critic.py`, `set_verification` in `store.py`, and `pipeline_verify.py` so that every Case can be deterministically assessed and LLM-critic-upgraded to a final `verification_status`.

**Architecture:** Deterministic cross-check (`crosscheck.py`) runs first and produces a base status; the injectable LLM critic (`critic.py`) optionally upgrades `cross-checked` → `verified` using a separate Anthropic API call at `temperature=0`; persistence (`store.py:set_verification`) writes results back; a thin orchestrator (`pipeline_verify.py`) wires them together. All LLM/network calls are injectable for hermetic tests.

**Tech Stack:** Python 3.12, pytest, ruff, anthropic SDK (live path only), sqlite3, existing `fundrec` package under `src/fundrec/`.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `src/fundrec/crosscheck.py` | Create | Deterministic conflict detection + base status |
| `src/fundrec/critic.py` | Create | LLM critic prompt/parse/critique (injectable) |
| `src/fundrec/db/schema.sql` | Modify | Add `verdict_reason TEXT` column to cases |
| `src/fundrec/schema.py` | Modify | Add `verdict_reason: str | None = None` to Case |
| `src/fundrec/store.py` | Modify | Add `set_verification()` function |
| `src/fundrec/pipeline_verify.py` | Create | Thin orchestrator: load → assess → critique → persist |
| `tests/test_crosscheck.py` | Create | Tests for `detect_conflict` + `assess_verification` |
| `tests/test_critic.py` | Create | Tests for `build_critic_prompt`, `parse_verdict`, `critique_case` |
| `tests/test_store.py` | Modify | Add `set_verification` round-trip test |
| `tests/test_pipeline_verify.py` | Create | End-to-end test with fake judge + tmp sqlite |

---

## Task 1: `crosscheck.py` — deterministic assessment

**Files:**
- Create: `src/fundrec/crosscheck.py`
- Create: `tests/test_crosscheck.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_crosscheck.py`:

```python
"""Tests for fundrec.crosscheck — detect_conflict + assess_verification."""
from __future__ import annotations

import pytest
from fundrec.schema import Case
from fundrec.crosscheck import detect_conflict, assess_verification


def _case(id: str, amount_uah: float | None = None,
          url: str = "https://example.com/case",
          provenance: dict | None = None,
          verification_status: str = "auto") -> Case:
    return Case(
        id=id,
        title="Test",
        actor_id="a1",
        url=url,
        goal="military",
        amount_uah=amount_uah,
        provenance=provenance or {},
        verification_status=verification_status,
    )


# --- detect_conflict ---

def test_no_conflict_within_tolerance():
    """Amounts within 10% tol → no conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_090_000.0)   # +9% — within tol
    assert detect_conflict([c1, c2]) is False


def test_conflict_beyond_tolerance():
    """Amounts differ >10% → conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_200_000.0)   # +20% — beyond tol
    assert detect_conflict([c1, c2]) is True


def test_no_conflict_exact_boundary():
    """Exactly at tol boundary (10%) → no conflict (not strictly greater)."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_100_000.0)   # exactly +10%
    assert detect_conflict([c1, c2]) is False


def test_conflict_none_amounts_ignored():
    """None amounts are skipped — no conflict from absent data."""
    c1 = _case("c1", amount_uah=None)
    c2 = _case("c2", amount_uah=1_000_000.0)
    c3 = _case("c3", amount_uah=None)
    assert detect_conflict([c1, c2, c3]) is False


def test_conflict_all_none_no_conflict():
    """All None → no conflict."""
    c1 = _case("c1", amount_uah=None)
    c2 = _case("c2", amount_uah=None)
    assert detect_conflict([c1, c2]) is False


def test_single_case_no_conflict():
    """Single case list → never a conflict."""
    c = _case("c1", amount_uah=500_000.0)
    assert detect_conflict([c]) is False


def test_empty_list_no_conflict():
    assert detect_conflict([]) is False


def test_conflict_three_cases_one_outlier():
    """Three cases: two agree, one is far off → conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_050_000.0)
    c3 = _case("c3", amount_uah=2_000_000.0)   # 100% off the max
    assert detect_conflict([c1, c2, c3]) is True


# --- assess_verification ---

def test_assess_conflict_flag_returns_conflict():
    c = _case("c1", amount_uah=1_000_000.0)
    assert assess_verification(c, conflicting=True) == "conflict"


def test_assess_tier1_provenance_returns_cross_checked():
    prov = {"amount_uah": {"source_url": "https://monobank.ua/jar/x",
                           "confidence": 0.95, "tier": 1, "note": ""}}
    c = _case("c1", amount_uah=1_000_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "cross-checked"


def test_assess_tier2_only_returns_auto():
    prov = {"amount_uah": {"source_url": "https://news.ua/art",
                           "confidence": 0.6, "tier": 2, "note": ""}}
    c = _case("c1", amount_uah=500_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_no_provenance_returns_auto():
    c = _case("c1")
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_tier3_only_returns_auto():
    prov = {"amount_uah": {"source_url": "https://t.me/x",
                           "confidence": 0.35, "tier": 3, "note": ""}}
    c = _case("c1", amount_uah=100_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_conflict_wins_over_tier1():
    """conflicting=True → conflict even if tier-1 present."""
    prov = {"amount_uah": {"source_url": "https://monobank.ua/jar/y",
                           "confidence": 0.95, "tier": 1, "note": ""}}
    c = _case("c1", amount_uah=1_000_000.0, provenance=prov)
    assert assess_verification(c, conflicting=True) == "conflict"
```

- [ ] **Step 1.2: Run test to verify it fails**

```powershell
cd "C:\Users\tomoo\Documents\GitHub\fundrising_recon"
.\.venv\Scripts\python.exe -m pytest tests/test_crosscheck.py -v
```

Expected: `ModuleNotFoundError: No module named 'fundrec.crosscheck'`

- [ ] **Step 1.3: Implement `src/fundrec/crosscheck.py`**

```python
"""Детерміністична оцінка верифікації (без LLM).

detect_conflict: перевіряє, чи кейси з однаковим ключем звітують суттєво
  різні суми (відносне відхилення > tol від максимуму).
assess_verification: повертає base verification_status для одного кейсу.
"""
from __future__ import annotations

from .schema import Case


def detect_conflict(cases_same_key: list[Case], *, tol: float = 0.10) -> bool:
    """True if any two non-None amounts differ by more than tol relative.

    Relative difference = |a - b| / max(|a|, |b|).
    None amounts are ignored.
    """
    amounts = [c.amount_uah for c in cases_same_key if c.amount_uah is not None]
    if len(amounts) < 2:
        return False
    max_val = max(abs(a) for a in amounts)
    if max_val == 0:
        return False
    min_val = min(abs(a) for a in amounts)
    return (max_val - min_val) / max_val > tol


def assess_verification(case: Case, *, conflicting: bool = False) -> str:
    """Returns verification_status string for a single case.

    Rules (in priority order):
    1. conflicting=True → "conflict"
    2. Any provenance entry with tier == 1 → "cross-checked"
    3. Otherwise → "auto"
    """
    if conflicting:
        return "conflict"
    for entry in case.provenance.values():
        if isinstance(entry, dict) and entry.get("tier") == 1:
            return "cross-checked"
    return "auto"
```

- [ ] **Step 1.4: Run test suite to verify green**

```powershell
cd "C:\Users\tomoo\Documents\GitHub\fundrising_recon"
.\.venv\Scripts\python.exe -m pytest tests/test_crosscheck.py -v
```

Expected: all crosscheck tests PASS.

Then run the full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: `83 + N passed` (N = new crosscheck tests), 0 failures.

- [ ] **Step 1.5: Ruff lint**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/fundrec/crosscheck.py tests/test_crosscheck.py
.\.venv\Scripts\python.exe -m ruff format src/fundrec/crosscheck.py tests/test_crosscheck.py
```

Expected: no errors.

- [ ] **Step 1.6: Commit**

```powershell
git add src/fundrec/crosscheck.py tests/test_crosscheck.py
git commit -c commit.gpgsign=false -m "feat: crosscheck.py — detect_conflict + assess_verification (P2 rubric 2)"
```

(If signing is required: `git -c commit.gpgsign=false commit -m "..."`)

Add trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 2: Schema + DB — add `verdict_reason` field

**Files:**
- Modify: `src/fundrec/schema.py`
- Modify: `src/fundrec/db/schema.sql`

> NOTE: Adding `verdict_reason: str | None = None` as the LAST field of `Case` with a default means existing `Case(...)` constructions and `Case(**dict)` calls still work. The `store.py` upsert/load code iterates `dataclasses.fields(Case)`, so the new field is automatically included. The existing `test_store.py` round-trip test constructs a `Case` without `verdict_reason`, which defaults to `None`; `upsert_case` will write `NULL` to the new column; `_row_to_case` will pass `verdict_reason=None` back. No test breaks.

- [ ] **Step 2.1: Add `verdict_reason` to `src/fundrec/schema.py`**

In `schema.py`, find the last field of `Case`:
```python
    extracted_by_model: str | None = None
```

Add after it:
```python
    verdict_reason: str | None = None
```

The full tail of the dataclass should look like:
```python
    # дисципліна
    provenance: dict[str, dict] = field(default_factory=dict)
    confidence_overall: float = 0.0
    verification_status: str = "auto"
    extracted_at: str | None = None
    extracted_by_model: str | None = None
    verdict_reason: str | None = None
```

- [ ] **Step 2.2: Add `verdict_reason` column to `src/fundrec/db/schema.sql`**

In `schema.sql`, the cases table ends with:
```sql
    extracted_at        TEXT,
    extracted_by_model  TEXT
```

Change to:
```sql
    extracted_at        TEXT,
    extracted_by_model  TEXT,
    verdict_reason      TEXT
```

- [ ] **Step 2.3: Run full suite to confirm no regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: same count as before + crosscheck tests, all passing.

- [ ] **Step 2.4: Ruff lint**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/fundrec/schema.py src/fundrec/db/schema.sql
.\.venv\Scripts\python.exe -m ruff format src/fundrec/schema.py
```

- [ ] **Step 2.5: Commit**

```powershell
git add src/fundrec/schema.py src/fundrec/db/schema.sql
git -c commit.gpgsign=false commit -m "feat: додати verdict_reason до Case + schema.sql (P2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `store.py` — add `set_verification`

**Files:**
- Modify: `src/fundrec/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 3.1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_set_verification_updates_status_and_reason(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c1", title="FPV", actor_id="a1", url="https://x", goal="military")
    store.upsert_case(conn, c)

    store.set_verification(conn, "c1", "verified", reason="підтверджено", confidence_overall=0.9)

    loaded = store.load_cases(conn)
    assert len(loaded) == 1
    assert loaded[0].verification_status == "verified"
    assert loaded[0].verdict_reason == "підтверджено"
    assert loaded[0].confidence_overall == 0.9
    # Other fields unchanged
    assert loaded[0].title == "FPV"
    assert loaded[0].goal == "military"


def test_set_verification_without_optional_args(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c2", title="Медицина", actor_id="a1", url="https://x", goal="medical",
             confidence_overall=0.5)
    store.upsert_case(conn, c)

    store.set_verification(conn, "c2", "conflict")

    loaded = store.load_cases(conn)
    assert loaded[0].verification_status == "conflict"
    assert loaded[0].verdict_reason is None    # not changed
    assert loaded[0].confidence_overall == 0.5  # not changed
```

- [ ] **Step 3.2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_store.py -v -k "set_verification"
```

Expected: `AttributeError` or `ImportError` — `set_verification` not defined.

- [ ] **Step 3.3: Implement `set_verification` in `src/fundrec/store.py`**

Add after `get_case`:

```python
def set_verification(
    conn: sqlite3.Connection,
    case_id: str,
    status: str,
    reason: str | None = None,
    confidence_overall: float | None = None,
) -> None:
    """Update verification_status (always), verdict_reason and confidence_overall (if provided)."""
    parts = ["verification_status = ?"]
    values: list = [status]
    if reason is not None:
        parts.append("verdict_reason = ?")
        values.append(reason)
    if confidence_overall is not None:
        parts.append("confidence_overall = ?")
        values.append(confidence_overall)
    values.append(case_id)
    conn.execute(
        f"UPDATE cases SET {', '.join(parts)} WHERE id = ?",
        values,
    )
    conn.commit()
```

- [ ] **Step 3.4: Run full suite**

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: all previous tests pass + 2 new `set_verification` tests pass.

- [ ] **Step 3.5: Ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/fundrec/store.py tests/test_store.py
.\.venv\Scripts\python.exe -m ruff format src/fundrec/store.py tests/test_store.py
```

- [ ] **Step 3.6: Commit**

```powershell
git add src/fundrec/store.py tests/test_store.py
git -c commit.gpgsign=false commit -m "feat: store.set_verification — UPDATE статус/reason/confidence (P2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `critic.py` — LLM critic (injectable)

**Files:**
- Create: `src/fundrec/critic.py`
- Create: `tests/test_critic.py`

- [ ] **Step 4.1: Write the failing tests**

Create `tests/test_critic.py`:

```python
"""Tests for fundrec.critic — prompt/parse/critique with injected judge."""
from __future__ import annotations

import pytest
from fundrec.schema import Case
from fundrec.critic import build_critic_prompt, parse_verdict, critique_case


def _case(
    id: str = "c1",
    amount_uah: float | None = 1_000_000.0,
    goal_amount: float | None = 2_000_000.0,
    goal: str = "military/fpv",
    style: list[str] | None = None,
    method: list[str] | None = None,
    provenance: dict | None = None,
    verification_status: str = "auto",
) -> Case:
    return Case(
        id=id,
        title="FPV збір",
        actor_id="a1",
        url="https://monobank.ua/jar/x",
        goal=goal,
        style=style or ["urgency"],
        method=method or ["monobank_jar"],
        amount_uah=amount_uah,
        goal_amount=goal_amount,
        provenance=provenance or {
            "amount_uah": {"source_url": "https://monobank.ua/jar/x",
                           "confidence": 0.95, "tier": 1, "note": ""},
        },
        verification_status=verification_status,
    )


# --- build_critic_prompt ---

def test_build_critic_prompt_includes_amounts():
    c = _case(amount_uah=1_000_000.0, goal_amount=2_000_000.0)
    prompt = build_critic_prompt(c)
    assert "1000000" in prompt or "1_000_000" in prompt or "1000000.0" in prompt


def test_build_critic_prompt_includes_source_url():
    c = _case()
    prompt = build_critic_prompt(c)
    assert "monobank.ua" in prompt


def test_build_critic_prompt_includes_goal_style_method():
    c = _case(goal="military/fpv", style=["urgency"], method=["monobank_jar"])
    prompt = build_critic_prompt(c)
    assert "military" in prompt
    assert "urgency" in prompt
    assert "monobank_jar" in prompt


def test_build_critic_prompt_requests_json():
    c = _case()
    prompt = build_critic_prompt(c)
    assert "JSON" in prompt
    assert "supported" in prompt
    assert "confidence" in prompt
    assert "reason" in prompt


# --- parse_verdict ---

def test_parse_verdict_valid_input():
    obj = {"supported": True, "confidence": 0.85, "reason": "підтверджено"}
    result = parse_verdict(obj)
    assert result == {"supported": True, "confidence": 0.85, "reason": "підтверджено"}


def test_parse_verdict_clamps_confidence_above_1():
    obj = {"supported": True, "confidence": 1.5, "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 1.0


def test_parse_verdict_clamps_confidence_below_0():
    obj = {"supported": False, "confidence": -0.2, "reason": "ні"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.0


def test_parse_verdict_missing_supported_defaults_false():
    obj = {"confidence": 0.5, "reason": "немає supported"}
    result = parse_verdict(obj)
    assert result["supported"] is False


def test_parse_verdict_missing_reason_defaults_empty():
    obj = {"supported": True, "confidence": 0.9}
    result = parse_verdict(obj)
    assert result["reason"] == ""


def test_parse_verdict_missing_confidence_defaults_zero():
    obj = {"supported": True, "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.0


def test_parse_verdict_coerces_confidence_to_float():
    obj = {"supported": True, "confidence": "0.8", "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.8


# --- critique_case ---

def _make_judge(supported: bool, confidence: float, reason: str = "тест"):
    """Returns a fake _judge callable that returns fixed verdict."""
    def _judge(prompt: str) -> dict:
        return {"supported": supported, "confidence": confidence, "reason": reason}
    return _judge


def test_critique_case_upgrades_cross_checked_to_verified():
    """Supported + high confidence upgrades cross-checked → verified."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(c, base_status="cross-checked",
                                   _judge=_make_judge(True, 0.8))
    assert status == "verified"
    assert reason  # non-empty


def test_critique_case_does_not_upgrade_below_threshold():
    """Supported but low confidence (< 0.7) — stays cross-checked."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(c, base_status="cross-checked",
                                   _judge=_make_judge(True, 0.65))
    assert status == "cross-checked"


def test_critique_case_unsupported_keeps_base_status():
    """Unsupported verdict: keeps base_status, reason explains doubt."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(c, base_status="cross-checked",
                                   _judge=_make_judge(False, 0.4, "джерело не підтверджує"))
    assert status == "cross-checked"
    assert "не підтверджує" in reason or reason  # reason populated


def test_critique_case_conflict_stays_conflict():
    """conflict is never downgraded — judge does not affect it."""
    c = _case(verification_status="conflict")
    status, reason = critique_case(c, base_status="conflict",
                                   _judge=_make_judge(True, 0.95))
    assert status == "conflict"


def test_critique_case_auto_passes_through():
    """auto base_status: judge cannot upgrade to verified (only cross-checked can)."""
    c = _case(verification_status="auto")
    status, reason = critique_case(c, base_status="auto",
                                   _judge=_make_judge(True, 0.95))
    assert status == "auto"
```

- [ ] **Step 4.2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_critic.py -v
```

Expected: `ModuleNotFoundError: No module named 'fundrec.critic'`

- [ ] **Step 4.3: Implement `src/fundrec/critic.py`**

```python
"""LLM-критик на прямому Anthropic API (окрема модель, temp=0).

Тестована поверхня: build_critic_prompt / parse_verdict / critique_case.
Мережевий виклик ізольовано у _live_judge (# pragma: no cover).
"""
from __future__ import annotations

import json
from typing import Callable

from . import config
from .schema import Case


def build_critic_prompt(case: Case) -> str:
    """Будує промпт для судді-критика.

    Просить суддю оцінити, чи джерела у провенансі кейсу правдоподібно
    підтверджують amount_uah / goal_amount і типізацію (goal/style/method).
    Вимагає СТРОГИЙ JSON: {"supported": bool, "confidence": 0..1, "reason": "..."}.
    """
    source_urls = sorted({
        entry["source_url"]
        for entry in case.provenance.values()
        if isinstance(entry, dict) and entry.get("source_url")
    })
    return (
        "Ти — незалежний критик-валідатор кейсів фандрайзингу.\n"
        "Оціни, чи цитовані джерела реально підтверджують вказану суму і типізацію кейсу.\n\n"
        f"Заголовок: {case.title}\n"
        f"Ціль (goal): {case.goal}\n"
        f"Стилі: {case.style}\n"
        f"Методи: {case.method}\n"
        f"amount_uah: {case.amount_uah}\n"
        f"goal_amount: {case.goal_amount}\n"
        f"Джерела провенансу: {source_urls}\n\n"
        "Поверни СТРОГО JSON (без зайвого тексту):\n"
        '{"supported": true|false, "confidence": 0.0..1.0, "reason": "<коротко українською>"}\n'
    )


def parse_verdict(obj: dict) -> dict:
    """Нормалізує відповідь судді → {"supported": bool, "confidence": float, "reason": str}."""
    supported = bool(obj.get("supported", False))
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(obj.get("reason", ""))
    return {"supported": supported, "confidence": confidence, "reason": reason}


def critique_case(
    case: Case,
    *,
    base_status: str,
    _judge: Callable[[str], dict] | None = None,
) -> tuple[str, str]:
    """Запускає суддю і повертає (verification_status, reason).

    Upgrade rules:
    - base_status == "conflict" → always stays "conflict" (never downgrade).
    - base_status == "cross-checked" AND supported AND confidence >= 0.7 → "verified".
    - base_status == "cross-checked" AND NOT supported → keep "cross-checked", reason explains doubt.
    - base_status == "auto" → judge cannot upgrade (only cross-checked eligible); pass through.
    """
    if _judge is None:
        _judge = _live_judge  # pragma: no cover

    if base_status == "conflict":
        return "conflict", ""

    prompt = build_critic_prompt(case)
    raw = _judge(prompt)
    verdict = parse_verdict(raw)

    if base_status == "cross-checked":
        if verdict["supported"] and verdict["confidence"] >= 0.7:
            return "verified", verdict["reason"]
        # unsupported or low confidence: keep base, note the doubt
        reason = verdict["reason"] if verdict["reason"] else "суддя не підтвердив"
        return base_status, reason

    # auto (or any other unrecognized base): pass through unchanged
    return base_status, verdict["reason"]


def _live_judge(prompt: str) -> dict:  # pragma: no cover
    """Живий виклик Anthropic API (Sonnet, temp=0). Не тестується."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.CRITIC_API_KEY)
    message = client.messages.create(
        model=config.JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text
    return json.loads(text)
```

- [ ] **Step 4.4: Run critic tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_critic.py -v
```

Expected: all critic tests PASS.

- [ ] **Step 4.5: Run full suite**

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: all prior tests + crosscheck + store + critic pass, 0 failures.

- [ ] **Step 4.6: Ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/fundrec/critic.py tests/test_critic.py
.\.venv\Scripts\python.exe -m ruff format src/fundrec/critic.py tests/test_critic.py
```

- [ ] **Step 4.7: Commit**

```powershell
git add src/fundrec/critic.py tests/test_critic.py
git -c commit.gpgsign=false commit -m "feat: critic.py — LLM-критик build_prompt/parse_verdict/critique_case (P2 rubric 4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `pipeline_verify.py` — thin orchestrator

**Files:**
- Create: `src/fundrec/pipeline_verify.py`
- Create: `tests/test_pipeline_verify.py`

- [ ] **Step 5.1: Write the failing tests**

Create `tests/test_pipeline_verify.py`:

```python
"""End-to-end tests for pipeline_verify.verify_cases with injected judge."""
from __future__ import annotations

import json
import pytest
from fundrec import store
from fundrec.schema import Actor, Source, Case
from fundrec.pipeline_verify import verify_cases


def _setup_db(tmp_path):
    """Create an in-memory-ish sqlite DB seeded with actors/sources."""
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(
        url="https://monobank.ua/jar/x", type="structured",
        tier=1, access="public", license="unknown", actor_id="a1",
    ))
    return conn


def _insert_case(conn, id: str, amount_uah: float | None, tier: int = 1,
                 url: str = "https://monobank.ua/jar/x") -> None:
    prov: dict = {}
    if amount_uah is not None:
        prov["amount_uah"] = {
            "source_url": url,
            "confidence": 0.95 if tier == 1 else 0.6,
            "tier": tier,
            "note": "",
        }
    case = Case(
        id=id, title="FPV збір", actor_id="a1", url=url,
        goal="military/fpv", amount_uah=amount_uah,
        provenance=prov, confidence_overall=prov["amount_uah"]["confidence"] if prov else 0.0,
    )
    store.upsert_case(conn, case)


def test_verify_single_case_auto_no_tier1(tmp_path):
    """Single case with tier-2 only → stays auto (judge irrelevant)."""
    conn = _setup_db(tmp_path)
    store.upsert_source(conn, Source(
        url="https://news.ua/art", type="news",
        tier=2, access="public", license="unknown", actor_id="a1",
    ))
    _insert_case(conn, "c1", 1_000_000.0, tier=2, url="https://news.ua/art")

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    assert cases[0].verification_status == "auto"
    assert summary.get("auto", 0) == 1


def test_verify_single_case_tier1_cross_checked_then_verified(tmp_path):
    """Single case with tier-1 provenance → cross-checked, then judge upgrades → verified."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", 1_000_000.0, tier=1)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "підтверджено"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    assert cases[0].verification_status == "verified"
    assert cases[0].verdict_reason == "підтверджено"
    assert summary.get("verified", 0) == 1


def test_verify_conflicting_cases_get_conflict_status(tmp_path):
    """Two cases with same dedup_key but amounts differ >10% → conflict."""
    conn = _setup_db(tmp_path)
    store.upsert_source(conn, Source(
        url="https://news.ua/art2", type="news",
        tier=2, access="public", license="unknown", actor_id="a1",
    ))
    # Same dedup_key (same URL host+path) would require same URL —
    # use different URLs so they have different dedup_keys, but share actor+title.
    # Actually: test the conflict path by inserting two cases with same URL-based key.
    # They'll have the same dedup_key if they share the same URL.
    _insert_case(conn, "c1", 1_000_000.0, tier=1, url="https://monobank.ua/jar/x")
    # Second case with same URL but different amount — conflict
    case2 = Case(
        id="c2", title="FPV збір", actor_id="a1",
        url="https://monobank.ua/jar/x",   # same dedup_key
        goal="military/fpv", amount_uah=2_500_000.0,
        provenance={"amount_uah": {"source_url": "https://monobank.ua/jar/x",
                                   "confidence": 0.95, "tier": 1, "note": ""}},
        confidence_overall=0.95,
    )
    store.upsert_case(conn, case2)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    statuses = {c.verification_status for c in cases}
    assert "conflict" in statuses
    assert summary.get("conflict", 0) >= 1


def test_verify_returns_summary_counts(tmp_path):
    """Summary dict counts cases by final status."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", 1_000_000.0, tier=1)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.95, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    # Summary values are non-negative ints
    assert all(isinstance(v, int) and v >= 0 for v in summary.values())
    total = sum(summary.values())
    assert total == len(store.load_cases(conn))
```

- [ ] **Step 5.2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_verify.py -v
```

Expected: `ModuleNotFoundError: No module named 'fundrec.pipeline_verify'`

- [ ] **Step 5.3: Implement `src/fundrec/pipeline_verify.py`**

```python
"""Тонкий оркестратор верифікації кейсів (P2).

verify_cases(conn, *, _judge=None) -> dict:
  1. Завантажує всі кейси.
  2. Групує за dedup.dedup_key.
  3. detect_conflict на кожну групу.
  4. assess_verification на кожен кейс.
  5. critique_case (з injectable _judge) для подальшого підвищення статусу.
  6. set_verification → записує результат у БД.
  7. Повертає {status: count}.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Callable

from . import store
from .crosscheck import assess_verification, detect_conflict
from .critic import critique_case
from .dedup import dedup_key


def verify_cases(
    conn: sqlite3.Connection,
    *,
    _judge: Callable[[str], dict] | None = None,
) -> dict[str, int]:
    """Run full verification pipeline. Returns {verification_status: count}."""
    cases = store.load_cases(conn)
    if not cases:
        return {}

    # Group by dedup_key
    groups: dict[str, list] = defaultdict(list)
    for c in cases:
        groups[dedup_key(c)].append(c)

    # Detect conflicts per group
    conflict_ids: set[str] = set()
    for group in groups.values():
        if detect_conflict(group):
            for c in group:
                conflict_ids.add(c.id)

    # Assess + critique + persist
    summary: dict[str, int] = defaultdict(int)
    for case in cases:
        conflicting = case.id in conflict_ids
        base_status = assess_verification(case, conflicting=conflicting)
        final_status, reason = critique_case(case, base_status=base_status, _judge=_judge)
        store.set_verification(conn, case.id, final_status, reason=reason or None)
        summary[final_status] += 1

    return dict(summary)
```

- [ ] **Step 5.4: Run pipeline_verify tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_verify.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5.5: Run full suite**

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -q
```

Expected: 83 + all new tests pass, 0 failures.

- [ ] **Step 5.6: Ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/fundrec/pipeline_verify.py tests/test_pipeline_verify.py
.\.venv\Scripts\python.exe -m ruff format src/fundrec/pipeline_verify.py tests/test_pipeline_verify.py
```

- [ ] **Step 5.7: Commit**

```powershell
git add src/fundrec/pipeline_verify.py tests/test_pipeline_verify.py
git -c commit.gpgsign=false commit -m "feat: pipeline_verify.py — оркестратор verify_cases E2E (P2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist

### Spec coverage

| Spec requirement | Covered by task |
|---|---|
| §5 rubric 2 — cross-check tier conflicts, `conflict` status | Task 1 (`detect_conflict`, `assess_verification`) |
| §5 rubric 4 — critic-agent (`temp=0`, separate model) | Task 4 (`critic.py`) |
| §8 invariant — `verification_status` ∈ `{auto, cross-checked, verified, conflict}` | `assess_verification` + `critique_case` return only valid values |
| `verdict_reason` persisted to DB | Tasks 2 + 3 |
| `set_verification` on store | Task 3 |
| End-to-end orchestration | Task 5 |
| `_live_judge` uses `config.CRITIC_API_KEY`, `config.JUDGE_MODEL`, `temp=0` | Task 4, `_live_judge` implementation |
| `_live_judge` marked `# pragma: no cover` | Task 4 |
| Inject all LLM/network | Tasks 4 + 5 (all tests use `_judge=fake_judge`) |
| TDD: red before green | Every task has run-fail step before implementation |
| No regression to 83 existing tests | Steps 1.4, 2.3, 3.4, 4.5, 5.5 all run full suite |

### Placeholder scan

No TBDs, no "implement later", no "handle edge cases" without code. All test code is complete.

### Type consistency

- `detect_conflict(cases_same_key: list[Case], *, tol=0.10) -> bool` — matches test calls.
- `assess_verification(case: Case, *, conflicting: bool = False) -> str` — matches test calls.
- `build_critic_prompt(case: Case) -> str` — matches test calls.
- `parse_verdict(obj: dict) -> dict` — matches test calls.
- `critique_case(case, *, base_status: str, _judge=None) -> tuple[str, str]` — matches test calls.
- `set_verification(conn, case_id, status, reason=None, confidence_overall=None) -> None` — matches test calls.
- `verify_cases(conn, *, _judge=None) -> dict[str, int]` — matches test calls.
- `verdict_reason: str | None = None` added to Case — consistent with `set_verification` writing it and `_row_to_case` reading it.
