"""Дамп БД -> data/cases.json для дашборда (P4).

Payload: {count, cases:[...], analytics:{...}}
analytics вбудовано, щоб кокпіт рендерив без повторного обчислення.
Зворотна сумісність: ключі `count` і `cases` завжди присутні.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, schema, store
from .pipeline_analyze import build_analytics


def export_cases(conn: sqlite3.Connection, out_path: Path | str = config.CASES_JSON) -> int:
    cases = store.load_cases(conn)
    analytics = build_analytics(conn)
    payload = {
        "count": len(cases),
        "cases": [schema.case_to_dict(c) for c in cases],
        "analytics": analytics,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cases)
