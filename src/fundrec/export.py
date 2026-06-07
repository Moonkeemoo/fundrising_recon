"""Дамп БД -> data/cases.json для дашборда (P4 + F5).

Payload: {count, cases:[...], analytics:{...}, campaigns:[...], creatives:[...], partners:[...]}
analytics вбудовано (включно з campaign_analytics), щоб кокпіт рендерив без
повторного обчислення. Зворотна сумісність: ключі `count`/`cases`/`analytics`
завжди присутні.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, schema, store
from .analyze import derive_themes, engagement_rate, rel_resonance_map
from .pipeline_analyze import build_analytics


def export_cases(conn: sqlite3.Connection, out_path: Path | str = config.CASES_JSON) -> int:
    cases = store.load_cases(conn)
    analytics = build_analytics(conn)
    campaigns = store.load_campaigns(conn)
    creatives = store.load_creatives(conn)
    partners = store.load_partners(conn)

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
