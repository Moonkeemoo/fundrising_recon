"""Тести для prune.prune_old_campaigns (TDD).

Усі тести використовують тимчасовий SQLite (:memory:).
Реальна БД data/fundrec.sqlite НІКОЛИ не торкається.
`now` завжди ін'єктується — datetime.now() ніколи не викликається в тестах.
"""
from __future__ import annotations

import sqlite3

import pytest

from fundrec.schema import Actor, Campaign, CreativeAsset
from fundrec.store import init_db, upsert_actor, upsert_campaign, upsert_creative


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
    *,
    actor_id: str = "a1",
    date_start: str | None = None,
    year: int | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"Збір {id}",
        goal="military",
        type="jar",
        date_start=date_start,
        year=year,
    )


def _creative(id: str, campaign_id: str) -> CreativeAsset:
    return CreativeAsset(
        id=id,
        campaign_id=campaign_id,
        platform="telegram",
        format="text",
    )


def _iso(days_ago: int, now_date: str = "2024-06-01") -> str:
    """Повертає ISO-дату N днів перед now_date."""
    from datetime import date, timedelta

    d = date.fromisoformat(now_date) - timedelta(days=days_ago)
    return d.isoformat()


# ---------------------------------------------------------------------------
# Базова логіка: old/fresh/undated
# ---------------------------------------------------------------------------


def test_old_campaigns_deleted(tmp_conn):
    """Кампанії старіші за max_age_days видаляються."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_fresh", date_start=_iso(10, NOW)))   # 10d → keep
    upsert_campaign(tmp_conn, _campaign("c_old70", date_start=_iso(70, NOW)))   # 70d → delete
    upsert_campaign(tmp_conn, _campaign("c_old100", date_start=_iso(100, NOW))) # 100d → delete

    prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    remaining = tmp_conn.execute("SELECT id FROM campaigns").fetchall()
    remaining_ids = {r[0] for r in remaining}
    assert "c_fresh" in remaining_ids
    assert "c_old70" not in remaining_ids
    assert "c_old100" not in remaining_ids


def test_fresh_campaigns_kept(tmp_conn):
    """Кампанії молодші за max_age_days зберігаються."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c10", date_start=_iso(10, NOW)))
    upsert_campaign(tmp_conn, _campaign("c40", date_start=_iso(40, NOW)))

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    assert result["kept"] == 2
    assert result["deleted_old"] == 0


def test_undated_deleted_by_default(tmp_conn):
    """Кампанії без дати видаляються за замовчуванням (delete_undated=True)."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_nodates"))  # date_start=None, year=None

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    assert result["deleted_undated"] == 1
    row = tmp_conn.execute("SELECT id FROM campaigns WHERE id = ?", ("c_nodates",)).fetchone()
    assert row is None


def test_undated_kept_when_delete_undated_false(tmp_conn):
    """Кампанії без дати зберігаються якщо delete_undated=False."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_nodates"))

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW, delete_undated=False)

    assert result["deleted_undated"] == 0
    assert result["kept"] == 1
    row = tmp_conn.execute("SELECT id FROM campaigns WHERE id = ?", ("c_nodates",)).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# Counts correctness
# ---------------------------------------------------------------------------


def test_counts_correct_mixed(tmp_conn):
    """Перевірка всіх лічильників: 10d + 40d fresh, 70d + 100d old, 1 undated."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c10",  date_start=_iso(10, NOW)))
    upsert_campaign(tmp_conn, _campaign("c40",  date_start=_iso(40, NOW)))
    upsert_campaign(tmp_conn, _campaign("c70",  date_start=_iso(70, NOW)))
    upsert_campaign(tmp_conn, _campaign("c100", date_start=_iso(100, NOW)))
    upsert_campaign(tmp_conn, _campaign("c_nd"))  # undated

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW, delete_undated=True)

    assert result["scanned"] == 5
    assert result["deleted_old"] == 2
    assert result["deleted_undated"] == 1
    assert result["kept"] == 2
    assert result["cutoff"] == _iso(60, NOW)


def test_counts_undated_kept(tmp_conn):
    """Лічильник kept включає undated якщо delete_undated=False."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_nd"))  # undated

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW, delete_undated=False)

    assert result["kept"] == 1
    assert result["deleted_undated"] == 0


# ---------------------------------------------------------------------------
# Creative assets видаляються разом з кампанією
# ---------------------------------------------------------------------------


def test_creatives_of_deleted_campaign_removed(tmp_conn):
    """creative_assets видаляються разом зі старою кампанією."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_old", date_start=_iso(90, NOW)))
    upsert_creative(tmp_conn, _creative("cr1", "c_old"))
    upsert_creative(tmp_conn, _creative("cr2", "c_old"))

    prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    creatives = tmp_conn.execute(
        "SELECT id FROM creative_assets WHERE campaign_id = ?", ("c_old",)
    ).fetchall()
    assert len(creatives) == 0


def test_creatives_of_fresh_campaign_not_removed(tmp_conn):
    """creative_assets свіжої кампанії НЕ видаляються."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_fresh", date_start=_iso(5, NOW)))
    upsert_creative(tmp_conn, _creative("cr_good", "c_fresh"))

    prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    cr = tmp_conn.execute(
        "SELECT id FROM creative_assets WHERE id = ?", ("cr_good",)
    ).fetchone()
    assert cr is not None


# ---------------------------------------------------------------------------
# year-only → parse_campaign_date → YYYY-01-01 (old)
# ---------------------------------------------------------------------------


def test_year_only_2022_is_old(tmp_conn):
    """Кампанія з year=2022 → parse_campaign_date → 2022-01-01 → стара."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_year2022", year=2022))

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    assert result["deleted_old"] == 1
    row = tmp_conn.execute("SELECT id FROM campaigns WHERE id = ?", ("c_year2022",)).fetchone()
    assert row is None


def test_year_only_current_is_fresh(tmp_conn):
    """Кампанія з year поточного року → свіжа якщо дата в межах вікна.

    Наприклад: now=2024-01-15, year=2024 → 2024-01-01 → 14 днів тому → fresh (≤60).
    """
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-01-15"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_y2024", year=2024))

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    assert result["kept"] == 1
    assert result["deleted_old"] == 0


# ---------------------------------------------------------------------------
# Cutoff boundary: точно на межі
# ---------------------------------------------------------------------------


def test_exactly_at_cutoff_is_old(tmp_conn):
    """Кампанія РІВНО на cutoff-дні вважається старою (d < cutoff → False; d == cutoff → keep).

    cutoff = now - max_age_days; умова видалення: d < cutoff.
    Кампанія з date = cutoff (тобто d == cutoff) → ЗБЕРІГАЄТЬСЯ.
    """
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_cutoff", date_start=_iso(60, NOW)))  # d == cutoff

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    # d == cutoff → NOT strictly less → KEEP
    assert result["kept"] == 1
    assert result["deleted_old"] == 0


def test_one_day_before_cutoff_is_old(tmp_conn):
    """Кампанія на 1 день старіша за cutoff → видаляється."""
    from fundrec.prune import prune_old_campaigns

    NOW = "2024-06-01"
    upsert_actor(tmp_conn, _actor())
    upsert_campaign(tmp_conn, _campaign("c_over", date_start=_iso(61, NOW)))  # d < cutoff

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now=NOW)

    assert result["deleted_old"] == 1


# ---------------------------------------------------------------------------
# Return dict keys always present
# ---------------------------------------------------------------------------


def test_result_keys_always_present(tmp_conn):
    """Повертає dict з усіма 6 ключами навіть на порожній БД."""
    from fundrec.prune import prune_old_campaigns

    result = prune_old_campaigns(tmp_conn, max_age_days=60, now="2024-06-01")

    assert "scanned" in result
    assert "deleted_old" in result
    assert "deleted_undated" in result
    assert "kept" in result
    assert "cutoff" in result
