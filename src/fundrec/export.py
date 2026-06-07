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
from .destinations import extract_destinations
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


def _aggregate_posts(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    """Агрегує охоплення/таймлайн з постів, привʼязаних до збору.

    Повертає dict з ключами:
      reach_total      — Σ views привʼязаних постів (None якщо жоден view невідомий);
      engagement_total — Σ engagement (None якщо жоден невідомий);
      post_count       — кількість привʼязаних постів;
      channel_count    — кількість унікальних каналів;
      first_post/last_post — найраніша/найпізніша дата (None якщо дат немає);
      post_channels    — список унікальних каналів (порядок появи);
      posts            — компактний список {date, channel, views, url} за датою.

    Honest null: суми = None якщо немає ЖОДНОГО відомого значення (не 0).
    """
    linked = store.load_posts(conn, campaign_id=campaign_id)
    if not linked:
        return {
            "reach_total": None,
            "engagement_total": None,
            "post_count": 0,
            "channel_count": 0,
            "first_post": None,
            "last_post": None,
            "post_channels": [],
            "posts": [],
        }

    views = [p.views for p in linked if p.views is not None]
    eng = [p.engagement for p in linked if p.engagement is not None]
    dates = [p.date for p in linked if p.date]
    channels: list[str] = []
    for p in linked:
        if p.channel and p.channel not in channels:
            channels.append(p.channel)

    compact = sorted(
        (
            {
                "date": p.date,
                "channel": p.channel,
                "views": p.views,
                "url": p.source_url,
            }
            for p in linked
        ),
        key=lambda d: (d["date"] is None, d["date"] or ""),
    )

    return {
        "reach_total": sum(views) if views else None,
        "engagement_total": sum(eng) if eng else None,
        "post_count": len(linked),
        "channel_count": len(channels),
        "first_post": min(dates) if dates else None,
        "last_post": max(dates) if dates else None,
        "post_channels": channels,
        "posts": compact,
    }


def _campaign_has_destination(c, raw_dir: Path | None) -> bool:
    """Чи має кампанія БУДЬ-ЯКЕ призначення донату (jar/priv).

    Деривація (export-time, не у схемі):
    1. jar з provenance (campaign_jar_id) — найнадійніший сигнал, без I/O.
    2. Якщо передано raw_dir — призначення з raw-поста (extract_destinations,
       offline _client=None) — ловить privat-конверти, яких немає в provenance.
    """
    if campaign_jar_id(c) is not None:
        return True
    if raw_dir is not None:
        from .dedup_pass import _find_raw_for_campaign  # noqa: PLC0415

        raw = _find_raw_for_campaign(c, raw_dir)
        if raw and extract_destinations(raw, _client=None):
            return True
    return False


def export_cases(
    conn: sqlite3.Connection,
    out_path: Path | str = config.CASES_JSON,
    *,
    jars_cache_path: Path | str = config.JARS_CACHE_PATH,
    raw_dir: Path | str | None = None,
) -> int:
    cases = store.load_cases(conn)
    analytics = build_analytics(conn)
    campaigns = store.load_campaigns(conn)
    creatives = store.load_creatives(conn)
    partners = store.load_partners(conn)

    # Завантажуємо jars_cache один раз
    jars_cache = _load_jars_cache(Path(jars_cache_path))

    # raw_dir для деривації has_destination (опц.; default config.RAW_DIR якщо існує)
    rd: Path | None
    if raw_dir is not None:
        rd = Path(raw_dir)
    elif config.RAW_DIR.exists():
        rd = config.RAW_DIR
    else:
        rd = None

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

        # has_destination: чи є куди донатити (jar/priv) — export-derived, не у схемі
        d["has_destination"] = _campaign_has_destination(c, rd)

        # Інформаційна історія / охоплення: агрегат привʼязаних постів (export-derived)
        d.update(_aggregate_posts(conn, c.id))

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
