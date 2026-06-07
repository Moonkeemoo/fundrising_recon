"""Тести Unit 3: збагачення export_cases velocity з jars_cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fundrec import export, store
from fundrec.schema import Actor, Campaign, Case, Source


_TS_DAY0 = "2024-01-01T10:00:00+00:00"
_TS_DAY1 = "2024-01-02T10:00:00+00:00"


def _setup_db(tmp_path: Path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Тест", type="individual"))
    store.upsert_source(conn, Source(
        url="https://x", type="structured", tier=1, access="public",
        license="unknown", actor_id="a1",
    ))
    store.upsert_case(conn, Case(
        id="c1", title="FPV", actor_id="a1", url="https://x",
        goal="military", style=[], method=[],
    ))
    return conn


def _jar_campaign(tmp_path: Path, conn):
    """Додає кампанію із jar-провенансом."""
    jar_id = "TESTJAR123"
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1", title="Збір FPV", goal="military/fpv",
        type="jar", channels=["telegram"], form_factor=["text"], tone=["urgency"],
        amount_uah=100_000.0, goal_amount=1_000_000.0,
        provenance={
            "amount_uah": {
                "source_url": f"https://send.monobank.ua/jar/{jar_id}",
                "tier": 1,
                "confidence": 0.9,
            }
        },
    ))
    return jar_id


def _write_cache(tmp_path: Path, jar_id: str, history: list[dict]) -> Path:
    cache = {
        jar_id: {
            "jar_id": jar_id,
            "url": f"https://send.monobank.ua/jar/{jar_id}",
            "title": "Банка FPV",
            "amount_uah": history[-1]["amount_uah"] if history else None,
            "goal_amount": 1_000_000.0,
            "history": history,
        }
    }
    p = tmp_path / "jars_cache.json"
    p.write_text(json.dumps(cache), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Тести
# ---------------------------------------------------------------------------


def test_export_velocity_enriched_when_two_snapshots(tmp_path):
    """Кампанія з jar отримує jar_velocity_uah_per_day коли є ≥2 snapshots."""
    conn = _setup_db(tmp_path)
    jar_id = _jar_campaign(tmp_path, conn)
    history = [
        {"ts": _TS_DAY0, "amount_uah": 0.0, "goal_amount": 1_000_000.0},
        {"ts": _TS_DAY1, "amount_uah": 100_000.0, "goal_amount": 1_000_000.0},
    ]
    cache_path = _write_cache(tmp_path, jar_id, history)
    out = tmp_path / "cases.json"

    export.export_cases(conn, out, jars_cache_path=cache_path)
    data = json.loads(out.read_text(encoding="utf-8"))

    camp = next(c for c in data["campaigns"] if c["id"] == "k1")
    assert camp["jar_velocity_uah_per_day"] == pytest.approx(100_000.0)
    assert camp["jar_span_days"] == pytest.approx(1.0)


def test_export_velocity_none_when_one_snapshot(tmp_path):
    """Кампанія з jar отримує None velocity якщо в кеші лише 1 snapshot."""
    conn = _setup_db(tmp_path)
    jar_id = _jar_campaign(tmp_path, conn)
    history = [{"ts": _TS_DAY0, "amount_uah": 50_000.0, "goal_amount": 1_000_000.0}]
    cache_path = _write_cache(tmp_path, jar_id, history)
    out = tmp_path / "cases.json"

    export.export_cases(conn, out, jars_cache_path=cache_path)
    data = json.loads(out.read_text(encoding="utf-8"))

    camp = next(c for c in data["campaigns"] if c["id"] == "k1")
    assert camp["jar_velocity_uah_per_day"] is None
    assert camp["jar_span_days"] is None


def test_export_velocity_none_when_cache_missing(tmp_path):
    """Кампанія без кешу → velocity None (не падає)."""
    conn = _setup_db(tmp_path)
    _jar_campaign(tmp_path, conn)
    missing_cache = tmp_path / "no_such_cache.json"
    out = tmp_path / "cases.json"

    export.export_cases(conn, out, jars_cache_path=missing_cache)
    data = json.loads(out.read_text(encoding="utf-8"))

    camp = next(c for c in data["campaigns"] if c["id"] == "k1")
    assert camp["jar_velocity_uah_per_day"] is None


def test_export_velocity_none_when_no_jar_provenance(tmp_path):
    """Кампанія без jar-провенансу → velocity None."""
    conn = _setup_db(tmp_path)
    # Кампанія без jar URL у провенансі
    store.upsert_campaign(conn, Campaign(
        id="k2", actor_id="a1", title="Без банки", goal="military",
        type="online_ad", channels=["facebook"],
        provenance={"amount_uah": {"source_url": "https://other.example", "tier": 1, "confidence": 0.8}},
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))

    camp = next(c for c in data["campaigns"] if c["id"] == "k2")
    assert camp["jar_velocity_uah_per_day"] is None


def test_export_backward_compat_existing_fields(tmp_path):
    """Всі старі поля кампанії (engagement_rate, rel_resonance, themes) присутні."""
    conn = _setup_db(tmp_path)
    _jar_campaign(tmp_path, conn)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))

    camp = next(c for c in data["campaigns"] if c["id"] == "k1")
    assert "engagement_rate" in camp
    assert "rel_resonance" in camp
    assert "themes" in camp
    # Нові поля також присутні (навіть якщо None)
    assert "jar_velocity_uah_per_day" in camp
    assert "jar_span_days" in camp
