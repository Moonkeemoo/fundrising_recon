"""Тонкий оркестратор верифікації кейсів (P2).

verify_cases(conn, *, _judge=None) -> dict:
  1. Завантажує всі кейси.
  2. Групує за dedup.dedup_key.
  3. detect_conflict на кожну групу.
  4. assess_verification на кожен кейс.
  5. critique_case (з injectable _judge) для подальшого підвищення статусу.
  6. set_verification → записує результат у БД.
  7. Повертає {status: count}.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Callable

from . import store
from .crosscheck import assess_verification, detect_conflict
from .critic import critique_case
from .dedup import dedup_key


def verify_cases(
    conn: sqlite3.Connection,
    *,
    _judge: Callable[[str], dict] | None = None,
) -> dict[str, int]:
    """Run full verification pipeline. Returns {verification_status: count}."""
    cases = store.load_cases(conn)
    if not cases:
        return {}

    # Group by dedup_key
    groups: dict[str, list] = defaultdict(list)
    for c in cases:
        groups[dedup_key(c)].append(c)

    # Detect conflicts per group
    conflict_ids: set[str] = set()
    for group in groups.values():
        if detect_conflict(group):
            for c in group:
                conflict_ids.add(c.id)

    # Assess + critique + persist
    summary: dict[str, int] = defaultdict(int)
    for case in cases:
        conflicting = case.id in conflict_ids
        base_status = assess_verification(case, conflicting=conflicting)
        final_status, reason = critique_case(case, base_status=base_status, _judge=_judge)
        store.set_verification(conn, case.id, final_status, reason=reason or None)
        summary[final_status] += 1

    return dict(summary)
