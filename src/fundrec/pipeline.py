"""Пост-дайджест пайплайн: classify → enrich text → enrich jars → dedup → export.

run_postprocess(conn, raw_dir, *, judge, render, complete, ...) -> dict:
  Запускає всі пост-дайджестові кроки в правильному порядку.
  Ін'єктовані залежності (judge/render/complete) роблять функцію тестабельною.

CLI: python -m fundrec.pipeline [--db PATH] [--raw-dir PATH] [--out PATH]
                                  [--no-classify] [--no-enrich] [--no-dedup]
  Єдина команда для фіналізації після dig.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def run_postprocess(
    conn: Any,
    raw_dir: Path | str,
    *,
    judge: Any = None,
    render: Any = None,
    complete: Any = None,
    do_classify: bool = True,
    do_enrich: bool = True,
    do_dedup: bool = True,
) -> dict:
    """Запускає пост-дайджестовий пайплайн у правильному порядку.

    Порядок:
      1. classify_relevance_db  — встановлює is_campaign прапор (non-destructive).
      2. enrich_amounts_from_text — tier-2 суми з тексту raw.
      3. enrich_jars             — tier-1 суми з Monobank jar (потребує render).
      4. dedup_database          — зливає дублікати (зберігає is_campaign — Unit 1 fix).
      5. complete (export)       — зберігає cases.json (ін'єктований або export.export_cases).

    Args:
        conn:        SQLite connection (ініціалізована БД).
        raw_dir:     Директорія сирих кешів.
        judge:       fn(prompt: str) -> dict — LLM-суддя для classify.
                     За замовч. relevance._live_judge_relevance (live LLM).
        render:      fn(jar_id: str) -> dict|None — рендерер jar банки.
                     За замовч. enrich._live_render (playwright/fetch).
        complete:    fn(conn, out_path) -> int — функція експорту.
                     За замовч. export.export_cases.
        do_classify: Якщо False — пропустити classify.
        do_enrich:   Якщо False — пропустити обидва enrich кроки.
        do_dedup:    Якщо False — пропустити dedup.

    Returns:
        dict з ключами: classify, enrich_text, enrich_jars, dedup, exported.
    """
    from . import config  # noqa: PLC0415
    from .dedup_pass import dedup_database  # noqa: PLC0415
    from .enrich import enrich_amounts_from_text, enrich_jars  # noqa: PLC0415
    from .export import export_cases  # noqa: PLC0415
    from .relevance import classify_relevance_db  # noqa: PLC0415

    raw_dir = Path(raw_dir)

    classify_result: dict[str, int] = {
        "scanned": 0, "relevant": 0, "topical": 0, "no_raw": 0, "llm_calls": 0,
    }
    enrich_text_result: dict[str, int] = {"scanned": 0, "updated": 0}
    enrich_jars_result: dict[str, int] = {
        "scanned": 0, "jars_found": 0, "rendered_ok": 0, "updated": 0,
    }
    dedup_result: dict[str, int] = {
        "before": 0, "after": 0, "merged": 0, "groups_collapsed": 0,
    }

    # ── 1. Classify ────────────────────────────────────────────────────────
    if do_classify:
        _judge_fn = judge  # може бути None → classify використає live judge
        classify_result = classify_relevance_db(conn, raw_dir, judge=_judge_fn)

    # ── 2. Enrich text (tier-2 суми) ──────────────────────────────────────
    if do_enrich:
        enrich_text_result = enrich_amounts_from_text(conn, raw_dir=raw_dir)

    # ── 3. Enrich jars (tier-1 суми) ──────────────────────────────────────
    if do_enrich:
        enrich_jars_result = enrich_jars(conn, raw_dir=raw_dir, render=render)

    # ── 4. Dedup ───────────────────────────────────────────────────────────
    if do_dedup:
        dedup_result = dedup_database(conn)

    # ── 5. Export ──────────────────────────────────────────────────────────
    if complete is None:
        complete = export_cases  # pragma: no cover

    out_path = config.CASES_JSON
    exported = complete(conn, out_path)

    return {
        "classify": classify_result,
        "enrich_text": enrich_text_result,
        "enrich_jars": enrich_jars_result,
        "dedup": dedup_result,
        "exported": exported,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.pipeline — єдина команда фіналізації після dig."""
    import argparse  # noqa: PLC0415

    from . import config, export, store  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description=(
            "fundrec pipeline: пост-дайджестовий пайплайн "
            "(classify → enrich → dedup → export)"
        )
    )
    parser.add_argument(
        "--db",
        default=str(config.DB_PATH),
        help="Шлях до SQLite БД (default: config.DB_PATH)",
    )
    parser.add_argument(
        "--raw-dir",
        default=str(config.RAW_DIR),
        help="Директорія сирих кешів (default: config.RAW_DIR)",
    )
    parser.add_argument(
        "--out",
        default=str(config.CASES_JSON),
        help="Шлях до cases.json для export (default: config.CASES_JSON)",
    )
    parser.add_argument(
        "--no-classify",
        action="store_true",
        help="Пропустити крок classify_relevance_db",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Пропустити обидва кроки enrich (text + jars)",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Пропустити крок dedup_database",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    raw_dir = Path(args.raw_dir)
    out_path = Path(args.out)

    if not db_path.exists():
        print(f"pipeline: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    store.init_db(conn)

    def _complete(conn_: Any, _out: Any) -> int:
        return export.export_cases(conn_, out_path)

    summary = run_postprocess(
        conn,
        raw_dir,
        do_classify=not args.no_classify,
        do_enrich=not args.no_enrich,
        do_dedup=not args.no_dedup,
        complete=_complete,
    )

    cl = summary["classify"]
    et = summary["enrich_text"]
    ej = summary["enrich_jars"]
    dd = summary["dedup"]
    exported = summary["exported"]

    print(
        f"pipeline: classify scanned={cl['scanned']} relevant={cl['relevant']} "
        f"topical={cl['topical']} no_raw={cl['no_raw']} llm_calls={cl['llm_calls']}"
    )
    print(f"pipeline: enrich_text scanned={et['scanned']} updated={et['updated']}")
    print(
        f"pipeline: enrich_jars scanned={ej['scanned']} jars_found={ej['jars_found']} "
        f"rendered_ok={ej['rendered_ok']} updated={ej['updated']}"
    )
    print(
        f"pipeline: dedup before={dd['before']} after={dd['after']} "
        f"merged={dd['merged']} groups_collapsed={dd['groups_collapsed']}"
    )
    print(f"pipeline: exported={exported} → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
