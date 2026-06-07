"""CLI P0: seed -> collect (Monobank) -> extract -> validate -> store -> export.

Мережа й LLM інжектяться (_fetch/_complete) для тестів; за замовчуванням —
живі monobank.fetch_jar та extract._live_complete.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import config, export, extract, store, validate
from .collect import monobank
from .schema import Actor, Source


def run_pipeline(
    seed_path: Path | str,
    *,
    db_path: Path | str = config.DB_PATH,
    out_path: Path | str = config.CASES_JSON,
    model: str = config.EXTRACT_MODEL,
    _fetch: Callable[..., dict] | None = None,
    _complete: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    fetch = _fetch or monobank.fetch_jar
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    conn = store.connect(db_path)
    store.init_db(conn)

    stored = 0
    problems: dict[str, list[str]] = {}
    for entry in seed:
        actor = Actor(id=entry["actor_id"], name=entry["actor_name"], type=entry["actor_type"])
        store.upsert_actor(conn, actor)
        jar_id = entry["jar_id"]
        raw = fetch(jar_id)
        source = Source(url=raw["url"], type="structured", tier=1,
                        access="public", license="unknown", actor_id=actor.id)
        store.upsert_source(conn, source)
        case = extract.extract_case(raw, source, case_id=entry["case_id"],
                                    actor_id=actor.id, model=model, _complete=_complete)
        case_problems = validate.validate_case(case)
        if case_problems:
            problems[case.id] = case_problems
        store.upsert_case(conn, case)
        stored += 1

    exported = export.export_cases(conn, out_path)
    return {"stored": stored, "exported": exported, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    seed_path = Path(argv[0]) if argv else config.SEEDS_DIR / "p0_seed.json"
    result = run_pipeline(seed_path)
    print(f"stored={result['stored']} exported={result['exported']} "
          f"problems={len(result['problems'])}")
    for cid, probs in result["problems"].items():
        print(f"  [{cid}] {probs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
