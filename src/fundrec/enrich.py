"""Збагачення сум для кампаній без tier-1 amount.

enrich_amounts_from_text(conn, raw_dir) -> {scanned, updated}:
  Для кожної кампанії без tier-1 amount_uah: знаходить raw-файл,
  парсить текст через parse_amounts_from_text, заповнює з tier-2 provenance.
  Заповнює лише None-поля (amount_uah, goal_amount).

enrich_jars(conn, raw_dir, *, render) -> {scanned, jars_found, rendered_ok, updated}:
  Для кожної кампанії без tier-1 amount: знаходить raw-файл,
  jar_ids_from_raw → рендерить першу банку (inject render),
  застосовує tier-1 via _apply_jar_to_campaign + verification_status="verified".

CLI:
  python -m fundrec.enrich [--db PATH] [--raw-dir PATH] [--no-jars] [--no-text]
  Запускає обидва enrichers (text першим, потім jars), виводить summary,
  re-exports cases.json.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .amounts import parse_amounts_from_text
from .extract import _TIER_CONFIDENCE
from .ingest import _apply_jar_to_campaign
from .jars import jar_ids_from_raw

# Tier для текстових сум
_TEXT_TIER = 2
_TEXT_NOTE = "text amount"


def _get_raw_file(raw_dir: Path, campaign: Any) -> Path | None:
    """Знаходить raw-файл кампанії (той самий алгоритм що у backfill)."""
    # Спочатку за source_url з provenance
    source_url = (campaign.provenance.get("campaign") or {}).get("source_url") or ""
    if source_url:
        file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        candidate = raw_dir / f"{file_id}.json"
        if candidate.exists():
            return candidate

    # Fallback: glob по id-префіксу (camp-{sha256[:12]} → перші 12 hex)
    id_suffix = campaign.id[5:]  # strip "camp-"
    if len(id_suffix) >= 12:
        prefix = id_suffix[:12]
        candidates = list(raw_dir.glob(f"{prefix}*.json"))
        if candidates:
            return candidates[0]

    return None


def _has_tier1_amount(campaign: Any) -> bool:
    """Повертає True якщо кампанія вже має tier-1 provenance для amount_uah."""
    prov = campaign.provenance.get("amount_uah")
    if not isinstance(prov, dict):
        return False
    return prov.get("tier") == 1


def enrich_amounts_from_text(conn: Any, raw_dir: Path | str | None = None) -> dict[str, int]:
    """Заповнює amount_uah/goal_amount з тексту raw-файлу (tier-2).

    Пропускає кампанії де amount_uah вже є з tier-1 provenance.
    Заповнює лише None-поля (не перезаписує існуючі значення).

    Args:
        conn:    SQLite-з'єднання (ініціалізована БД).
        raw_dir: директорія raw-кешу. За замовчуванням — config.RAW_DIR.

    Returns:
        {scanned, updated}
    """
    from . import config, store  # noqa: PLC0415

    if raw_dir is None:
        raw_dir = config.RAW_DIR
    raw_dir = Path(raw_dir)

    campaigns = store.load_campaigns(conn)
    scanned = 0
    updated = 0

    for campaign in campaigns:
        scanned += 1

        # Пропускаємо якщо вже є tier-1 amount
        if _has_tier1_amount(campaign) and campaign.amount_uah is not None:
            continue

        # Шукаємо raw-файл
        raw_file = _get_raw_file(raw_dir, campaign)
        if raw_file is None:
            continue

        try:
            raw_item: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"enrich: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            continue

        text = raw_item.get("text") or raw_item.get("raw_text") or ""
        if not text:
            continue

        parsed = parse_amounts_from_text(text)
        amount = parsed.get("amount_uah")
        goal = parsed.get("goal_amount")

        changed = False
        source_url = raw_item.get("source_url") or ""
        confidence = _TIER_CONFIDENCE.get(_TEXT_TIER, 0.55)

        if campaign.amount_uah is None and amount is not None:
            campaign.amount_uah = amount
            campaign.provenance["amount_uah"] = {
                "source_url": source_url,
                "confidence": confidence,
                "tier": _TEXT_TIER,
                "note": _TEXT_NOTE,
            }
            changed = True

        if campaign.goal_amount is None and goal is not None:
            campaign.goal_amount = goal
            campaign.provenance["goal_amount"] = {
                "source_url": source_url,
                "confidence": confidence,
                "tier": _TEXT_TIER,
                "note": _TEXT_NOTE,
            }
            changed = True

        if changed:
            store.upsert_campaign(conn, campaign)
            updated += 1

    return {"scanned": scanned, "updated": updated}


def enrich_jars(
    conn: Any,
    raw_dir: Path | str | None = None,
    *,
    render: Any | None = None,
) -> dict[str, int]:
    """Збагачує кампанії через рендер jar-банки (tier-1).

    Для кожної кампанії без tier-1 amount_uah:
    1. Знаходить raw-файл.
    2. jar_ids_from_raw(raw) → знаходить jar-id.
    3. render(jar_id) → дані банки.
    4. Якщо amount присутній → _apply_jar_to_campaign + verification_status="verified".

    Args:
        conn:    SQLite-з'єднання (ініціалізована БД).
        raw_dir: директорія raw-кешу. За замовчуванням — config.RAW_DIR.
        render:  fn(jar_id) -> dict | None. За замовчуванням — render_jar_cached.
                 У тестах інжектується фейковий рендерер.

    Returns:
        {scanned, jars_found, rendered_ok, updated}
    """
    from . import config, store  # noqa: PLC0415

    if raw_dir is None:
        raw_dir = config.RAW_DIR
    raw_dir = Path(raw_dir)

    if render is None:
        # Lazy-import playwright-шлях (не імпортуємо на рівні модуля)
        try:
            from .collect.jar_render import render_jar_cached  # noqa: PLC0415  # pragma: no cover
            render = render_jar_cached  # pragma: no cover
        except ImportError:  # pragma: no cover
            from .jars import fetch_jar_data  # noqa: PLC0415  # pragma: no cover
            render = fetch_jar_data  # pragma: no cover

    campaigns = store.load_campaigns(conn)
    scanned = 0
    jars_found = 0
    rendered_ok = 0
    updated = 0

    for campaign in campaigns:
        scanned += 1

        # Пропускаємо якщо вже є tier-1 amount
        if _has_tier1_amount(campaign) and campaign.amount_uah is not None:
            continue

        # Знаходимо raw-файл
        raw_file = _get_raw_file(raw_dir, campaign)
        if raw_file is None:
            continue

        try:
            raw_item: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"enrich: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            continue

        jar_ids = jar_ids_from_raw(raw_item)
        if not jar_ids:
            continue
        jars_found += 1

        first_jar = jar_ids[0]
        try:
            jar_data = render(first_jar)
        except Exception as exc:  # noqa: BLE001
            print(f"enrich: render failed for {first_jar}: {exc}", file=sys.stderr)
            jar_data = None

        if jar_data is None or jar_data.get("amount_uah") is None:
            continue
        rendered_ok += 1

        _apply_jar_to_campaign(campaign, jar_data)
        store.upsert_campaign(conn, campaign)
        store.set_campaign_verification(conn, campaign.id, "verified", reason="monobank jar tier-1")
        updated += 1

    return {
        "scanned": scanned,
        "jars_found": jars_found,
        "rendered_ok": rendered_ok,
        "updated": updated,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI: збагачення сум для всіх кампаній у БД."""
    import argparse  # noqa: PLC0415

    from . import config, export, store  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec enrich: збагачення amount_uah/goal_amount кампаній"
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів"
    )
    parser.add_argument(
        "--out", default=str(config.CASES_JSON), help="Шлях до cases.json для re-export"
    )
    parser.add_argument(
        "--no-text", action="store_true", help="Пропустити text-enrichment"
    )
    parser.add_argument(
        "--no-jars", action="store_true", help="Пропустити jar-enrichment"
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    raw_dir = Path(args.raw_dir)

    if not db_path.exists():
        print(f"enrich: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)

    text_result: dict[str, int] = {"scanned": 0, "updated": 0}
    jar_result: dict[str, int] = {"scanned": 0, "jars_found": 0, "rendered_ok": 0, "updated": 0}

    if not args.no_text:
        text_result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
        print(
            f"enrich text: scanned={text_result['scanned']} updated={text_result['updated']}",
            file=sys.stdout,
        )

    if not args.no_jars:
        jar_result = enrich_jars(conn, raw_dir=raw_dir)
        print(
            f"enrich jars: scanned={jar_result['scanned']} "
            f"jars_found={jar_result['jars_found']} "
            f"rendered_ok={jar_result['rendered_ok']} "
            f"updated={jar_result['updated']}",
            file=sys.stdout,
        )

    # Re-export cases.json
    exported = export.export_cases(conn, args.out)
    print(f"enrich: exported={exported}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
