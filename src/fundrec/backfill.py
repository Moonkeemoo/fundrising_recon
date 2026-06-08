"""Детермінований бекфіл сигналів для вже зібраних кампаній.

backfill_campaign(campaign, raw_item) -> bool:
  Заповнює reach/engagement/date_start/goal_reached із сирого payload.
  Лише якщо поле поточно None. Повертає True якщо щось змінилось.

backfill_database(conn, raw_dir) -> dict:
  Для кожної кампанії знаходить raw-файл, застосовує backfill_campaign,
  зберігає якщо змінилась. Повертає {scanned, raw_found, updated}.

CLI:
  python -m fundrec.backfill [--db PATH] [--raw-dir PATH]
  Запускає backfill_database + re-export cases.json + виводить summary.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .analyze import text_signals_goal_reached
from .extract import _TIER_CONFIDENCE

# Tier для платформних сигналів при бекфілі
_BACKFILL_TIER = 3
_BACKFILL_NOTE = "platform signal backfill"


def _parse_date(raw_date: str | None) -> str | None:
    """Нормалізує ISO-дату/datetime до YYYY-MM-DD. Повертає None якщо нема."""
    if not raw_date:
        return None
    s = str(raw_date).strip()
    # Беремо перші 10 символів — YYYY-MM-DD (або YYYY-MM-DDTHH:...)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # Підтримка YYYY-MM (якщо раптом так)
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return None


def _extract_signals(raw_item: dict[str, Any]) -> tuple[int | float | None, int | float | None]:
    """Витягує (reach, engagement) з raw_item детерміновано.

    Telegram: reach=views; engagement=forwards (БЕЗ fallback на views →
        None якщо forwards відсутній; публічний t.me/s/ не дає forwards/реакцій).
    YouTube:  reach=views; engagement=likes (БЕЗ fallback на views).
    Інші платформи: (None, None).
    """
    platform = (raw_item.get("platform") or "").lower()
    views = raw_item.get("views")
    forwards = raw_item.get("forwards")
    likes = raw_item.get("likes")

    if platform == "telegram":
        if views is not None:
            reach: int | float | None = views
            engagement: int | float | None = forwards  # None якщо відсутній — чесно
            return reach, engagement

    elif platform == "youtube":
        if views is not None:
            reach = views
            engagement = likes  # None якщо відсутній — чесно
            return reach, engagement

    return None, None


def backfill_campaign(campaign: Any, raw_item: dict[str, Any]) -> bool:
    """Заповнює порожні сигнальні поля кампанії із сирого payload.

    Правила:
    - reach/engagement — тільки якщо None (не перезаписує існуючі значення).
    - date_start — з raw['date'] (telegram) або raw['published'] (youtube),
      тільки якщо None; нормалізується до YYYY-MM-DD.
    - goal_reached — keyword-аналіз тексту (text_signals_goal_reached),
      тільки якщо None.
    - Провіненс tier-3 з note='platform signal backfill'.

    Args:
        campaign: Campaign dataclass instance (mutated in-place).
        raw_item: сирий payload із raw-кешу.

    Returns:
        True якщо хоча б одне поле змінилось.
    """
    changed = False
    source_url = raw_item.get("source_url") or ""
    confidence = _TIER_CONFIDENCE.get(_BACKFILL_TIER, 0.35)

    # ── reach / engagement ──────────────────────────────────────────────────
    if campaign.reach is None or campaign.engagement is None:
        reach_val, engagement_val = _extract_signals(raw_item)

        if campaign.reach is None and reach_val is not None:
            campaign.reach = reach_val
            campaign.provenance["reach"] = {
                "source_url": source_url,
                "confidence": confidence,
                "tier": _BACKFILL_TIER,
                "note": _BACKFILL_NOTE,
            }
            changed = True

        if campaign.engagement is None and engagement_val is not None:
            campaign.engagement = engagement_val
            campaign.provenance["engagement"] = {
                "source_url": source_url,
                "confidence": confidence,
                "tier": _BACKFILL_TIER,
                "note": _BACKFILL_NOTE,
            }
            changed = True

    # ── date_start ──────────────────────────────────────────────────────────
    if campaign.date_start is None:
        raw_date = raw_item.get("date") or raw_item.get("published")
        parsed = _parse_date(raw_date)
        if parsed is not None:
            campaign.date_start = parsed
            changed = True

    # ── goal_reached ────────────────────────────────────────────────────────
    if campaign.goal_reached is None:
        text = raw_item.get("text") or raw_item.get("raw_text") or ""
        kw_result = text_signals_goal_reached(text)
        if kw_result is not None:
            campaign.goal_reached = kw_result
            changed = True

    return changed


def backfill_database(conn: Any, raw_dir: Path | str) -> dict[str, int]:
    """Бекфіл усіх кампаній у БД із raw-кешу.

    Для кожної кампанії:
    1. Обчислює raw-файл: raw_dir/{sha256(url)[:16]}.json
    2. Якщо файл існує — завантажує, запускає backfill_campaign
    3. Якщо кампанія змінилась — upsert_campaign

    Args:
        conn: SQLite connection (вже ініціалізована БД).
        raw_dir: шлях до директорії сирих кешів.

    Returns:
        {scanned, raw_found, updated}
    """
    from . import store  # noqa: PLC0415

    raw_dir = Path(raw_dir)
    campaigns = store.load_campaigns(conn)

    scanned = 0
    raw_found = 0
    updated = 0

    for campaign in campaigns:
        scanned += 1

        # id формат: "camp-{sha256(url)[:12]}"; raw файл: "{sha256(url)[:16]}.json"
        # Перші 12 hex кампанії є префіксом 16-hex raw-файлу — glob для відповідності.
        # Fallback: якщо source_url є у provenance — обчислюємо напряму.
        raw_file: Path | None = None

        source_url = (campaign.provenance.get("campaign") or {}).get("source_url") or ""
        if source_url:
            file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
            candidate = raw_dir / f"{file_id}.json"
            if candidate.exists():
                raw_file = candidate

        # Fallback: glob по id-префіксу (camp-{sha256[:12]} → перші 12 hex)
        if raw_file is None:
            id_suffix = campaign.id[5:]  # strip "camp-"
            if len(id_suffix) >= 12:
                prefix = id_suffix[:12]
                candidates = list(raw_dir.glob(f"{prefix}*.json"))
                if candidates:
                    raw_file = candidates[0]

        if raw_file is None:
            continue

        raw_found += 1
        try:
            raw_item: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"backfill: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            continue

        if backfill_campaign(campaign, raw_item):
            store.upsert_campaign(conn, campaign)
            updated += 1

    return {"scanned": scanned, "raw_found": raw_found, "updated": updated}


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: бекфіл БД + re-export cases.json."""
    import argparse  # noqa: PLC0415

    from . import config, export, store  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec backfill: заповнює engagement/date/goal_reached з raw-кешу"
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів"
    )
    parser.add_argument(
        "--out", default=str(config.CASES_JSON), help="Шлях до cases.json для re-export"
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    raw_dir = Path(args.raw_dir)

    if not db_path.exists():
        print(f"backfill: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    result = backfill_database(conn, raw_dir)

    # re-export cases.json
    exported = export.export_cases(conn, args.out)

    print(
        f"backfill: scanned={result['scanned']} raw_found={result['raw_found']} "
        f"updated={result['updated']} exported={exported}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
