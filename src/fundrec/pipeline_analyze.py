"""Оркестратор ANALYZE: читає з БД, заповнює 4 осі, записує назад.

Єдине місце, де analyze.py і store.py зустрічаються.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from . import store
from .analyze import (
    compute_repeatability,
    compute_speed,
    compute_virality,
    compute_volume_scores,
    crosstab,
    kpis,
    trend_series,
)
from .rates import to_usd
from .schema import Case


def analyze_all(
    conn: sqlite3.Connection,
    *,
    signals_by_case: dict | None = None,
    _client: Callable[[str], list] | None = None,
) -> dict:
    """Завантажує кейси+акторів, заповнює 4 осі, зберігає назад у БД.

    Args:
        conn: з'єднання SQLite.
        signals_by_case: {case_id: {mentions, shares, peak, ...}} — соц-сигнали.
        _client: ін'єктований HTTP-клієнт для курсу НБУ.

    Returns:
        summary dict з кількістю оброблених кейсів.
    """
    signals = signals_by_case or {}
    cases = store.load_cases(conn)

    # 1) Заповнюємо amount_usd через курс НБУ
    for c in cases:
        if c.amount_usd is None and c.amount_uah is not None:
            date_str = c.date_start or (str(c.year) + "-01-01" if c.year else None)
            c.amount_usd = to_usd(c.amount_uah, date_str, _client=_client)

    # 2) Volume score (перцентиль у категорії)
    vol_scores = compute_volume_scores(cases)
    for c in cases:
        c.volume_score = vol_scores.get(c.id)

    # 3) Speed (UAH / активний_день)
    for c in cases:
        c.speed = compute_speed(c)

    # 4) Virality (з соц-сигналів; null якщо немає)
    for c in cases:
        c.virality_score = compute_virality(signals.get(c.id))

    # 5) Repeatability (на рівні актора)
    # Кешуємо по actor_id щоб не рахувати N разів
    actor_cases: dict[str, list[Case]] = {}
    for c in cases:
        actor_cases.setdefault(c.actor_id, []).append(c)

    for c in cases:
        c.repeatability = compute_repeatability(c.actor_id, actor_cases.get(c.actor_id, []))

    # 6) Зберігаємо назад у БД
    for c in cases:
        store.upsert_case(conn, c)

    return {"cases_processed": len(cases)}


def build_analytics(conn: sqlite3.Connection) -> dict:
    """Збирає повний аналітичний блок для дашборда.

    Передбачає, що `analyze_all` вже викликаний і осі заповнені.

    Returns:
        {
          kpis: {...},
          trends: {
            count_by_quarter: [...],
            volume_by_quarter: [...],
            median_speed_by_quarter: [...],
            count_by_goal: [...],
            count_by_method: [...],
            count_by_style: [...],
          },
          crosstabs: {
            goal_method: [...],
            goal_style: [...],
          },
          generated_for_counts: {total_cases: N},
        }
    """
    cases = store.load_cases(conn)

    kpi_data = kpis(cases)

    trends = {
        "count_by_quarter": trend_series(cases, dimension=None, metric="count"),
        "volume_by_quarter": trend_series(cases, dimension=None, metric="volume_usd"),
        "median_speed_by_quarter": trend_series(cases, dimension=None, metric="median_speed"),
        "count_by_goal": trend_series(cases, dimension="goal", metric="count"),
        "count_by_method": trend_series(cases, dimension="method", metric="count"),
        "count_by_style": trend_series(cases, dimension="style", metric="count"),
    }

    crosstabs = {
        "goal_method": crosstab(cases, axis_a="goal", axis_b="method", metric="count"),
        "goal_style": crosstab(cases, axis_a="goal", axis_b="style", metric="count"),
    }

    return {
        "kpis": kpi_data,
        "trends": trends,
        "crosstabs": crosstabs,
        "generated_for_counts": {"total_cases": len(cases)},
    }
