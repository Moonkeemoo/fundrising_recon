"""Аудит повноти збору: детермінований аналіз дірок + read-only --report-only.

Для кожного збору (донат-призначення = одиниця) детермінований core перевіряє
наявність усієї аналітично потрібної інформації й класифікує кожне відсутнє поле:
  - PRESENT              — є;
  - MISSING_FILLABLE     — нема, але є сигнал, що добірне → конкретна дія;
  - MISSING_UNAVAILABLE  — нема й принципово недоступне (НЕ зациклюватись).

Цей модуль НЕ робить жодного I/O добору (мережа/LLM/рендер банки) — лише чистий
аналіз сигналів + агрегований звіт. Виконавець (фетч дірок) — окреме завдання,
що викликатиме gap_actions().

Сигнали заповнюваності → дія (spec §«Класифікація дірки»):
  призначення нема + у raw є лінк            → RESOLVE_LINKS
  сума/ціль нема + є jar-id                   → RENDER_JAR
  пости/охоплення/база нема + handle/jar      → SEARCH_POSTS
  стиль (tone/form/face/cta) порожнє + raw    → LLM_EXTRACT_STYLE
  теми порожні                                → RETAG_THEME (+ LLM_DIAGNOSE з raw)
  залишковий hard-gap (призначення/сума)      → LLM_DIAGNOSE
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from typing import Any

from . import config, store
from .analyze import (
    campaign_handle,
    channel_baselines,
    derive_themes,
    reach_resonance,
)
from .dedup import campaign_jar_id
from .dedup_pass import _find_raw_for_campaign
from .destinations import extract_destinations
from .schema import Campaign

# ── статуси полів ────────────────────────────────────────────────────────────
PRESENT = "present"
MISSING_FILLABLE = "missing_fillable"
MISSING_UNAVAILABLE = "missing_unavailable"

# ── дії добору ───────────────────────────────────────────────────────────────
RESOLVE_LINKS = "RESOLVE_LINKS"
RENDER_JAR = "RENDER_JAR"
SEARCH_POSTS = "SEARCH_POSTS"
LLM_EXTRACT_STYLE = "LLM_EXTRACT_STYLE"
RETAG_THEME = "RETAG_THEME"
LLM_DIAGNOSE = "LLM_DIAGNOSE"

# Поля, що враховуються для is_complete (усі обовʼязкові виміри).
_REQUIRED_FIELDS = (
    "has_destination",
    "amount_uah",
    "goal_amount",
    "post_count",
    "reach_total",
    "reach_resonance",
    "tone",
    "form_factor",
    "face",
    "cta_type",
    "themes",
)

# Евристика «у raw є лінк» (нерозвʼязане/скорочене посилання, що варто chase).
_LINK_HINTS = ("http", "t.me", "send.monobank", "privat", "bit.ly", "cutt.ly", "is.gd", "tinyurl")


# ── звіт ─────────────────────────────────────────────────────────────────────


@dataclass
class CompletenessReport:
    """Повнота одного збору: статус кожного поля + дії добору."""

    campaign_id: str
    fields: dict[str, str] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True якщо ВСІ обовʼязкові поля PRESENT або MISSING_UNAVAILABLE.

        Тобто не лишилось жодної добірної дірки (missing_fillable).
        """
        return all(
            self.fields.get(f) in (PRESENT, MISSING_UNAVAILABLE) for f in _REQUIRED_FIELDS
        )

    @property
    def n_missing_fillable(self) -> int:
        """Кількість полів зі статусом MISSING_FILLABLE."""
        return sum(1 for s in self.fields.values() if s == MISSING_FILLABLE)


# ── допоміжні детектори сигналів (чисті) ─────────────────────────────────────


def _raw_text_blob(raw: dict) -> str:
    """Збирає всі текстові поля raw у один рядок для пошуку лінків."""
    parts: list[str] = []
    for key in ("text", "raw_text", "description"):
        v = raw.get(key)
        if v:
            parts.append(str(v))
    for link in raw.get("links") or []:
        if link:
            parts.append(str(link))
    return " ".join(parts)


def _raw_has_link(raw: dict | None) -> bool:
    """Чи містить raw будь-яке URL/лінк-посилання (евристика для RESOLVE_LINKS)."""
    if not raw:
        return False
    blob = _raw_text_blob(raw).lower()
    return any(hint in blob for hint in _LINK_HINTS)


def _has_destination(campaign: Campaign, raw: dict | None) -> bool:
    """Чи має збір призначення (jar з провенансу АБО призначення з raw)."""
    if campaign_jar_id(campaign) is not None:
        return True
    if raw is not None and extract_destinations(raw, _client=None):
        return True
    return False


def _campaign_themes(campaign: Campaign) -> list[str]:
    """Export-derived теми з title + playbook_note (keyword-tagger)."""
    text = (campaign.title or "") + " " + (campaign.playbook_note or "")
    return derive_themes(text)


# ── ядро: аудит одного збору ─────────────────────────────────────────────────


def audit_campaign(
    campaign: Campaign,
    raw: dict | None,
    *,
    baselines: dict[str, float],
    post_count: int = 0,
    reach_total: float | None = None,
) -> CompletenessReport:
    """Детермінований аудит повноти одного збору (чиста функція, без I/O добору).

    Args:
        campaign: збір (Campaign).
        raw: raw-пост (dict) або None якщо не знайдено.
        baselines: медіани каналів (analyze.channel_baselines) для reach_resonance.
        post_count: кількість привʼязаних постів (export-derived, передає caller).
        reach_total: Σ views привʼязаних постів (None якщо невідомо — honest null).

    Returns:
        CompletenessReport зі статусом кожного поля та deduped-списком дій.
    """
    fields: dict[str, str] = {}
    actions: list[str] = []

    has_jar = campaign_jar_id(campaign) is not None
    handle = campaign_handle(campaign)
    has_handle_or_jar = has_jar or (handle is not None)

    # — призначення —
    if _has_destination(campaign, raw):
        fields["has_destination"] = PRESENT
    elif _raw_has_link(raw):
        fields["has_destination"] = MISSING_FILLABLE
        actions.append(RESOLVE_LINKS)
    else:
        fields["has_destination"] = MISSING_UNAVAILABLE

    # — сума —
    if campaign.amount_uah is not None:
        fields["amount_uah"] = PRESENT
    elif has_jar:
        fields["amount_uah"] = MISSING_FILLABLE
        actions.append(RENDER_JAR)
    else:
        fields["amount_uah"] = MISSING_UNAVAILABLE

    # — ціль —
    if campaign.goal_amount is not None:
        fields["goal_amount"] = PRESENT
    elif has_jar:
        fields["goal_amount"] = MISSING_FILLABLE
        actions.append(RENDER_JAR)
    else:
        fields["goal_amount"] = MISSING_UNAVAILABLE

    # — пости —
    if post_count >= 1:
        fields["post_count"] = PRESENT
    elif has_handle_or_jar:
        fields["post_count"] = MISSING_FILLABLE
        actions.append(SEARCH_POSTS)
    else:
        fields["post_count"] = MISSING_UNAVAILABLE

    # — охоплення —
    if reach_total is not None:
        fields["reach_total"] = PRESENT
    elif has_handle_or_jar:
        fields["reach_total"] = MISSING_FILLABLE
        actions.append(SEARCH_POSTS)
    else:
        fields["reach_total"] = MISSING_UNAVAILABLE

    # — резонанс (база каналу) —
    if reach_resonance(campaign, baselines) is not None:
        fields["reach_resonance"] = PRESENT
    elif handle is not None:
        fields["reach_resonance"] = MISSING_FILLABLE
        actions.append(SEARCH_POSTS)
    else:
        fields["reach_resonance"] = MISSING_UNAVAILABLE

    # — стиль (списки tone/form_factor; скаляри face/cta_type) —
    for name, value in (("tone", campaign.tone), ("form_factor", campaign.form_factor)):
        if value:
            fields[name] = PRESENT
        elif raw is not None:
            fields[name] = MISSING_FILLABLE
            actions.append(LLM_EXTRACT_STYLE)
        else:
            fields[name] = MISSING_UNAVAILABLE

    for name, value in (("face", campaign.face), ("cta_type", campaign.cta_type)):
        if value:
            fields[name] = PRESENT
        elif raw is not None:
            fields[name] = MISSING_FILLABLE
            actions.append(LLM_EXTRACT_STYLE)
        else:
            fields[name] = MISSING_UNAVAILABLE

    # — теми —
    if _campaign_themes(campaign):
        fields["themes"] = PRESENT
    else:
        fields["themes"] = MISSING_FILLABLE
        actions.append(RETAG_THEME)  # завжди дешево
        if raw is not None:
            actions.append(LLM_DIAGNOSE)  # LLM може дотегувати конкретний предмет

    # — залишковий hard-gap: призначення/сума відсутні, але є raw → LLM читає raw —
    if raw is not None and (
        fields["has_destination"] != PRESENT or fields["amount_uah"] != PRESENT
    ):
        actions.append(LLM_DIAGNOSE)

    return CompletenessReport(
        campaign_id=campaign.id,
        fields=fields,
        actions=sorted(set(actions)),
    )


def gap_actions(report: CompletenessReport) -> list[str]:
    """Список дій добору для звіту (для виклику виконавцем-фетчером)."""
    return report.actions


# ── агрегація по БД ──────────────────────────────────────────────────────────


def _post_metrics(conn: sqlite3.Connection, campaign_id: str) -> tuple[int, float | None]:
    """Export-honest деривація (post_count, reach_total) з привʼязаних постів.

    Дзеркалить export._aggregate_posts: reach_total = Σ views (None якщо жоден
    view невідомий — НЕ 0); post_count = кількість привʼязаних постів.
    """
    linked = store.load_posts(conn, campaign_id=campaign_id)
    views = [p.views for p in linked if p.views is not None]
    reach_total = sum(views) if views else None
    return len(linked), reach_total


def audit_database(
    conn: sqlite3.Connection,
    *,
    baselines: dict[str, float] | None = None,
    raw_dir: Path | str | None = None,
) -> list[CompletenessReport]:
    """Аудитує всі реальні збори (is_campaign True) живої БД.

    Для кожного збору знаходить raw (через _find_raw_for_campaign), деривує
    post_count/reach_total з привʼязаних постів (export-honest) і повертає
    один CompletenessReport. baselines рахуються раз, якщо не передано.
    Read-only: жодного фетчу/експорту.
    """
    rd = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
    if baselines is None:
        baselines = channel_baselines(store.load_posts(conn))

    campaigns = [c for c in store.load_campaigns(conn) if c.is_campaign is True]
    reports: list[CompletenessReport] = []
    for c in campaigns:
        raw = _find_raw_for_campaign(c, rd)
        post_count, reach_total = _post_metrics(conn, c.id)
        reports.append(
            audit_campaign(
                c,
                raw,
                baselines=baselines,
                post_count=post_count,
                reach_total=reach_total,
            )
        )
    return reports


# ═════════════════════════════════════════════════════════════════════════════
# ВИКОНАВЕЦЬ (executor): точковий добір дірок + re-export
#
# Кожен handler заповнює ОДНЕ поле для ОДНОГО збору, реюзаючи наявні модулі.
# Усі зовнішні ефекти (мережа/LLM/рендер банки) ІНʼЄКТУЮТЬСЯ → тести без I/O.
# Handler-и ідемпотентні: повторний запуск нічого нового не додає (резюмованість).
# ═════════════════════════════════════════════════════════════════════════════

# Provenance-ключ, під яким зберігаємо знайдене призначення донату (банку),
# щоб dedup.campaign_jar_id побачив його source_url симетрично до relink/dedup.
_DESTINATION_PROV_KEY = "destination"
_TIER1_CONFIDENCE = 0.95


def _attach_jar_destination(campaign: Campaign, jar_id: str) -> None:
    """Прикріплює банку як призначення донату через provenance (tier-1).

    Пише source_url банки у provenance[_DESTINATION_PROV_KEY] — той самий шлях,
    яким campaign_jar_id зчитує jar-id (симетрично до relink/dedup).
    """
    jar_url = f"https://send.monobank.ua/jar/{jar_id}"
    campaign.provenance[_DESTINATION_PROV_KEY] = {
        "source_url": jar_url,
        "confidence": _TIER1_CONFIDENCE,
        "tier": 1,
        "note": "resolved donation destination",
    }


def fill_resolve_links(
    conn: Any,
    campaign: Campaign,
    raw: dict | None,
    *,
    _resolve: Any | None = None,
) -> bool:
    """RESOLVE_LINKS: re-скан raw на призначення (вкл. скорочені лінки).

    Використовує jars.jar_ids_from_raw_resolved (прямі + скорочувачі через
    _resolve-клієнт) для пошуку банки, якої збору бракує. Якщо знайдено нову
    банку — прикріплює її як призначення (provenance[destination]) і зберігає.

    _resolve інжектує link-resolver (httpx-подібний клієнт) для тестів;
    за замовчуванням — реальне розкриття скорочувачів (live: # pragma: no cover).

    Повертає True якщо щось додано, інакше False.
    """
    if raw is None:
        return False
    if campaign_jar_id(campaign) is not None:
        return False  # призначення вже є

    from .jars import jar_ids_from_raw_resolved  # noqa: PLC0415

    jar_ids = jar_ids_from_raw_resolved(raw, _client=_resolve)
    if not jar_ids:
        return False  # priv-призначення вже ловить extract_destinations(raw) у audit
    _attach_jar_destination(campaign, jar_ids[0])
    store.upsert_campaign(conn, campaign)
    return True


def fill_render_jar(
    conn: Any,
    campaign: Campaign,
    *,
    _render: Any | None = None,
    cache_path: Any | None = None,
    force: bool = True,
) -> bool:
    """RENDER_JAR: рендерить банку збору й заповнює amount_uah/goal_amount.

    Для jar-id збору (dedup.campaign_jar_id) викликає
    jar_render.render_jar_cached(force=force). Якщо банка повернула суму/ціль,
    яких збору бракує — застосовує tier-1 (ingest._apply_jar_to_campaign:
    встановлює amount_uah + provenance, + goal_amount) і зберігає (verified).

    Закрита банка / нема числа / нема jar → False (no-op, НЕ помилка).
    _render інжектується (jar_id -> body_text | None).
    """
    jar_id = campaign_jar_id(campaign)
    if jar_id is None:
        return False

    from .collect.jar_render import render_jar_cached  # noqa: PLC0415
    from .ingest import _apply_jar_to_campaign  # noqa: PLC0415

    cp = cache_path if cache_path is not None else config.JARS_CACHE_PATH
    try:
        jar_data = render_jar_cached(jar_id, cache_path=cp, _render=_render, force=force)
    except Exception as exc:  # noqa: BLE001
        print(f"audit: render_jar failed for {jar_id}: {exc}")
        return False

    if jar_data is None:
        return False
    amount = jar_data.get("amount_uah")
    goal = jar_data.get("goal_amount")
    if amount is None and goal is None:
        return False

    changed = False
    if amount is not None and campaign.amount_uah is None:
        _apply_jar_to_campaign(campaign, jar_data)  # ставить amount + tier-1 prov (+goal)
        changed = True
    elif goal is not None and campaign.goal_amount is None:
        # лише ціль (суми вже немає сенсу перезаписувати / amount відсутній у банці)
        campaign.goal_amount = goal
        changed = True

    if changed:
        store.upsert_campaign(conn, campaign)
        store.set_campaign_verification(
            conn, campaign.id, "verified", reason="audit: monobank jar tier-1"
        )
    return changed


def _write_raw_post(raw_dir: Path, post: dict) -> None:
    """Записує raw-пост у raw_dir під sha256[:16](source_url).json (ingest-схема).

    Ідемпотентно: один і той самий source_url → той самий файл (перезапис).
    """
    import hashlib  # noqa: PLC0415

    url = post.get("source_url") or post.get("url")
    if not url:
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    (raw_dir / f"{file_id}.json").write_text(
        json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fill_search_posts(
    conn: Any,
    campaign: Campaign,
    *,
    raw_dir: Path | str | None = None,
    pages: int = 2,
    _client: Any | None = None,
) -> int:
    """SEARCH_POSTS: дофетчує пости каналу збору й релінкує пости→збори.

    Визначає handle збору (analyze.campaign_handle); якщо є — тягне додаткові
    пости через telegram_web.fetch_channel_web(handle, pages, _client), пише їх
    у raw-кеш, потім перебудовує лінки posts.build_posts(conn, raw_dir).

    Повертає к-ть постів, привʼязаних саме до цього збору ПІСЛЯ релінку (приріст
    охоплення/бази каналу). Ідемпотентно: повторний фетч тих самих постів →
    raw-файли перезаписуються, лінк-набір стабільний → приріст 0.
    """
    handle = campaign_handle(campaign)
    if handle is None:
        return 0

    from .collect.telegram_web import fetch_channel_web  # noqa: PLC0415
    from .posts import build_posts  # noqa: PLC0415

    rd = Path(raw_dir) if raw_dir is not None else config.RAW_DIR

    before = len(store.load_posts(conn, campaign_id=campaign.id))

    try:
        fetched = fetch_channel_web(handle, pages=pages, _client=_client)
    except Exception as exc:  # noqa: BLE001
        print(f"audit: fetch_channel_web failed for {handle}: {exc}")
        return 0

    new_files = 0
    for post in fetched:
        if not post.get("source_url"):
            continue
        # platform/channel мають бути присутні для коректного релінку
        post.setdefault("platform", "telegram")
        post.setdefault("channel", handle)
        _write_raw_post(rd, post)
        new_files += 1

    if new_files == 0:
        return 0

    build_posts(conn, rd)

    after = len(store.load_posts(conn, campaign_id=campaign.id))
    return max(0, after - before)


# Стилеві поля, які заповнює LLM_EXTRACT_STYLE (лише ПОРОЖНІ).
_STYLE_LIST_FIELDS = ("tone", "form_factor")
_STYLE_SCALAR_FIELDS = ("face", "cta_type")


def fill_llm_style(
    conn: Any,
    campaign: Campaign,
    raw: dict | None,
    *,
    _complete: Any | None = None,
) -> bool:
    """LLM_EXTRACT_STYLE: заповнює ЛИШЕ порожні стилеві поля з raw через LLM.

    Якщо є raw і якесь зі стилевих полів (tone/form_factor/face/cta_type)
    порожнє — викликає extract.parse_campaign_extraction на raw і переносить
    ТІЛЬКИ значення для порожніх полів (наявні не чіпає). Зберігає при зміні.

    _complete інжектує LLM-бекенд (prompt -> dict) для тестів.
    Повертає True якщо щось заповнено.
    """
    if raw is None:
        return False
    needs = (
        any(not getattr(campaign, f) for f in _STYLE_LIST_FIELDS)
        or any(not getattr(campaign, f) for f in _STYLE_SCALAR_FIELDS)
    )
    if not needs:
        return False

    from . import extract as _extract  # noqa: PLC0415
    from .schema import Source  # noqa: PLC0415

    complete = _complete if _complete is not None else _extract._live_complete
    src_url = (campaign.provenance.get("campaign") or {}).get("source_url") or ""
    source = Source(url=src_url, type="social", tier=3, access="public", license="unknown")
    prompt = _extract.build_campaign_prompt(raw, source)
    try:
        obj = complete(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"audit: llm_style complete failed for {campaign.id}: {exc}")
        return False

    parsed, _creatives, _partners = _extract.parse_campaign_extraction(
        obj, raw, source, model="audit-style",
        campaign_id=campaign.id, actor_id=campaign.actor_id,
    )

    changed = False
    for f in _STYLE_LIST_FIELDS:
        if not getattr(campaign, f) and getattr(parsed, f):
            setattr(campaign, f, getattr(parsed, f))
            changed = True
    for f in _STYLE_SCALAR_FIELDS:
        if not getattr(campaign, f) and getattr(parsed, f):
            setattr(campaign, f, getattr(parsed, f))
            changed = True

    if changed:
        store.upsert_campaign(conn, campaign)
    return changed


def fill_diagnose(
    conn: Any,
    campaign: Campaign,
    raw: dict | None,
    *,
    _complete: Any | None = None,
) -> dict:
    """LLM_DIAGNOSE: LLM читає raw для hard-residual (нема призначення/суми/теми).

    Повертає структурований hint:
      {found_destination?, found_goal?, theme_items?, search_hint?}.
    Прямо застосовує те, що можна:
      - found_destination з jar-лінком → прикріплює призначення (як resolve);
      - found_goal (число) → ставить goal_amount якщо порожнє;
      - theme_items → дописує у playbook_note (щоб derive_themes на export зловив).
    Зберігає при зміні. _complete інжектує LLM-бекенд.
    """
    if raw is None:
        return {}

    from . import extract as _extract  # noqa: PLC0415
    from .jars import extract_jar_ids  # noqa: PLC0415

    complete = _complete if _complete is not None else _extract._live_complete
    blob = _raw_text_blob(raw)
    prompt = (
        "Прочитай сирий запис збору коштів і поверни СТРОГО JSON з полями (усі опційні):\n"
        '{ "found_destination": str|null,  # пряме посилання на банку/конверт, якщо є у тексті\n'
        '  "found_goal": number|null,       # озвучена ціль збору (число у грн), якщо є\n'
        '  "theme_items": [str],            # конкретні предмети (дрон, тепловізор, авто...)\n'
        '  "search_hint": str|null }        # де ще шукати (напр. «ціль у закріпленому пості»)\n\n'
        "Не вигадуй: чого немає в тексті — став null/порожньо.\n\n"
        f"Сирий запис: {blob[:2000]}\n"
    )
    try:
        hint = complete(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"audit: llm_diagnose complete failed for {campaign.id}: {exc}")
        return {}
    if not isinstance(hint, dict):
        return {}

    changed = False

    dest = hint.get("found_destination")
    if dest and campaign_jar_id(campaign) is None:
        jar_ids = extract_jar_ids(str(dest))
        if jar_ids:
            _attach_jar_destination(campaign, jar_ids[0])
            changed = True

    goal = hint.get("found_goal")
    if goal is not None and campaign.goal_amount is None:
        try:
            campaign.goal_amount = float(goal)
            changed = True
        except (TypeError, ValueError):
            pass

    items = hint.get("theme_items") or []
    if items and not _campaign_themes(campaign):
        extra = " ".join(str(x) for x in items if x)
        if extra.strip():
            campaign.playbook_note = ((campaign.playbook_note or "") + " " + extra).strip()
            changed = True

    if changed:
        store.upsert_campaign(conn, campaign)
    return hint


# ── оркестратор ──────────────────────────────────────────────────────────────

# Порядок виконання дій: детерміновані спершу, LLM — на залишок.
_ACTION_ORDER = (
    RESOLVE_LINKS,
    RENDER_JAR,
    SEARCH_POSTS,
    LLM_EXTRACT_STYLE,
    LLM_DIAGNOSE,
)
_LLM_ACTIONS = frozenset({LLM_EXTRACT_STYLE, LLM_DIAGNOSE})


def _present_counts(reports: list[CompletenessReport]) -> dict[str, int]:
    """{field: к-ть зборів зі статусом PRESENT} по всіх обовʼязкових полях."""
    return {
        f: sum(1 for r in reports if r.fields.get(f) == PRESENT)
        for f in _REQUIRED_FIELDS
    }


def run_audit(
    conn: Any,
    *,
    fields: list[str] | None = None,
    use_llm: bool = True,
    max_items: int | None = None,
    only_actions: set[str] | None = None,
    dry_run: bool = False,
    raw_dir: Path | str | None = None,
    channels_file: Path | str | None = None,
    out_path: Path | str | None = None,
    jars_cache_path: Path | str | None = None,
    pages: int = 2,
    _render: Any | None = None,
    _client: Any | None = None,
    _complete: Any | None = None,
    now: str | None = None,  # noqa: ARG001 — зарезервовано для майбутнього часу
) -> dict:
    """Виконавець: аудитує БД, добирає дірки точковими handler-ами, re-export.

    Для кожного звіту (cap max_items) у порядку _ACTION_ORDER викликає
    відповідний handler, якщо дія потрібна (є у report.actions), пройшла
    only_actions-фільтр і (не LLM* АБО use_llm). dry_run рахує намічені дії
    без записів/фетчу. Наприкінці (крім dry_run) — re-export + повторний аудит
    для AFTER-покриття.

    Повертає summary:
      {before, after, actions_run, n_campaigns,
       fully_complete_before, fully_complete_after}.
    """
    rd = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
    op = out_path if out_path is not None else config.CASES_JSON

    reports = audit_database(conn, raw_dir=rd)
    if max_items is not None:
        reports = reports[:max_items]

    before = _present_counts(reports)
    fully_complete_before = sum(1 for r in reports if r.is_complete)
    actions_run: dict[str, int] = {a: 0 for a in _ACTION_ORDER}

    # Мапа id → Campaign для handler-ів (потрібні живі обʼєкти).
    campaigns_by_id = {c.id: c for c in store.load_campaigns(conn)}

    for report in reports:
        camp = campaigns_by_id.get(report.campaign_id)
        if camp is None:
            continue
        raw = _find_raw_for_campaign(camp, rd)
        wanted = [a for a in _ACTION_ORDER if a in report.actions]
        if only_actions is not None:
            wanted = [a for a in wanted if a in only_actions]
        if not use_llm:
            wanted = [a for a in wanted if a not in _LLM_ACTIONS]
        if not wanted:
            continue

        done: list[str] = []
        for action in wanted:
            if dry_run:
                actions_run[action] += 1
                done.append(action)
                continue
            ok = _dispatch_action(
                action, conn, camp, raw,
                raw_dir=rd, channels_file=channels_file,
                jars_cache_path=jars_cache_path, pages=pages,
                _render=_render, _client=_client, _complete=_complete,
            )
            if ok:
                actions_run[action] += 1
                done.append(action)

        print(f"audit: {report.campaign_id} actions={wanted} done={done}")

    if dry_run:
        return {
            "before": before,
            "after": before,
            "actions_run": actions_run,
            "n_campaigns": len(reports),
            "fully_complete_before": fully_complete_before,
            "fully_complete_after": fully_complete_before,
            "dry_run": True,
        }

    # Re-export (теми перетегуються derive_themes на цьому кроці).
    from . import export as _export  # noqa: PLC0415

    jcp = jars_cache_path if jars_cache_path is not None else config.JARS_CACHE_PATH
    try:
        _export.export_cases(conn, op, jars_cache_path=jcp, raw_dir=str(rd))
    except Exception as exc:  # noqa: BLE001
        print(f"audit: export failed: {exc}")

    after_reports = audit_database(conn, raw_dir=rd)
    if max_items is not None:
        after_reports = after_reports[:max_items]
    after = _present_counts(after_reports)
    fully_complete_after = sum(1 for r in after_reports if r.is_complete)

    return {
        "before": before,
        "after": after,
        "actions_run": actions_run,
        "n_campaigns": len(reports),
        "fully_complete_before": fully_complete_before,
        "fully_complete_after": fully_complete_after,
    }


def _dispatch_action(
    action: str,
    conn: Any,
    campaign: Campaign,
    raw: dict | None,
    *,
    raw_dir: Path,
    channels_file: Path | str | None,
    jars_cache_path: Path | str | None,
    pages: int,
    _render: Any | None,
    _client: Any | None,
    _complete: Any | None,
) -> bool:
    """Маршрутизує одну дію до її handler-а. Повертає True якщо щось заповнено.

    channels_file наразі не використовується (handle береться з provenance збору),
    але приймається для сумісності CLI/інтерфейсу.
    """
    if action == RESOLVE_LINKS:
        return fill_resolve_links(conn, campaign, raw, _resolve=_client)
    if action == RENDER_JAR:
        return fill_render_jar(
            conn, campaign, _render=_render, cache_path=jars_cache_path, force=True
        )
    if action == SEARCH_POSTS:
        return fill_search_posts(
            conn, campaign, raw_dir=raw_dir, pages=pages, _client=_client
        ) > 0
    if action == LLM_EXTRACT_STYLE:
        return fill_llm_style(conn, campaign, raw, _complete=_complete)
    if action == LLM_DIAGNOSE:
        hint = fill_diagnose(conn, campaign, raw, _complete=_complete)
        return bool(hint)
    return False


# ── звіт-матриця (read-only) ─────────────────────────────────────────────────

_ALL_ACTIONS = (
    RESOLVE_LINKS,
    RENDER_JAR,
    SEARCH_POSTS,
    LLM_EXTRACT_STYLE,
    RETAG_THEME,
    LLM_DIAGNOSE,
)


def _format_report(reports: list[CompletenessReport]) -> str:
    """Формує текстову матрицю повноти + breakdown дірок + агрегат дій."""
    n = len(reports)
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"АУДИТ ПОВНОТИ ЗБОРІВ — {n} реальних зборів")
    lines.append("=" * 60)

    # Per-field матриця: present / fillable / unavailable.
    lines.append("")
    lines.append(f"{'поле':<18} {'present':>9} {'fillable':>9} {'unavail':>9}")
    lines.append("-" * 48)
    for fname in _REQUIRED_FIELDS:
        n_present = sum(1 for r in reports if r.fields.get(fname) == PRESENT)
        n_fill = sum(1 for r in reports if r.fields.get(fname) == MISSING_FILLABLE)
        n_unav = sum(1 for r in reports if r.fields.get(fname) == MISSING_UNAVAILABLE)
        lines.append(f"{fname:<18} {f'{n_present}/{n}':>9} {n_fill:>9} {n_unav:>9}")

    # Повністю повні збори.
    n_complete = sum(1 for r in reports if r.is_complete)
    lines.append("")
    lines.append(f"Повністю повні (без добірних дірок): {n_complete}/{n}")

    # Агрегат дій: скільки зборів потребує кожної дії.
    lines.append("")
    lines.append("Потрібні дії добору (к-ть зборів):")
    lines.append("-" * 48)
    for act in _ALL_ACTIONS:
        cnt = sum(1 for r in reports if act in r.actions)
        lines.append(f"  {act:<20} {cnt:>4}")

    lines.append("=" * 60)
    return "\n".join(lines)


_VALID_ACTIONS = frozenset(_ACTION_ORDER)


def _format_run_summary(summary: dict) -> str:
    """Матриця before→after по полях + агрегат actions_run для run_audit."""
    lines: list[str] = []
    n = summary["n_campaigns"]
    tag = " [DRY-RUN — без записів]" if summary.get("dry_run") else ""
    lines.append("=" * 60)
    lines.append(f"ВИКОНАВЕЦЬ ДОБОРУ — {n} зборів{tag}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"{'поле':<18} {'before':>9} {'after':>9}")
    lines.append("-" * 40)
    before = summary["before"]
    after = summary["after"]
    for fname in _REQUIRED_FIELDS:
        b = before.get(fname, 0)
        a = after.get(fname, 0)
        delta = f"  (+{a - b})" if a > b else ""
        lines.append(f"{fname:<18} {f'{b}/{n}':>9} {f'{a}/{n}':>9}{delta}")
    lines.append("")
    lines.append(
        f"Повністю повні: {summary['fully_complete_before']}"
        f" → {summary['fully_complete_after']} / {n}"
    )
    lines.append("")
    lines.append("Виконані дії (к-ть успішних добо́рів):")
    lines.append("-" * 40)
    for act in _ACTION_ORDER:
        lines.append(f"  {act:<20} {summary['actions_run'].get(act, 0):>4}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.audit [--report-only | добір дірок].

    --report-only → друкує матрицю повноти над живою БД (read-only, без фетчу).
    Default      → run_audit: добір дірок (resolve-links/render-jar/search-posts/
                   llm-style/diagnose) + re-export + матриця before/after.
    Прапори: --no-llm, --max N, --only-actions a,b, --dry-run, --fields, --db, --raw-dir.
    """
    parser = argparse.ArgumentParser(description="Аудит повноти зборів фандрайзингу.")
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД.")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія raw-кешу."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Лише друкувати матрицю повноти (read-only, без добору).",
    )
    parser.add_argument(
        "--max", type=int, default=None, help="Обмежити кількість зборів."
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Не запускати LLM-дії (style/diagnose)."
    )
    parser.add_argument(
        "--only-actions",
        default=None,
        help="Фільтр дій через кому (напр. RESOLVE_LINKS,RENDER_JAR).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Лише намічені дії (без записів/фетчу/LLM/рендеру).",
    )
    parser.add_argument(
        "--fields",
        default=None,
        help="Підмножина полів (зарезервовано; наразі аудитуються всі).",
    )
    args = parser.parse_args(argv)

    conn = store.connect(args.db)
    store.init_db(conn)

    # --report-only — read-only матриця (без змін).
    if args.report_only:
        reports = audit_database(conn, raw_dir=args.raw_dir)
        if args.max is not None:
            reports = reports[: args.max]
        print(_format_report(reports))
        return 0

    only_actions: set[str] | None = None
    if args.only_actions:
        only_actions = {a.strip().upper() for a in args.only_actions.split(",") if a.strip()}
        unknown = only_actions - _VALID_ACTIONS
        if unknown:
            print(f"audit: невідомі дії у --only-actions: {sorted(unknown)}", file=sys.stderr)
            return 2

    fields = None
    if args.fields:
        fields = [f.strip() for f in args.fields.split(",") if f.strip()]

    summary = run_audit(
        conn,
        fields=fields,
        use_llm=not args.no_llm,
        max_items=args.max,
        only_actions=only_actions,
        dry_run=args.dry_run,
        raw_dir=args.raw_dir,
    )
    print(_format_run_summary(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
