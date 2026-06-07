"""Дамп БД -> data/cases.json для дашборда (P4 + F5).

Payload: {count, cases:[...], analytics:{...}, campaigns:[...], creatives:[...], partners:[...]}
analytics вбудовано (включно з campaign_analytics), щоб кокпіт рендерив без
повторного обчислення. Зворотна сумісність: ключі `count`/`cases`/`analytics`
завжди присутні.

Збагачення velocity: кампанії з jar-провенансом отримують jar_velocity_uah_per_day
та jar_span_days якщо в jars_cache.json є ≥2 snapshots для відповідного jar_id.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config, schema, store
from .analyze import derive_themes, engagement_rate, rel_resonance_map
from .dedup import campaign_jar_id
from .jars import jar_velocity
from .pipeline_analyze import build_analytics


def _load_jars_cache(cache_path: Path) -> dict[str, Any]:
    """Завантажує jars_cache.json; повертає {} якщо файл відсутній або пошкоджений."""
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def export_cases(
    conn: sqlite3.Connection,
    out_path: Path | str = config.CASES_JSON,
    *,
    jars_cache_path: Path | str = config.JARS_CACHE_PATH,
) -> int:
    cases = store.load_cases(conn)
    analytics = build_analytics(conn)
    campaigns = store.load_campaigns(conn)
    creatives = store.load_creatives(conn)
    partners = store.load_partners(conn)

    # Завантажуємо jars_cache один раз
    jars_cache = _load_jars_cache(Path(jars_cache_path))

    # Збагачуємо кампанії обчисленими метриками (не змінюємо схему — тільки export-dict)
    rrmap = rel_resonance_map(campaigns)
    campaign_dicts = []
    for c in campaigns:
        d = schema.campaign_to_dict(c)
        d["engagement_rate"] = engagement_rate(c)
        d["rel_resonance"] = rrmap.get(c.id)
        # Теми — keyword-derived з title + playbook_note (export-time, не в схемі)
        text = (c.title or "") + " " + (c.playbook_note or "")
        d["themes"] = derive_themes(text)

        # Velocity: збагачуємо якщо є jar-провенанс і кеш з ≥2 snapshots
        jar_id = campaign_jar_id(c)
        d["jar_velocity_uah_per_day"] = None
        d["jar_span_days"] = None
        if jar_id and jar_id in jars_cache:
            history = jars_cache[jar_id].get("history") or []
            vel = jar_velocity(history)
            if vel["uah_per_day"] is not None:
                d["jar_velocity_uah_per_day"] = vel["uah_per_day"]
                d["jar_span_days"] = vel["span_days"]

        campaign_dicts.append(d)

    payload = {
        "count": len(cases),
        "cases": [schema.case_to_dict(c) for c in cases],
        "analytics": analytics,
        "campaigns": campaign_dicts,
        "creatives": [schema.creative_to_dict(a) for a in creatives],
        "partners": [schema.partner_to_dict(p) for p in partners],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cases)
