"""Оркестратор ANALYZE: читає з БД, заповнює 4 осі, записує назад.

Єдине місце, де analyze.py і store.py зустрічаються.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from . import store
from .analyze import (
    campaign_axis_summary,
    campaign_crosstab,
    channel_baselines,
    compute_repeatability,
    compute_speed,
    compute_virality,
    compute_volume_scores,
    crosstab,
    goal_success_rate,
    kpis,
    parse_campaign_date,
    reach_resonance_axis_summary,
    trend_momentum,
    trend_series,
    what_raises_most,
    what_works_now,
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
        "campaign_analytics": _build_campaign_analytics(conn),
        "radar": _build_radar(conn),
    }


def _build_radar(conn: sqlite3.Connection) -> dict:
    """Радар «Що працює зараз»: what_works_now + momentum.

    now = max parse_campaign_date серед кампаній (детермінований).
    Якщо жодної дати немає — використовуємо сьогоднішню дату (ISO).

    Returns:
        {
          now: "<iso>",
          what_works_now: {channel:[...], tone:[...], form_factor:[...], goal:[...]},
          momentum: {goal:[...], channel:[...], tone:[...]}
        }
    """
    import datetime  # noqa: PLC0415

    campaigns = store.load_campaigns(conn)
    # Базові медіани каналів для reach-резонансу (рахуємо раз з усіх постів)
    baselines = channel_baselines(store.load_posts(conn))

    # Знаходимо максимальну відому дату кампанії
    dates = [parse_campaign_date(c) for c in campaigns]
    valid_dates = [d for d in dates if d is not None]
    if valid_dates:
        now_str = max(valid_dates)
    else:
        now_str = datetime.date.today().isoformat()

    wwn = {
        "channel": what_works_now(
            campaigns, now=now_str, by="channels", min_n=1, baselines=baselines),
        "tone": what_works_now(
            campaigns, now=now_str, by="tone", min_n=1, baselines=baselines),
        "form_factor": what_works_now(
            campaigns, now=now_str, by="form_factor", min_n=1, baselines=baselines),
        "goal": what_works_now(
            campaigns, now=now_str, by="goal", min_n=1, baselines=baselines),
    }
    momentum = {
        "goal": trend_momentum(campaigns, axis="goal", now=now_str, baselines=baselines),
        "channel": trend_momentum(
            campaigns, axis="channels", now=now_str, baselines=baselines),
        "tone": trend_momentum(campaigns, axis="tone", now=now_str, baselines=baselines),
    }
    # Вісь грошей: що приносить найбільше ₴ (медіана amount_uah у розрізі осі)
    what_raises = {
        "channel": what_raises_most(campaigns, by="channels", min_n=3),
        "tone": what_raises_most(campaigns, by="tone", min_n=3),
        "form_factor": what_raises_most(campaigns, by="form_factor", min_n=3),
        "goal": what_raises_most(campaigns, by="goal", min_n=3),
    }
    return {
        "now": now_str,
        "what_works_now": wwn,
        "what_raises_most": what_raises,
        "momentum": momentum,
    }


def _build_campaign_analytics(conn: sqlite3.Connection) -> dict:
    """Блок глибокої аналітики кампаній (F5) для дашборда.

    Returns:
        {
          kpis: {n_campaigns, n_creatives, n_partners, total_spend (nullable)},
          crosstabs: {channel_volume, format_engagement, tone_virality,
                      face_volume, goal_channel},
          axis_summaries: {tone_amount, cta_amount, face_amount, channel_amount},
        }
    """
    campaigns = store.load_campaigns(conn)
    creatives = store.load_creatives(conn)
    partners = store.load_partners(conn)
    # Базові медіани каналів для reach-резонансу
    baselines = channel_baselines(store.load_posts(conn))

    spends = [c.spend for c in campaigns if c.spend is not None]
    total_spend = sum(spends) if spends else None

    kpi_data = {
        "n_campaigns": len(campaigns),
        "n_creatives": len(creatives),
        "n_partners": len(partners),
        "total_spend": total_spend,
    }

    crosstabs = {
        "channel_volume": campaign_crosstab(
            campaigns, axis_a="channels", axis_b="goal_category", metric="amount_uah"),
        # engagement тепер чесно None → метрика reach (реальні views)
        "format_engagement": campaign_crosstab(
            campaigns, axis_a="form_factor", axis_b="channels", metric="reach"),
        "tone_virality": campaign_crosstab(
            campaigns, axis_a="tone", axis_b="channels", metric="reach"),
        "face_volume": campaign_crosstab(
            campaigns, axis_a="face", axis_b="goal_category", metric="amount_uah"),
        "goal_channel": campaign_crosstab(
            campaigns, axis_a="goal_category", axis_b="channels", metric="count"),
    }

    axis_summaries = {
        "tone_amount": campaign_axis_summary(campaigns, axis="tone", metric="amount_uah"),
        "cta_amount": campaign_axis_summary(campaigns, axis="cta_type", metric="amount_uah"),
        "face_amount": campaign_axis_summary(campaigns, axis="face", metric="amount_uah"),
        "channel_amount": campaign_axis_summary(campaigns, axis="channels", metric="amount_uah"),
        # Медіана reach-резонансу по осях (замість фейкового engagement)
        "tone_resonance": reach_resonance_axis_summary(
            campaigns, axis="tone", baselines=baselines),
        "channel_resonance": reach_resonance_axis_summary(
            campaigns, axis="channels", baselines=baselines),
    }

    # Успіх = amount_uah >= goal_amount (де обидва відомі); ключ лише при n>=3
    success_rates = {
        "tone": goal_success_rate(campaigns, axis="tone", min_n=3),
        "channels": goal_success_rate(campaigns, axis="channels", min_n=3),
    }

    return {
        "kpis": kpi_data,
        "crosstabs": crosstabs,
        "axis_summaries": axis_summaries,
        "success_rates": success_rates,
    }
