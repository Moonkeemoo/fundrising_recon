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
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.audit --report-only.

    --report-only → друкує матрицю повноти над живою БД (без фетчу/експорту).
    Без --report-only → дружнє повідомлення (виконавець — окреме завдання).
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
        "--max", type=int, default=None, help="Обмежити кількість зборів у звіті."
    )
    args = parser.parse_args(argv)

    if not args.report_only:
        print("виконавець ще не підключений — використай --report-only")
        return 0

    conn = store.connect(args.db)
    store.init_db(conn)
    reports = audit_database(conn, raw_dir=args.raw_dir)
    if args.max is not None:
        reports = reports[: args.max]
    print(_format_report(reports))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
