"""Тести для Unit 2: dedup_database — другий прохід fuzzy-злиття.

TDD: тести написані ДО реалізації — спочатку червоні, потім зелені.
Перевіряє, що після identity-based дедупу виконується другий прохід:
fuzzy_merge_groups → collapse по actor+goal+title_similarity≥min_sim.
"""
from __future__ import annotations

import sqlite3

import pytest

from fundrec import store
from fundrec.dedup_pass import dedup_database
from fundrec.schema import Actor, Campaign, CreativeAsset
from fundrec.store import (
    init_db,
    upsert_actor,
    upsert_campaign,
    upsert_creative,
)


# ---------------------------------------------------------------------------
# Fixtures
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
    goal: str = "military",
    provenance: dict | None = None,
    amount_uah: float | None = None,
    channels: list[str] | None = None,
    date_start: str | None = None,
    verification_status: str = "auto",
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal=goal,
        type="jar",
        channels=channels or [],
        amount_uah=amount_uah,
        date_start=date_start,
        provenance=provenance or {},
        verification_status=verification_status,
    )


def _creative(id: str, campaign_id: str) -> CreativeAsset:
    return CreativeAsset(
        id=id,
        campaign_id=campaign_id,
        platform="telegram",
        format="text",
    )


def _jar_prov(jar_id: str, tier: int = 1, amount: float = 1_000_000.0) -> dict:
    return {
        "amount_uah": {
            "source_url": f"https://send.monobank.ua/jar/{jar_id}",
            "confidence": 0.95,
            "tier": tier,
            "note": "jar",
        }
    }


# ---------------------------------------------------------------------------
# Unit 2 — fuzzy second pass merges
# ---------------------------------------------------------------------------


def test_dedup_database_fuzzy_merges_similar_titles_same_actor(tmp_conn):
    """Два схожих заголовки (без jar), один актор → залишається 1 кампанія."""
    upsert_actor(tmp_conn, _actor("feniksdpsu"))
    # Один пост з jar-провенансом (tier-1 amount)
    t1 = "Збір 1 000 000 на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів підрозділ"
    c1 = _campaign(
        "c1",
        actor_id="feniksdpsu",
        title=t1,
        provenance=_jar_prov("3T8X5TJ9aN"),
        amount_uah=1_000_000.0,
    )
    # Другий пост: той самий збір, але різна identity (немає jar)
    c2 = _campaign(
        "c2",
        actor_id="feniksdpsu",
        title=t2,
        # Без jar → отримає content: або actor: identity — не збіжна з c1
        provenance={
            "amount_uah": {
                "source_url": "https://t.me/feniksdpsu/1994",
                "confidence": 0.7,
                "tier": 2,
            }
        },
        amount_uah=None,
    )
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1, f"Очікувалась 1 кампанія, лишилось {len(remaining)}"
    assert summary.get("fuzzy_merged", 0) >= 1


def test_dedup_database_fuzzy_survivor_has_jar_amount(tmp_conn):
    """Survivor після fuzzy-злиття несе tier-1 jar amount."""
    upsert_actor(tmp_conn, _actor("feniksdpsu"))
    t1 = "Збір 1 000 000 на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів підрозділ"
    c1 = _campaign(
        "c1",
        actor_id="feniksdpsu",
        title=t1,
        provenance=_jar_prov("3T8X5TJ9aN"),
        amount_uah=1_000_000.0,
    )
    c2 = _campaign(
        "c2",
        actor_id="feniksdpsu",
        title=t2,
        provenance={"amount_uah": {"source_url": "https://t.me/feniksdpsu/1994", "confidence": 0.7, "tier": 2}},
        amount_uah=None,
    )
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    survivor = remaining[0]
    assert survivor.amount_uah == pytest.approx(1_000_000.0), (
        f"Survivor має нести jar amount, але amount_uah={survivor.amount_uah}"
    )


def test_dedup_database_fuzzy_creatives_repointed(tmp_conn):
    """Після fuzzy-злиття CreativeAsset лосера переприв'язується до canonical."""
    upsert_actor(tmp_conn, _actor("feniksdpsu"))
    t1 = "Збір 1 000 000 на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів підрозділ"
    c1 = _campaign("c1", actor_id="feniksdpsu", title=t1, provenance=_jar_prov("FUZZYJAR"))
    c2 = _campaign(
        "c2",
        actor_id="feniksdpsu",
        title=t2,
        provenance={"amount_uah": {"source_url": "https://t.me/feniksdpsu/1994", "confidence": 0.7, "tier": 2}},
    )
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)
    upsert_creative(tmp_conn, _creative("cr1", campaign_id="c2"))

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    canonical_id = remaining[0].id

    creatives = store.load_creatives(tmp_conn)
    assert len(creatives) == 1
    assert creatives[0].campaign_id == canonical_id


def test_dedup_database_fuzzy_dissimilar_titles_stay_separate(tmp_conn):
    """Два різні збори того самого актора НЕ зливаються (similarity < 0.6)."""
    upsert_actor(tmp_conn, _actor("actor1"))
    c1 = _campaign("c1", actor_id="actor1", title="Збір на броньований автомобіль для десантників")
    c2 = _campaign("c2", actor_id="actor1", title="Збір на FPV дрони для штурмової групи")
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 2
    assert summary.get("fuzzy_merged", 0) == 0


def test_dedup_database_fuzzy_different_actors_never_merged(tmp_conn):
    """Схожі заголовки, різні актори → НЕ зливаються fuzzy-проходом.

    Кожен актор має УНІКАЛЬНИЙ jar → Pass 1 не зливає їх за identity.
    Pass 2 (fuzzy) теж не має зливати — різні actor_id.
    """
    upsert_actor(tmp_conn, _actor("actor_a"))
    upsert_actor(tmp_conn, _actor("actor_b"))
    t1 = "Збір 1 000 000 на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів підрозділ"
    # Різні jar → Pass 1 не зливає
    c1 = _campaign("c1", actor_id="actor_a", title=t1, provenance=_jar_prov("JAR_ACTOR_A"))
    c2 = _campaign("c2", actor_id="actor_b", title=t2, provenance=_jar_prov("JAR_ACTOR_B"))
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    dedup_database(tmp_conn)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 2


def test_dedup_database_summary_has_fuzzy_merged_key(tmp_conn):
    """Summary завжди містить ключ 'fuzzy_merged'."""
    upsert_actor(tmp_conn, _actor("a1"))
    upsert_campaign(tmp_conn, _campaign("c1"))

    summary = dedup_database(tmp_conn)
    assert "fuzzy_merged" in summary


def test_dedup_database_empty_db_fuzzy_merged_zero(tmp_conn):
    """Порожня БД → fuzzy_merged = 0."""
    summary = dedup_database(tmp_conn)
    assert summary.get("fuzzy_merged") == 0


def test_dedup_database_fuzzy_merged_zero_when_no_similar_pairs(tmp_conn):
    """Без схожих пар → fuzzy_merged = 0."""
    upsert_actor(tmp_conn, _actor("a1"))
    c1 = _campaign("c1", actor_id="a1", title="Збір на авто для бойових підрозділів", provenance=_jar_prov("J1"))
    c2 = _campaign("c2", actor_id="a1", title="Збір FPV дрони штурм", provenance=_jar_prov("J2"))
    upsert_campaign(tmp_conn, c1)
    upsert_campaign(tmp_conn, c2)

    summary = dedup_database(tmp_conn)
    assert summary.get("fuzzy_merged") == 0


def test_dedup_database_existing_summary_keys_still_present(tmp_conn):
    """Нові ключі не видаляють старі (before/after/merged/groups_collapsed)."""
    upsert_actor(tmp_conn, _actor("a1"))
    upsert_campaign(tmp_conn, _campaign("c1", provenance=_jar_prov("J99")))

    summary = dedup_database(tmp_conn)

    for key in ("before", "after", "merged", "groups_collapsed", "fuzzy_merged"):
        assert key in summary, f"Відсутній ключ {key!r} в summary"
