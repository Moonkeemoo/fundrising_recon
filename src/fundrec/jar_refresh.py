"""CLI для оновлення snapshot-ів банок Monobank.

python -m fundrec.jar_refresh [--db PATH] [--raw-dir PATH]

Знаходить усі jar_id з провенансу кампаній у БД,
потім викликає render_jar_cached для кожного (записує свіжий snapshot),
виводить зведення.

Логіка збору jar_id:
    - завантажує кампанії з БД через store.load_campaigns;
    - для кожної кампанії — campaign_jar_id(campaign) з dedup;
    - дедуплікує jar_id (зберігає порядок першої появи).

Виклик _render=None (live, pragma: no cover) в main CLI;
логіка збору jar_id — тестована окремо.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import config
from .dedup import campaign_jar_id


def collect_jar_ids_from_campaigns(campaigns: list[Any]) -> list[str]:
    """Збирає унікальні jar_id з провенансу кампаній.

    Повертає список jar_id (без дублів, порядок першої появи).
    Тестована функція — не викликає мережу.
    """
    seen: set[str] = set()
    result: list[str] = []
    for c in campaigns:
        jar_id = campaign_jar_id(c)
        if jar_id and jar_id not in seen:
            seen.add(jar_id)
            result.append(jar_id)
    return result


def run_refresh(  # pragma: no cover
    *,
    db_path: Path | str = config.DB_PATH,
    cache_path: Path | str = config.JARS_CACHE_PATH,
    verbose: bool = True,
) -> dict[str, int]:  # pragma: no cover
    """Запускає live-рендер усіх jar_id з кампаній, оновлює кеш.

    Повертає {total, ok, failed}.
    Весь live-рендер позначено # pragma: no cover.
    """
    from . import store  # noqa: PLC0415
    from .collect.jar_render import render_jar_cached  # noqa: PLC0415

    conn = store.connect(db_path)
    campaigns = store.load_campaigns(conn)
    jar_ids = collect_jar_ids_from_campaigns(campaigns)

    total = len(jar_ids)
    ok = 0
    failed = 0

    if verbose:
        print(f"fundrec jar_refresh: знайдено {total} jar_id у кампаніях")

    for jar_id in jar_ids:
        result = render_jar_cached(jar_id, cache_path=cache_path, force=True)
        if result is not None:
            ok += 1
            if verbose:
                amt = result.get("amount_uah")
                title = (result.get("title") or jar_id)[:40]
                hist = result.get("history") or []
                print(f"  OK {jar_id[:12]}… «{title}» ₴{amt:,.0f} (snapshots: {len(hist)})")
        else:
            failed += 1
            if verbose:
                print(f"  FAIL {jar_id[:12]}…", file=sys.stderr)

    if verbose:
        print(f"fundrec jar_refresh: OK={ok} FAIL={failed} / {total}")

    return {"total": total, "ok": ok, "failed": failed}


def main() -> None:  # pragma: no cover
    """CLI entrypoint: python -m fundrec.jar_refresh."""
    parser = argparse.ArgumentParser(
        description="Оновлює snapshot-и банок Monobank (jar momentum).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Запускай регулярно (наприклад, кожні 6–12 год) щоб накопичити\n"
            "достатньо snapshot-ів для відображення velocity на дашборді.\n"
            "Velocity зʼявиться після ≥2 рефрешів з різними сумами або\n"
            "через ≥6 годин між запусками."
        ),
    )
    parser.add_argument(
        "--db",
        default=str(config.DB_PATH),
        help=f"Шлях до SQLite БД (default: {config.DB_PATH})",
    )
    parser.add_argument(
        "--cache",
        default=str(config.JARS_CACHE_PATH),
        help=f"Шлях до jars_cache.json (default: {config.JARS_CACHE_PATH})",
    )
    args = parser.parse_args()
    run_refresh(db_path=args.db, cache_path=args.cache)


if __name__ == "__main__":  # pragma: no cover
    main()
