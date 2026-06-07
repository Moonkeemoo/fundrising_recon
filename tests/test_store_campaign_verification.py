"""Тести для fundrec.store — set_campaign_verification (F3)."""
from __future__ import annotations

from fundrec import store
from fundrec.schema import Actor, Campaign, Source


def _seed(conn):
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(
        conn,
        Source(
            url="https://x",
            type="structured",
            tier=1,
            access="public",
            license="unknown",
            actor_id="a1",
        ),
    )


def _make_campaign(id: str = "camp1") -> Campaign:
    return Campaign(
        id=id,
        actor_id="a1",
        title="FPV кампанія",
        goal="military",
        type="online_ad",
        channels=["facebook"],
        confidence_overall=0.5,
    )


def test_set_campaign_verification_updates_status(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    camp = _make_campaign()
    store.upsert_campaign(conn, camp)

    store.set_campaign_verification(conn, "camp1", "verified")

    loaded = store.get_campaign(conn, "camp1")
    assert loaded is not None
    assert loaded.verification_status == "verified"


def test_set_campaign_verification_updates_reason(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    camp = _make_campaign()
    store.upsert_campaign(conn, camp)

    store.set_campaign_verification(conn, "camp1", "verified", reason="підтверджено джерелом")

    loaded = store.get_campaign(conn, "camp1")
    assert loaded.verdict_reason == "підтверджено джерелом"


def test_set_campaign_verification_updates_confidence(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    camp = _make_campaign()
    store.upsert_campaign(conn, camp)

    store.set_campaign_verification(conn, "camp1", "cross-checked", confidence_overall=0.85)

    loaded = store.get_campaign(conn, "camp1")
    assert loaded.verification_status == "cross-checked"
    assert loaded.confidence_overall == 0.85


def test_set_campaign_verification_without_optional_args(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    camp = _make_campaign()
    store.upsert_campaign(conn, camp)

    store.set_campaign_verification(conn, "camp1", "conflict")

    loaded = store.get_campaign(conn, "camp1")
    assert loaded.verification_status == "conflict"
    assert loaded.verdict_reason is None       # не змінювався
    assert loaded.confidence_overall == 0.5    # не змінювався


def test_set_campaign_verification_other_fields_unchanged(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    camp = _make_campaign()
    store.upsert_campaign(conn, camp)

    store.set_campaign_verification(conn, "camp1", "verified", reason="ok", confidence_overall=0.9)

    loaded = store.get_campaign(conn, "camp1")
    assert loaded.title == "FPV кампанія"
    assert loaded.goal == "military"
    assert loaded.type == "online_ad"
