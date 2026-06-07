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
