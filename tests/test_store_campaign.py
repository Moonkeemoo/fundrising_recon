"""Тести store CRUD для Campaign/CreativeAsset/Partner (F1)."""
from __future__ import annotations

from fundrec import store
from fundrec.schema import Actor, Campaign, CreativeAsset, Partner


def _seed_actor(conn) -> None:
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))


def _make_campaign(**override) -> Campaign:
    base: dict = dict(
        id="camp1",
        actor_id="a1",
        title="Тест-кампанія",
        goal="military/fpv",
        type="online_ad",
        channels=["facebook", "instagram"],
        form_factor=["video"],
        tone=["emotional", "urgency"],
        partner_ids=[],
        provenance={
            "amount_uah": {"source_url": "https://x", "confidence": 0.9, "tier": 1, "note": ""}
        },
        year=2024,
        amount_uah=500000.0,
        confidence_overall=0.85,
        verification_status="cross-checked",
    )
    base.update(override)
    return Campaign(**base)


def _make_creative(campaign_id: str = "camp1", **override) -> CreativeAsset:
    base: dict = dict(
        id="cr1",
        campaign_id=campaign_id,
        platform="facebook",
        format="video",
        copy_text="Допоможи!",
        views=3200.0,
        provenance={"views": {"source_url": "https://x", "confidence": 0.8, "tier": 2, "note": ""}},
    )
    base.update(override)
    return CreativeAsset(**base)


def _make_partner(pid: str = "p1", **override) -> Partner:
    base: dict = dict(id=pid, name=f"Партнер {pid}", role="sponsor", links=["https://example.com"])
    base.update(override)
    return Partner(**base)


# --- Campaign ---


def test_upsert_and_load_campaign(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign()
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)

    assert len(loaded) == 1
    assert loaded[0] == c


def test_campaign_idempotent_upsert(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign()
    store.upsert_campaign(conn, c)
    c.title = "Оновлено"
    store.upsert_campaign(conn, c)

    loaded = store.load_campaigns(conn)
    assert len(loaded) == 1
    assert loaded[0].title == "Оновлено"


def test_get_campaign(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign()
    store.upsert_campaign(conn, c)

    found = store.get_campaign(conn, "camp1")
    assert found == c

    missing = store.get_campaign(conn, "nope")
    assert missing is None


def test_campaign_list_fields_roundtrip(tmp_path):
    """channels, form_factor, tone, partner_ids збережені і відновлені."""
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign(channels=["facebook", "telegram"], tone=["humor", "heroism"])
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)[0]

    assert loaded.channels == ["facebook", "telegram"]
    assert loaded.tone == ["humor", "heroism"]


# --- Campaign + Partners M:N ---


def test_campaign_with_partners_roundtrip(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    p1 = _make_partner("p1")
    p2 = _make_partner("p2")
    store.upsert_partner(conn, p1)
    store.upsert_partner(conn, p2)

    c = _make_campaign(partner_ids=["p1", "p2"])
    store.upsert_campaign(conn, c)

    loaded = store.load_campaigns(conn)[0]
    assert set(loaded.partner_ids) == {"p1", "p2"}


def test_link_campaign_partner_idempotent(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    p1 = _make_partner("p1")
    store.upsert_partner(conn, p1)

    c = _make_campaign(partner_ids=["p1"])
    store.upsert_campaign(conn, c)

    # Linking again must not raise
    store.link_campaign_partner(conn, "camp1", "p1")

    rows = conn.execute("SELECT * FROM campaign_partners WHERE campaign_id='camp1'").fetchall()
    assert len(rows) == 1


def test_campaign_partner_ids_authoritative_from_join_table(tmp_path):
    """partner_ids у load_campaigns береться з join-таблиці (авторитетне джерело)."""
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    p1 = _make_partner("p1")
    p2 = _make_partner("p2")
    store.upsert_partner(conn, p1)
    store.upsert_partner(conn, p2)

    c = _make_campaign(partner_ids=["p1"])
    store.upsert_campaign(conn, c)
    # Manually add p2 to join table (simulates external link)
    store.link_campaign_partner(conn, "camp1", "p2")

    loaded = store.load_campaigns(conn)[0]
    assert set(loaded.partner_ids) == {"p1", "p2"}


# --- CreativeAsset ---


def test_upsert_and_load_creative(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign(partner_ids=[])
    store.upsert_campaign(conn, c)

    a = _make_creative()
    store.upsert_creative(conn, a)

    loaded = store.load_creatives(conn)
    assert len(loaded) == 1
    assert loaded[0] == a


def test_load_creatives_filtered_by_campaign_id(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c1 = _make_campaign(id="camp1", partner_ids=[])
    c2 = _make_campaign(id="camp2", partner_ids=[])
    store.upsert_campaign(conn, c1)
    store.upsert_campaign(conn, c2)

    a1 = _make_creative(id="cr1", campaign_id="camp1")
    a2 = _make_creative(id="cr2", campaign_id="camp2")
    store.upsert_creative(conn, a1)
    store.upsert_creative(conn, a2)

    result = store.load_creatives(conn, campaign_id="camp1")
    assert len(result) == 1
    assert result[0].id == "cr1"


def test_upsert_creative_idempotent(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    c = _make_campaign(partner_ids=[])
    store.upsert_campaign(conn, c)

    a = _make_creative(copy_text="Оригінал")
    store.upsert_creative(conn, a)
    a.copy_text = "Оновлено"
    store.upsert_creative(conn, a)

    loaded = store.load_creatives(conn)
    assert len(loaded) == 1
    assert loaded[0].copy_text == "Оновлено"


# --- Partner ---


def test_upsert_and_load_partner(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)

    p = _make_partner()
    store.upsert_partner(conn, p)

    loaded = store.load_partners(conn)
    assert len(loaded) == 1
    assert loaded[0] == p


def test_partner_idempotent_upsert(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)

    p = _make_partner(name="Початковий")
    store.upsert_partner(conn, p)
    p.name = "Оновлений"
    store.upsert_partner(conn, p)

    loaded = store.load_partners(conn)
    assert len(loaded) == 1
    assert loaded[0].name == "Оновлений"


def test_full_seed_and_reload(tmp_path):
    """Насіння: актор + кампанія + 2 креативи + 2 партнери; перезавантаження рівне."""
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed_actor(conn)

    p1 = _make_partner("p1", name="Бренд А", role="brand")
    p2 = _make_partner("p2", name="Зірка Б", role="celebrity")
    store.upsert_partner(conn, p1)
    store.upsert_partner(conn, p2)

    c = _make_campaign(partner_ids=["p1", "p2"])
    store.upsert_campaign(conn, c)

    a1 = _make_creative(id="cr1", campaign_id="camp1")
    a2 = _make_creative(id="cr2", campaign_id="camp1", format="carousel", views=None)
    store.upsert_creative(conn, a1)
    store.upsert_creative(conn, a2)

    # reload
    campaigns = store.load_campaigns(conn)
    partners = store.load_partners(conn)
    creatives_c1 = store.load_creatives(conn, campaign_id="camp1")

    assert len(campaigns) == 1
    assert set(campaigns[0].partner_ids) == {"p1", "p2"}
    assert len(partners) == 2
    assert len(creatives_c1) == 2
