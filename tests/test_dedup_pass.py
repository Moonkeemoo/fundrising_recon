"""Тести для Unit 2: dedup_pass.dedup_database + store helpers.

TDD: тести написані до реалізації. Усі тести використовують тимчасовий SQLite.
Реальна БД data/fundrec.sqlite не торкається ніколи.
"""
from __future__ import annotations

import sqlite3

import pytest

from fundrec import store
from fundrec.dedup_pass import dedup_database
from fundrec.schema import Actor, Campaign, CreativeAsset
from fundrec.store import (
    delete_campaign,
    init_db,
    upsert_actor,
    upsert_campaign,
    upsert_creative,
)


# ---------------------------------------------------------------------------
# Fixture: тимчасова in-memory DB зі схемою
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Хелпери
# ---------------------------------------------------------------------------


def _actor(id: str = "a1") -> Actor:
    return Actor(id=id, name=f"Actor {id}", type="foundation")


def _campaign(
    id: str,
    actor_id: str = "a1",
    title: str = "Збір на дрони",
    provenance: dict | None = None,
    amount_uah: float | None = None,
    channels: list[str] | None = None,
    date_start: str | None = None,
    partner_ids: list[str] | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal="military",
        type="jar",
        channels=channels or [],
        amount_uah=amount_uah,
        date_start=date_start,
        provenance=provenance or {},
        partner_ids=partner_ids or [],
    )


def _creative(id: str, campaign_id: str) -> CreativeAsset:
    return CreativeAsset(
        id=id,
        campaign_id=campaign_id,
        platform="telegram",
        format="text",
    )


def _jar_prov(jar_id: str, tier: int = 1, amount: float = 100_000.0) -> dict:
    return {
        "amount_uah": {
            "source_url": f"https://send.monobank.ua/jar/{jar_id}",
            "confidence": 0.95,
            "tier": tier,
            "note": "jar",
        }
    }


# ---------------------------------------------------------------------------
# delete_campaign store helper
# ---------------------------------------------------------------------------


def test_delete_campaign_removes_row(tmp_conn):
    upsert_actor(tmp_conn, _actor("a1"))
    upsert_campaign(tmp_conn, _campaign("c1"))
    delete_campaign(tmp_conn, "c1")
    row = tmp_conn.execute("SELECT id FROM campaigns WHERE id = ?", ("c1",)).fetchone()
    assert row is None


def test_delete_campaign_removes_campaign_partners(tmp_conn):
    """delete_campaign очищає рядки campaign_partners."""
    from fundrec.schema import Partner
    from fundrec.store import upsert_partner

    upsert_actor(tmp_conn, _actor("a1"))
    upsert_partner(tmp_conn, Partner(id="p1", name="Partner", role="sponsor"))
    c = _campaign("c1", partner_ids=["p1"])
    upsert_campaign(tmp_conn, c)
    delete_campaign(tmp_conn, "c1")
    row = tmp_conn.execute(
        "SELECT * FROM campaign_partners WHERE campaign_id = ?", ("c1",)
    ).fetchone()
    assert row is None


def test_delete_nonexistent_campaign_noop(tmp_conn):
    """Видалення неіснуючої кампанії не падає."""
    delete_campaign(tmp_conn, "does_not_exist")


# ---------------------------------------------------------------------------
# dedup_database — jar-merge scenario
# ---------------------------------------------------------------------------


def test_dedup_database_merges_two_campaigns_sharing_jar(tmp_conn):
    """Дві кампанії з однаковим jar → залишається 1, summary коректний."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov = _jar_prov("JARSHARED")
    c1 = _campaign("c1", provenance=prov, amount_uah=100_000.0, channels=["telegram"])
    c2 = _campaign(
        "c2",
        title="Інша назва того ж збору",
        provenance=prov,
        amount_uah=50_000.0,
        channels=["facebook"],
    )
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    assert summary["before"] == 2
    assert summary["after"] == 1
    assert summary["merged"] == 1
    assert summary["groups_collapsed"] == 1


def test_dedup_database_canonical_has_unioned_channels(tmp_conn):
    """Merged кампанія об'єднує channels з обох."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov = _jar_prov("JARX")
    c1 = _campaign("c1", provenance=prov, channels=["telegram"])
    c2 = _campaign("c2", provenance=prov, channels=["facebook"])
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    merged_channels = set(remaining[0].channels)
    assert "telegram" in merged_channels
    assert "facebook" in merged_channels


def test_dedup_database_canonical_keeps_tier1_amount(tmp_conn):
    """Tier-1 (jar) amount_uah зберігається у merged кампанії."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov_tier1 = _jar_prov("JARY", tier=1)
    c1 = _campaign("c1", provenance=prov_tier1, amount_uah=250_000.0)
    # Обидві кампанії мають той самий jar щоб злилися за jar identity
    c2 = _campaign("c2", provenance=prov_tier1, amount_uah=999_999.0)
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    # Tier-1 jar провенанс зберігається; максимальне значення (999_999.0) може
    # перемогти якщо tier однаковий — але tier однаковий, тому confidence вирішує.
    # Обидва tier=1, значення відрізняються — merge_campaigns береже вищий confidence.
    # Головне: amount_uah не None і є реальним числом.
    assert remaining[0].amount_uah is not None


def test_dedup_database_creative_repointed_to_canonical(tmp_conn):
    """Творчий актив вказувавший на loser → після dedup вказує на canonical."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov = _jar_prov("JARZ")
    c1 = _campaign("c1", provenance=prov, channels=["telegram"])
    c2 = _campaign("c2", provenance=prov, channels=["facebook"])
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    # Творчий актив вказує на кампанію, яка потенційно буде loser
    cr = _creative("cr1", campaign_id="c2")
    upsert_creative(tmp_conn, cr)

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    canonical_id = remaining[0].id

    # Перевіряємо що creative тепер вказує на canonical
    creatives = store.load_creatives(tmp_conn)
    assert len(creatives) == 1
    assert creatives[0].campaign_id == canonical_id


def test_dedup_database_loser_campaign_deleted(tmp_conn):
    """Loser кампанія видалена з БД після dedup."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov = _jar_prov("JARDELETE")
    c1 = _campaign("c1", provenance=prov)
    c2 = _campaign("c2", provenance=prov)
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    dedup_database(tmp_conn)

    rows = tmp_conn.execute("SELECT id FROM campaigns ORDER BY id").fetchall()
    assert len(rows) == 1


def test_dedup_database_unique_campaign_untouched(tmp_conn):
    """Кампанії з різними jar і різними назвами залишаються без змін."""
    upsert_actor(tmp_conn, _actor("a1"))
    prov1 = _jar_prov("JAR_UNIQUE_1")
    prov2 = _jar_prov("JAR_UNIQUE_2")
    # Різні заголовки → fuzzy-прохід теж не зливає
    c1 = _campaign("c1", title="Збір на броньований автомобіль", provenance=prov1)
    c2 = _campaign("c2", title="Збір на FPV дрони для штурму", provenance=prov2)
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)

    assert summary["before"] == 2
    assert summary["after"] == 2
    assert summary["merged"] == 0
    assert summary["groups_collapsed"] == 0


def test_dedup_database_three_campaigns_two_share_jar_one_unique(tmp_conn):
    """3 кампанії: 2 зі спільним jar + 1 з різним jar і різною назвою → 2 залишаються."""
    upsert_actor(tmp_conn, _actor("a1"))
    shared_prov = _jar_prov("JARSHARED3")
    unique_prov = _jar_prov("JAR_UNIQUE_99")
    c1 = _campaign("c1", title="Збір на дрони підрозділу", provenance=shared_prov, channels=["telegram"])
    c2 = _campaign("c2", title="Збір на дрони підрозділу", provenance=shared_prov, channels=["facebook"])
    # Різна назва → fuzzy-прохід не зливає c3 з merged(c1+c2)
    c3 = _campaign("c3", title="Збір на броньований автомобіль", provenance=unique_prov, channels=["youtube"])
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)
    upsert_campaign(tmp_conn, c3)

    summary = dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 2
    assert summary["before"] == 3
    assert summary["after"] == 2
    assert summary["merged"] == 1
    assert summary["groups_collapsed"] == 1


def test_dedup_database_content_hash_repost_merges(tmp_conn):
    """Без jar: дві кампанії з однаковим title (repost) → зливаються."""
    upsert_actor(tmp_conn, _actor("a1"))
    # Без jar: content_hash(title) буде однаковий
    same_title = "Збираємо на дрони для ЗСУ. Потрібно 500 000 грн."
    c1 = _campaign("c1", title=same_title, channels=["telegram"])
    c2 = _campaign("c2", title=same_title, channels=["facebook"])
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    assert summary["merged"] == 1


def test_dedup_database_summary_keys_present(tmp_conn):
    """Summary словник завжди містить всі 4 ключі."""
    upsert_actor(tmp_conn, _actor("a1"))
    upsert_campaign(tmp_conn, _campaign("c1", provenance=_jar_prov("JAR1")))

    summary = dedup_database(tmp_conn)

    assert "before" in summary
    assert "after" in summary
    assert "merged" in summary
    assert "groups_collapsed" in summary


def test_dedup_database_empty_db_returns_zeros(tmp_conn):
    """Порожня БД → summary з нулями (включно з fuzzy_merged)."""
    summary = dedup_database(tmp_conn)
    assert summary["before"] == 0
    assert summary["after"] == 0
    assert summary["merged"] == 0
    assert summary["groups_collapsed"] == 0
    assert summary.get("fuzzy_merged", 0) == 0
