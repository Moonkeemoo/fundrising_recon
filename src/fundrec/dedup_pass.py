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

from .dedup import _campaign_merge_two, campaign_identity
from .store import (
    delete_campaign,
    load_campaigns,
    load_creatives,
    upsert_campaign,
    upsert_creative,
)


def dedup_database(conn: sqlite3.Connection) -> dict:
    """Пост-інгест дедуплікаційний прохід.

    1. Завантажує всі Campaign + CreativeAsset.
    2. Групує кампанії за campaign_identity (title як текст — jar beats content beats actor).
    3. Для груп >1: обирає canonical (tier-1 jar або найбільше провенансу / найрання дата),
       зливає решту через _campaign_merge_two, зберігає canonical id.
    4. Переприв'язує CreativeAsset: loser campaign_id → canonical id.
    5. Видаляє loser-кампанії (та їх campaign_partners).
    6. Upsert canonical кампанії.
    7. Повертає summary {"before", "after", "merged", "groups_collapsed"}.
    """
    campaigns = load_campaigns(conn)
    creatives = load_creatives(conn)
    before = len(campaigns)

    if before == 0:
        return {"before": 0, "after": 0, "merged": 0, "groups_collapsed": 0}

    # Групуємо за identity (використовуємо title як text)
    groups: dict[str, list] = {}
    for c in campaigns:
        key = campaign_identity(c)
        groups.setdefault(key, []).append(c)

    merged_count = 0
    groups_collapsed = 0
    losers: list[str] = []  # campaign ids to delete
    canonical_map: dict[str, str] = {}  # loser_id → canonical_id

    for group in groups.values():
        if len(group) == 1:
            continue

        groups_collapsed += 1

        # Обираємо canonical: спочатку той, у кого tier-1 jar provenance для amount_uah;
        # якщо декілька — беремо з найбільшою кількістю полів провенансу;
        # якщо однаково — найрання date_start; в решті — менший id (алфавітно).
        def _sort_key(c):  # noqa: ANN001
            has_tier1 = 0
            entry = c.provenance.get("amount_uah")
            if isinstance(entry, dict) and int(entry.get("tier", 99)) == 1:
                has_tier1 = 1
            prov_count = len(c.provenance)
            date = c.date_start or "9999-99-99"
            return (-has_tier1, -prov_count, date, c.id)

        sorted_group = sorted(group, key=_sort_key)
        canonical = sorted_group[0]

        # Зливаємо всіх losers у canonical
        for loser in sorted_group[1:]:
            canonical = _campaign_merge_two(canonical, loser)
            # Але зберігаємо id canonical (merge_two вибирає менший id алфавітно)
            # Нам потрібен id саме першого обраного canonical:
            # _campaign_merge_two повертає менший id — це нормально для детермінізму.

        # Визначаємо реальний canonical id (після злиття — той що в canonical.id)
        canonical_id = canonical.id

        # Усі id в групі крім canonical → losers
        for c in group:
            if c.id != canonical_id:
                losers.append(c.id)
                canonical_map[c.id] = canonical_id
                merged_count += 1

        # Upsert canonical
        upsert_campaign(conn, canonical)

    # Переприв'язуємо креативи
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

    # Видаляємо losers
    for loser_id in losers:
        delete_campaign(conn, loser_id)

    after = before - merged_count
    return {
        "before": before,
        "after": after,
        "merged": merged_count,
        "groups_collapsed": groups_collapsed,
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
