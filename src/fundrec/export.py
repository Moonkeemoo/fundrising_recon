"""Дамп БД -> data/cases.json для дашборда (P4)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, schema, store


def export_cases(conn: sqlite3.Connection, out_path: Path | str = config.CASES_JSON) -> int:
    cases = store.load_cases(conn)
    payload = {
        "count": len(cases),
        "cases": [schema.case_to_dict(c) for c in cases],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cases)
