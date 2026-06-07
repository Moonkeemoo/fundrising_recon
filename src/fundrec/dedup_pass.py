"""Пост-інгест дедуплікаційний прохід по всій БД кампаній.

dedup_database(conn) -> dict:
  Завантажує всі кампанії і креативи, групує за campaign_identity,
  зливає дублікати через _campaign_merge_two, переприв'язує креативи
  до canonical, видаляє loser-кампанії.
  Повертає {"before": N, "after": M, "merged": N-M, "groups_collapsed": k}.

CLI: python -m fundrec.dedup_pass [--db PATH]
  Запускає dedup_database на реальній БД, виводить summary,
  потім re-export через export.export_cases.
"""
from __future__ import annotations

import sqlite3

from .dedup import _campaign_merge_two, campaign_identity, campaign_jar_id, fuzzy_merge_groups
from .store import (
    delete_campaign,
    load_campaigns,
    load_creatives,
    upsert_campaign,
    upsert_creative,
)


def _sort_key_canonical(c) -> tuple:  # noqa: ANN001
    """Ключ сортування для вибору canonical у групі.

    Порядок пріоритетів (менше = кращий canonical):
    1. Наявність tier-1 jar provenance для amount_uah (є → 0, немає → 1).
    2. Кількість полів провенансу (більше — краще, тому мінус).
    3. Найрання date_start.
    4. Менший id (алфавітно) для детермінізму.
    """
    has_tier1 = 0
    entry = c.provenance.get("amount_uah")
    if isinstance(entry, dict) and int(entry.get("tier", 99)) == 1:
        has_tier1 = 1
    # Також враховуємо наявність jar у будь-якому полі провенансу
    if campaign_jar_id(c) is not None:
        has_tier1 = 1
    prov_count = len(c.provenance)
    date = c.date_start or "9999-99-99"
    return (-has_tier1, -prov_count, date, c.id)


def _apply_group_merge(
    group: list,
    merged_count: int,
    groups_collapsed: int,
    losers: list[str],
    canonical_map: dict[str, str],
    conn: sqlite3.Connection,
) -> tuple[int, int]:
    """Зливає групу кампаній, повертає (merged_count, groups_collapsed)."""
    groups_collapsed += 1

    sorted_group = sorted(group, key=_sort_key_canonical)
    canonical = sorted_group[0]

    for loser in sorted_group[1:]:
        canonical = _campaign_merge_two(canonical, loser)

    canonical_id = canonical.id

    for c in group:
        if c.id != canonical_id:
            losers.append(c.id)
            canonical_map[c.id] = canonical_id
            merged_count += 1

    upsert_campaign(conn, canonical)
    return merged_count, groups_collapsed


def dedup_database(conn: sqlite3.Connection, *, min_sim: float = 0.6) -> dict:
    """Пост-інгест дедуплікаційний прохід.

    Прохід 1 (identity-based):
      Групує кампанії за campaign_identity (jar > content > actor).
      Для груп >1: обирає canonical, зливає решту, переприв'язує креативи.

    Прохід 2 (fuzzy title-based):
      Серед кампаній, що залишились після Проходу 1, групує за
      fuzzy_merge_groups (same actor + same goal_category + title_similarity ≥ min_sim).
      Зливає fuzzy-групи →  jar amount та verified status переходять до survivor.

    Повертає summary {"before", "after", "merged", "groups_collapsed", "fuzzy_merged"}.
    """
    campaigns = load_campaigns(conn)
    creatives = load_creatives(conn)
    before = len(campaigns)

    if before == 0:
        return {"before": 0, "after": 0, "merged": 0, "groups_collapsed": 0, "fuzzy_merged": 0}

    # --- Прохід 1: identity-based ---
    groups: dict[str, list] = {}
    for c in campaigns:
        key = campaign_identity(c)
        groups.setdefault(key, []).append(c)

    merged_count = 0
    groups_collapsed = 0
    losers: list[str] = []
    canonical_map: dict[str, str] = {}

    for group in groups.values():
        if len(group) == 1:
            continue
        merged_count, groups_collapsed = _apply_group_merge(
            group, merged_count, groups_collapsed, losers, canonical_map, conn
        )

    # Переприв'язуємо креативи після Проходу 1
    for creative in creatives:
        if creative.campaign_id in canonical_map:
            new_cid = canonical_map[creative.campaign_id]
            updated = type(creative)(
                id=creative.id,
                campaign_id=new_cid,
                platform=creative.platform,
                format=creative.format,
                copy_text=creative.copy_text,
                hook=creative.hook,
                cta=creative.cta,
                media_url=creative.media_url,
                published=creative.published,
                impressions_range=creative.impressions_range,
                spend_range=creative.spend_range,
                views=creative.views,
                likes=creative.likes,
                provenance=creative.provenance,
            )
            upsert_creative(conn, updated)

    # Видаляємо losers Проходу 1
    for loser_id in losers:
        delete_campaign(conn, loser_id)

    # --- Прохід 2: fuzzy title-based ---
    # Перезавантажуємо кампанії після Проходу 1
    remaining_after_pass1 = load_campaigns(conn)
    creatives_after_pass1 = load_creatives(conn)

    fuzzy_groups = fuzzy_merge_groups(remaining_after_pass1, min_sim=min_sim)

    fuzzy_merged_count = 0
    fuzzy_losers: list[str] = []
    fuzzy_canonical_map: dict[str, str] = {}
    fuzzy_groups_collapsed = 0

    for fgroup in fuzzy_groups:
        if len(fgroup) == 1:
            continue
        fuzzy_merged_count, fuzzy_groups_collapsed = _apply_group_merge(
            fgroup,
            fuzzy_merged_count,
            fuzzy_groups_collapsed,
            fuzzy_losers,
            fuzzy_canonical_map,
            conn,
        )

    # Переприв'язуємо креативи після Проходу 2
    for creative in creatives_after_pass1:
        if creative.campaign_id in fuzzy_canonical_map:
            new_cid = fuzzy_canonical_map[creative.campaign_id]
            updated = type(creative)(
                id=creative.id,
                campaign_id=new_cid,
                platform=creative.platform,
                format=creative.format,
                copy_text=creative.copy_text,
                hook=creative.hook,
                cta=creative.cta,
                media_url=creative.media_url,
                published=creative.published,
                impressions_range=creative.impressions_range,
                spend_range=creative.spend_range,
                views=creative.views,
                likes=creative.likes,
                provenance=creative.provenance,
            )
            upsert_creative(conn, updated)

    # Видаляємо losers Проходу 2
    for loser_id in fuzzy_losers:
        delete_campaign(conn, loser_id)

    total_merged = merged_count + fuzzy_merged_count
    after = before - total_merged
    return {
        "before": before,
        "after": after,
        "merged": merged_count,
        "groups_collapsed": groups_collapsed,
        "fuzzy_merged": fuzzy_merged_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:  # pragma: no cover
    """CLI: python -m fundrec.dedup_pass [--db PATH]"""
    import argparse
    import sys

    from . import config, export, store

    parser = argparse.ArgumentParser(description="Дедуплікаційний прохід по БД кампаній.")
    parser.add_argument(
        "--db",
        default=str(config.DB_PATH),
        help="Шлях до SQLite БД (default: config.DB_PATH)",
    )
    args = parser.parse_args()

    conn = store.connect(args.db)
    store.init_db(conn)

    summary = dedup_database(conn)
    print(f"Dedup pass complete: {summary}")

    count = export.export_cases(conn)
    print(f"Re-exported {count} cases to cases.json")
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _main()
