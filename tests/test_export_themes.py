"""Test that export_cases enriches campaign dicts with `themes`."""
from __future__ import annotations

import json

from fundrec import export, store
from fundrec.schema import Actor, Campaign, Case, Source


def _setup(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="ЗСУ", type="foundation"))
    store.upsert_source(conn, Source(
        url="https://example.com", type="structured", tier=1,
        access="public", license="unknown", actor_id="a1",
    ))
    store.upsert_case(conn, Case(
        id="c1", title="Test", actor_id="a1",
        url="https://example.com", goal="military",
    ))
    return conn


def test_export_themes_fpv(tmp_path):
    """Campaign with FPV title → exported dict has 'fpv' in themes."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1",
        title="Збір на FPV для ЗСУ",
        goal="military/fpv", type="online_ad",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "themes" in camp
    assert "fpv" in camp["themes"]


def test_export_themes_uses_playbook_note(tmp_path):
    """Theme derived from playbook_note when title is generic."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k2", actor_id="a1",
        title="Допоможи ЗСУ",
        goal="military", type="organic_social",
        playbook_note="Збираємо на старлінк і рацію для зв'язку",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "comms" in camp["themes"]


def test_export_themes_empty_when_no_match(tmp_path):
    """Generic title with no keywords → themes is empty list."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k3", actor_id="a1",
        title="Підтримай бійців",
        goal="military", type="organic_social",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert camp["themes"] == []


def test_export_themes_present_for_all_campaigns(tmp_path):
    """All exported campaign dicts have a `themes` key."""
    conn = _setup(tmp_path)
    for i, title in enumerate(["FPV збір", "медична допомога", "генератори"]):
        store.upsert_campaign(conn, Campaign(
            id=f"k{i}", actor_id="a1", title=title,
            goal="military", type="organic_social",
        ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for camp in data["campaigns"]:
        assert "themes" in camp, f"Missing 'themes' key in campaign {camp['id']}"
