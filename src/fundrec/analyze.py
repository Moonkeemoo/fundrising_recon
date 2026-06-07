"""ANALYZE: 4 осі успіху + нормалізація + тренди + крос-таби.

Всі функції — чисті (приймають списки/словники, не звертаються до БД).
Spec §6: порівнюємо подібне з подібним (в межах категорії цілі);
обсяг у лог-шкалі (power-law); virality=null за відсутності даних;
кожен агрегат несе N (чесна магнітуда).
"""
from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Sequence

from .schema import Case

# ── утилітки ──────────────────────────────────────────────────────────────────


def goal_category(goal: str) -> str:
    """Повертає частину до '/' у назві цілі: 'military/fpv' → 'military'."""
    return goal.split("/")[0]


def quarter(date_iso_or_year: str) -> str:
    """Перетворює дату або рік на позначення кварталу: '2024-04-15' → '2024-Q2'."""
    s = date_iso_or_year.strip()
    if len(s) == 4:
        # тільки рік
        return f"{s}-Q1"
    try:
        d = date.fromisoformat(s[:10])
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}"
    except ValueError:
        return f"{s[:4]}-Q1"


# ── вісь VOLUME ───────────────────────────────────────────────────────────────


def compute_volume_scores(cases: Sequence[Case]) -> dict[str, float | None]:
    """Перцентильний ранг log10(amount_usd) в межах категорії цілі.

    Returns:
        dict mapping case.id → float 0..1 або None якщо amount_usd відсутній.
    """
    # Групуємо за категорією цілі
    by_cat: dict[str, list[tuple[str, float]]] = {}
    none_ids: set[str] = set()

    for c in cases:
        cat = goal_category(c.goal)
        if c.amount_usd is None:
            none_ids.add(c.id)
            continue
        log_val = math.log10(c.amount_usd) if c.amount_usd > 0 else -math.inf
        by_cat.setdefault(cat, []).append((c.id, log_val))

    scores: dict[str, float | None] = {cid: None for cid in none_ids}

    for cat, items in by_cat.items():
        n = len(items)
        if n == 1:
            scores[items[0][0]] = 1.0
            continue
        # Сортуємо за log_val для присвоєння рангу
        sorted_items = sorted(items, key=lambda x: x[1])
        for rank, (cid, _) in enumerate(sorted_items):
            scores[cid] = rank / (n - 1)

    return scores


# ── вісь SPEED ────────────────────────────────────────────────────────────────


def time_to_goal_days(case: Case) -> int | None:
    """Повертає кількість активних днів (≥1) або None якщо дати відсутні."""
    if not case.date_start or not case.date_end:
        return None
    try:
        d0 = date.fromisoformat(case.date_start)
        d1 = date.fromisoformat(case.date_end)
        return max(1, (d1 - d0).days)
    except ValueError:
        return None


def compute_speed(case: Case) -> float | None:
    """velocity = amount_uah / active_days; None якщо даних не вистачає."""
    if case.amount_uah is None:
        return None
    days = time_to_goal_days(case)
    if days is None:
        return None
    return case.amount_uah / days


# ── вісь VIRALITY ─────────────────────────────────────────────────────────────

# Ваги сигналів (задокументовано для прозорості).
_VIRALITY_WEIGHTS = {"mentions": 0.4, "shares": 0.35, "peak": 0.25}
# Нормалізаційні шкали (грубі орієнтири для press-coverage у UA-контексті).
_VIRALITY_SCALES = {"mentions": 10_000.0, "shares": 5_000.0, "peak": 15_000.0}


def compute_virality(signals: dict | None) -> float | None:
    """Зважений нормалізований композит соц-сигналів.

    Spec §6 та Invariant #5: повертає None (НЕ 0) якщо signals=None або всі
    поля None/відсутні — щоб не плутати «немає даних» з «нульовою віральністю».

    Args:
        signals: словник з ключами mentions/shares/peak (всі опційні).

    Returns:
        float 0..1 або None.
    """
    if not signals:
        return None

    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in _VIRALITY_WEIGHTS.items():
        val = signals.get(key)
        if val is None:
            continue
        scale = _VIRALITY_SCALES[key]
        normalized = min(float(val) / scale, 1.0)
        weighted_sum += normalized * weight
        total_weight += weight

    if total_weight == 0.0:
        return None

    return weighted_sum / total_weight


# ── вісь REPEATABILITY ────────────────────────────────────────────────────────


def compute_repeatability(actor_id: str, cases: Sequence[Case]) -> float:
    """Оцінка повторюваності/утримання актора (0..1).

    Формула:
        base = log(campaign_count + 1) / log(max_scale + 1)  (нормалізований лог)
        bonus = 0.2 за наявність кампаній у >=2 різних кварталах
        score = min(1.0, base + bonus)

    Щоб порівнювати акторів: 1 кампанія → ~0.14, 10 → ~0.66, 30 → ~0.87 (без бонусу).
    """
    _MAX_SCALE = 50  # насичення: 50+ кампаній → base → 1.0
    actor_cases = [c for c in cases if c.actor_id == actor_id]
    count = len(actor_cases)
    if count == 0:
        return 0.0

    base = math.log(count + 1) / math.log(_MAX_SCALE + 1)

    # Визначаємо унікальні квартали з дат
    quarters_seen: set[str] = set()
    for c in actor_cases:
        if c.date_start:
            quarters_seen.add(quarter(c.date_start))
        elif c.year:
            quarters_seen.add(f"{c.year}-Q1")

    bonus = 0.2 if len(quarters_seen) >= 2 else 0.0
    return min(1.0, base + bonus)


# ── TREND SERIES ──────────────────────────────────────────────────────────────

_ALL_QUARTERS = [
    f"{y}-Q{q}" for y in range(2022, 2027) for q in range(1, 5)
]


def _case_quarter(case: Case) -> str | None:
    """Визначає квартал кейсу (з date_start або year)."""
    if case.date_start:
        return quarter(case.date_start)
    if case.year:
        return f"{case.year}-Q1"
    return None


def trend_series(
    cases: Sequence[Case],
    *,
    dimension: str | None,
    metric: str,
) -> list[dict]:
    """Квартальні точки 2022→2026 з метрикою і N.

    Args:
        cases: список кейсів.
        dimension: 'goal' | 'style' | 'method' | None.
        metric: 'count' | 'volume_usd' | 'median_speed'.

    Returns:
        list of {period, key (if dimension), value, n}
    """
    # Розбиваємо кейси по кварталах і (якщо dimension) по ключах
    # Bucket: (period, key) -> list[Case]
    buckets: dict[tuple[str, str], list[Case]] = {}

    for c in cases:
        period = _case_quarter(c)
        if period is None:
            continue
        if period not in _ALL_QUARTERS:
            continue

        # Визначаємо ключ(і) за dimension
        if dimension is None:
            keys_for_case = ["_total"]
        elif dimension == "goal":
            keys_for_case = [goal_category(c.goal)]
        elif dimension == "style":
            keys_for_case = c.style if c.style else ["_none"]
        elif dimension == "method":
            keys_for_case = c.method if c.method else ["_none"]
        else:
            keys_for_case = ["_total"]

        for key in keys_for_case:
            bucket_key = (period, key)
            buckets.setdefault(bucket_key, []).append(c)

    # Збираємо унікальні ключі для ітерації по всіх кварталах
    all_keys: set[str] = set()
    for _, k in buckets:
        all_keys.add(k)
    if not all_keys:
        all_keys = {"_total"}

    result: list[dict] = []
    for period in _ALL_QUARTERS:
        for key in sorted(all_keys):
            bucket = buckets.get((period, key), [])
            n = len(bucket)
            value = _compute_metric(bucket, metric)
            point: dict = {"period": period, "value": value, "n": n}
            if dimension is not None:
                point["key"] = key
            result.append(point)

    # Якщо немає dimension — прибираємо порожні ключ-"_total" з output
    if dimension is None:
        # strip internal _total key, restructure
        result2 = []
        for pt in result:
            result2.append({"period": pt["period"], "value": pt["value"], "n": pt["n"]})
        return result2

    return result


def _compute_metric(cases: list[Case], metric: str) -> float | None:
    """Обчислює метрику для набору кейсів."""
    if metric == "count":
        return len(cases)
    if metric == "volume_usd":
        vals = [c.amount_usd for c in cases if c.amount_usd is not None]
        return sum(vals) if vals else None
    if metric == "median_speed":
        speeds = [compute_speed(c) for c in cases]
        speeds = [s for s in speeds if s is not None]
        return statistics.median(speeds) if speeds else None
    return None


# ── CROSSTAB ──────────────────────────────────────────────────────────────────

def _axis_values(case: Case, axis: str) -> list[str]:
    """Повертає список значень осі для кейсу."""
    if axis == "goal":
        return [goal_category(case.goal)]
    if axis == "style":
        return case.style if case.style else []
    if axis == "method":
        return case.method if case.method else []
    return []


def crosstab(
    cases: Sequence[Case],
    *,
    axis_a: str,
    axis_b: str,
    metric: str,
) -> list[dict]:
    """Крос-таб: клітинки {a, b, value, n} для пар осей.

    Мульти-тег (style[], method[]) — кейс вносить внесок у кожну пару тегів.
    Метрики: 'count' | 'volume_usd'.
    """
    # Accumulate case lists per (a, b) cell
    cells: dict[tuple[str, str], list[Case]] = {}

    for c in cases:
        a_vals = _axis_values(c, axis_a)
        b_vals = _axis_values(c, axis_b)
        for a in a_vals:
            for b in b_vals:
                cells.setdefault((a, b), []).append(c)

    result = []
    for (a, b), cell_cases in sorted(cells.items()):
        n = len(cell_cases)
        if metric == "count":
            value: float | None = float(n)
        elif metric == "volume_usd":
            vals = [c.amount_usd for c in cell_cases if c.amount_usd is not None]
            value = sum(vals) if vals else None
        else:
            value = None
        result.append({"a": a, "b": b, "value": value, "n": n})

    return result


# ── KPIS ──────────────────────────────────────────────────────────────────────

def kpis(cases: Sequence[Case]) -> dict:
    """Ключові показники для набору кейсів (вже відфільтрованих).

    Returns:
        {total_usd, count, median_speed, n_verified}
    """
    case_list = list(cases)
    total_usd = sum(c.amount_usd for c in case_list if c.amount_usd is not None)
    count = len(case_list)
    speeds = [compute_speed(c) for c in case_list]
    speeds = [s for s in speeds if s is not None]
    median_speed = statistics.median(speeds) if speeds else None
    n_verified = sum(
        1 for c in case_list if c.verification_status in ("verified", "cross-checked")
    )
    return {
        "total_usd": total_usd,
        "count": count,
        "median_speed": median_speed,
        "n_verified": n_verified,
    }
