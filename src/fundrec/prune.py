"""Прунінг кампаній за датою: залишаємо тільки СВІЖІ збори (≤ N днів).

prune_old_campaigns(conn, *, max_age_days, now, delete_undated) -> dict
    Для кожної кампанії обчислює дату через analyze.parse_campaign_date.
    Старі (d < cutoff) та без дати (якщо delete_undated=True) — видаляються
    разом зі своїми creative_assets. Свіжі — залишаються.

CLI:
    python -m fundrec.prune [--max-age-days 60] [--keep-undated] [--db PATH] [--out PATH]
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta, timezone

from . import analyze, store


def prune_old_campaigns(
    conn: sqlite3.Connection,
    *,
    max_age_days: int = 60,
    now: str,
    delete_undated: bool = True,
) -> dict:
    """Видаляє застарілі та (за замовчуванням) кампанії без дати.

    Args:
        conn: SQLite connection (ініціалізована БД).
        max_age_days: максимальний вік кампанії в днях (включно з межею).
        now: ISO-рядок референсного моменту (YYYY-MM-DD або повний ISO).
            Не викликає datetime.now() — ін'єктується ззовні.
        delete_undated: True → кампанії без дати видаляються;
            False → залишаються (консервативно).

    Returns:
        {scanned, deleted_old, deleted_undated, kept, cutoff}
    """
    # Парсимо now (може бути повний ISO з часом — беремо перші 10 символів)
    now_date = date.fromisoformat(str(now)[:10])
    cutoff_date = now_date - timedelta(days=max_age_days)
    cutoff_str = cutoff_date.isoformat()

    campaigns = store.load_campaigns(conn)

    scanned = 0
    deleted_old = 0
    deleted_undated = 0
    kept = 0

    for campaign in campaigns:
        scanned += 1

        d = analyze.parse_campaign_date(campaign)

        if d is not None and d < cutoff_str:
            # Стара кампанія — видаляємо
            _delete_campaign_with_creatives(conn, campaign.id)
            deleted_old += 1

        elif d is None and delete_undated:
            # Без дати, не можемо підтвердити свіжість — видаляємо
            _delete_campaign_with_creatives(conn, campaign.id)
            deleted_undated += 1

        else:
            # Свіжа або undated при delete_undated=False — залишаємо
            kept += 1

    return {
        "scanned": scanned,
        "deleted_old": deleted_old,
        "deleted_undated": deleted_undated,
        "kept": kept,
        "cutoff": cutoff_str,
    }


def _delete_campaign_with_creatives(conn: sqlite3.Connection, campaign_id: str) -> None:
    """Видаляє creative_assets кампанії, потім саму кампанію (+ campaign_partners)."""
    conn.execute(
        "DELETE FROM creative_assets WHERE campaign_id = ?",
        (campaign_id,),
    )
    conn.commit()
    store.delete_campaign(conn, campaign_id)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.prune [--max-age-days 60] [--keep-undated] [--db PATH] [--out PATH]."""
    import argparse  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    from . import config, export  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec prune: видалити застарілі кампанії (> N днів)"
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=60,
        help="Максимальний вік кампанії в днях (default: 60)",
    )
    parser.add_argument(
        "--keep-undated",
        action="store_true",
        help="Зберегти кампанії без дати (за замовч. видаляються)",
    )
    parser.add_argument(
        "--db",
        default=str(config.DB_PATH),
        help="Шлях до SQLite БД (default: config.DB_PATH)",
    )
    parser.add_argument(
        "--out",
        default=str(config.CASES_JSON),
        help="Шлях до cases.json для re-export (default: config.CASES_JSON)",
    )
    args = parser.parse_args(argv)

    from pathlib import Path  # noqa: PLC0415

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"prune: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    # Реальний now — тільки CLI, не core-функція
    now_str = datetime.now(timezone.utc).isoformat()

    conn = store.connect(db_path)

    result = prune_old_campaigns(
        conn,
        max_age_days=args.max_age_days,
        now=now_str,
        delete_undated=not args.keep_undated,
    )

    exported = export.export_cases(conn, args.out)

    print(
        f"prune: scanned={result['scanned']} "
        f"deleted_old={result['deleted_old']} "
        f"deleted_undated={result['deleted_undated']} "
        f"kept={result['kept']} "
        f"cutoff={result['cutoff']} "
        f"exported={exported}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
