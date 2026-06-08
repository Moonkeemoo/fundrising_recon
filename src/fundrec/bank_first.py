"""Bank-first («зборо-центрична») інгестія: підняття осиротілих банок у збір-кампанії.

Кожен фандрайзинг моделюється як призначення донату (банка Monobank). Корпус
сирих постів містить унікальні банки, частина яких так і не стала кампанією
(«осиротілі» банки — реальні збори, що лежать у зібраних постах, але ніколи не
розкопані як джерело). Цей модуль детерміновано піднімає КОЖНУ унікальну
осиротілу банку у збір-кампанію (рендер jar + агрегація постів; БЕЗ LLM —
стилеві поля лишаються None і заповнюються пізнішим аудит-пасом) та дедуплікує,
щоб не створити другу кампанію для банки, що вже є призначенням.

Публічні функції:
  corpus_banks(raw_dir) -> {jar_id: [post-meta]}
      Sweep усіх raw-постів; для кожної банки збирає компактні пост-мети.
  orphan_banks(conn, raw_dir) -> {jar_id: [post-meta]}
      corpus_banks мінус банки, що вже є призначенням якоїсь кампанії.
  build_campaign_from_bank(jar_id, post_metas, *, render=None, now=None) -> Campaign
      Детерміноване будівництво кампанії-збору з банки + пост-мет.
  run_bank_first(conn, ...) -> dict
      Оркестратор: orphan_banks → render → build → dedup-upsert → build_posts →
      export. Ідемпотентний (стабільні id + дедуп).

CLI: python -m fundrec.bank_first [--max N] [--no-render] [--report-only]
                                   [--raw-dir PATH] [--db PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from . import config, store
from .dedup import campaign_jar_id
from .jars import jar_ids_from_raw
from .schema import Actor, Campaign

# Provenance-ключ призначення донату — той самий, яким audit/relink пишуть банку,
# а dedup.campaign_jar_id її зчитує (симетрія обовʼязкова для дедупу).
_DESTINATION_PROV_KEY = "destination"
_JAR_URL_TMPL = "https://send.monobank.ua/jar/{jar_id}"

# Confidence-рівні
_CONF_WITH_AMOUNT = 0.9
_CONF_NO_AMOUNT = 0.5
_TIER1_CONF = 0.9
_REACH_CONF = 0.35

_TITLE_MAX = 60
# Сигнальні токени «збір/донат»-тексту для деривації title без рендеру.
_SIGNAL_TOKENS = ("донат", "збір", "збiр", "зібрати", "збираємо")


# ── деривація channel/title ──────────────────────────────────────────────────


def _channel_from_url(url: str | None) -> str | None:
    """Деривує канал з t.me-URL: https://t.me/<channel>/123 → <channel>.

    Підтримує t.me/s/<channel>/... (web-форму) та t.me/<channel>/...
    Повертає None якщо не t.me або канал не визначити.
    """
    if not url:
        return None
    try:
        parsed = urlparse(str(url))
    except Exception:  # noqa: BLE001
        return None
    host = (parsed.hostname or "").lower()
    if "t.me" not in host:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    # t.me/s/<channel>/<id> — пропускаємо префікс 's'
    if parts[0] == "s" and len(parts) >= 2:
        return parts[1]
    return parts[0]


def _post_meta(raw: dict) -> dict:
    """Будує компактну пост-мету з raw-поста."""
    url = raw.get("source_url") or raw.get("url") or ""
    return {
        "channel": _channel_from_url(url),
        "source_url": url,
        "text": raw.get("text") or raw.get("raw_text") or raw.get("description") or "",
        "date": raw.get("date") or raw.get("published"),
        "views": raw.get("views"),
    }


def _primary_meta(post_metas: list[dict]) -> dict | None:
    """Пост-мета з максимальними переглядами (для primary_channel/reach-провенансу)."""
    if not post_metas:
        return None
    with_views = [m for m in post_metas if m.get("views") is not None]
    if with_views:
        return max(with_views, key=lambda m: m["views"])
    return post_metas[0]


def _derive_title(jar_id: str, post_metas: list[dict]) -> str:
    """Title без рендеру: найдовший «збір/донат»-текст, обрізаний до ~60 симв.

    Fallback: f"Збір (банка {jar_id})".
    """
    candidates = [
        (m.get("text") or "").strip()
        for m in post_metas
        if any(tok in (m.get("text") or "").lower() for tok in _SIGNAL_TOKENS)
    ]
    candidates = [c for c in candidates if c]
    if candidates:
        best = max(candidates, key=len)
        return best[:_TITLE_MAX].strip()
    return f"Збір (банка {jar_id})"


def _norm_date(d: str | None) -> str | None:
    """Нормалізує дату до YYYY-MM-DD (для min/max/year). None якщо нема."""
    if not d:
        return None
    s = str(d).strip()
    return s[:10] if len(s) >= 10 else s  # noqa: PLR2004


# ── corpus_banks / orphan_banks ──────────────────────────────────────────────


def corpus_banks(raw_dir: Path | str | None = None) -> dict[str, list[dict]]:
    """Sweep усіх raw json-файлів → {jar_id: [post-meta, ...]}.

    Для кожного raw-поста, для кожної банки (jar_ids_from_raw) додає компактну
    пост-мету {channel, source_url, text, date, views}. Пост-мети дедупляться за
    source_url у межах однієї банки.
    """
    rd = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
    result: dict[str, list[dict]] = {}
    seen_urls: dict[str, set[str]] = {}

    if not rd.exists():
        return result

    for raw_file in sorted(rd.glob("*.json")):
        try:
            raw: dict = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"bank_first: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            continue
        if not isinstance(raw, dict):
            continue
        jar_ids = jar_ids_from_raw(raw)
        if not jar_ids:
            continue
        meta = _post_meta(raw)
        url = meta["source_url"]
        for jar_id in jar_ids:
            bucket = result.setdefault(jar_id, [])
            urls = seen_urls.setdefault(jar_id, set())
            if url and url in urls:
                continue
            if url:
                urls.add(url)
            bucket.append(meta)
    return result


def orphan_banks(
    conn: Any, raw_dir: Path | str | None = None
) -> dict[str, list[dict]]:
    """corpus_banks мінус банки, що вже є призначенням якоїсь кампанії в БД.

    Повертає лише осиротілі банки (jar_id → пост-мети).
    """
    used = {
        jar
        for c in store.load_campaigns(conn)
        if (jar := campaign_jar_id(c)) is not None
    }
    return {
        jar_id: metas
        for jar_id, metas in corpus_banks(raw_dir).items()
        if jar_id not in used
    }


# ── build_campaign_from_bank ─────────────────────────────────────────────────


def _bank_campaign_id(jar_id: str) -> str:
    """Стабільний id кампанії-збору: camp-<sha256('jar:'+jar_id)[:12]> (ідемпотентно)."""
    return "camp-" + hashlib.sha256(f"jar:{jar_id}".encode()).hexdigest()[:12]


def _bank_actor_id(channel: str) -> str:
    """actor_id з primary-каналу: auto-<sha256(channel)[:8]> (mirror ingest)."""
    return "auto-" + hashlib.sha256(channel.encode()).hexdigest()[:8]


def build_campaign_from_bank(
    jar_id: str,
    post_metas: list[dict],
    *,
    render: dict | None = None,
    now: str | None = None,
) -> Campaign:
    """Детерміновано будує кампанію-збір з банки + пост-мет (БЕЗ LLM).

    render (опційно, з render_jar_cached) дає amount_uah/goal_amount/title. Якщо
    render=None або без назви — title деривується з найбільш «збір»-подібного
    тексту, інакше fallback f"Збір (банка {jar_id})".

    provenance містить:
      - destination → source_url банки (tier-1, conf 0.9) — симетрично до того, як
        dedup.campaign_jar_id зчитує банку (КРИТИЧНО для дедупу);
      - reach (tier-3, conf 0.35) на primary-пост (якщо є пости);
      - amount_uah (tier-1, conf 0.9) на URL банки (якщо є сума).

    Стилеві поля (tone/form_factor/face/cta_type/cadence/playbook_note) лишаються
    None/[] — їх заповнить пізніший LLM-аудит-пас.
    """
    metas = post_metas or []
    primary = _primary_meta(metas)
    primary_channel = (primary.get("channel") if primary else None) or "unknown"
    primary_url = (primary.get("source_url") if primary else None) or ""

    jar_url = _JAR_URL_TMPL.format(jar_id=jar_id)

    # --- amount / goal / title з render ---
    amount_uah: float | None = None
    goal_amount: float | None = None
    title: str | None = None
    if render:
        amount_uah = render.get("amount_uah")
        goal_amount = render.get("goal_amount")
        title = render.get("title") or render.get("name")
    if not title:
        title = _derive_title(jar_id, metas)

    # --- reach: Σ views (None якщо жоден view невідомий — honest null) ---
    views = [m["views"] for m in metas if m.get("views") is not None]
    reach = sum(views) if views else None

    # --- дати ---
    dates = [d for m in metas if (d := _norm_date(m.get("date")))]
    date_start = min(dates) if dates else None
    date_end = max(dates) if dates else None
    year: int | None = None
    if date_start:
        try:
            year = int(date_start[:4])
        except ValueError:
            year = None

    # --- provenance (симетрія з campaign_jar_id через destination.source_url) ---
    provenance: dict[str, dict] = {
        _DESTINATION_PROV_KEY: {
            "source_url": jar_url,
            "tier": 1,
            "confidence": _TIER1_CONF,
            "note": "bank-first: jar from corpus",
        }
    }
    if primary_url:
        provenance["reach"] = {
            "source_url": primary_url,
            "tier": 3,
            "confidence": _REACH_CONF,
            "note": "bank-first: aggregated post reach",
        }
        # Привʼязка до сирого поста, з якого піднято збір (щоб
        # dedup_pass._find_raw_for_campaign / posts знаходили raw → призначення).
        provenance["campaign"] = {
            "source_url": primary_url,
            "tier": 3,
            "confidence": _REACH_CONF,
            "note": "bank-first: origin post",
        }
    if amount_uah is not None:
        provenance["amount_uah"] = {
            "source_url": jar_url,
            "tier": 1,
            "confidence": _TIER1_CONF,
            "note": "monobank jar tier-1",
        }

    has_amount = amount_uah is not None
    return Campaign(
        id=_bank_campaign_id(jar_id),
        actor_id=_bank_actor_id(primary_channel),
        title=title,
        goal="other",
        type="jar",
        channels=["telegram"],
        date_start=date_start,
        date_end=date_end,
        year=year,
        form_factor=[],
        cta_type=None,
        tone=[],
        face=None,
        cadence=None,
        playbook_note=None,
        amount_uah=amount_uah,
        amount_usd=None,
        goal_amount=goal_amount,
        reach=reach,
        engagement=None,
        spend=None,
        assets_count=None,
        goal_reached=None,
        is_campaign=True,
        case_id=None,
        partner_ids=[],
        provenance=provenance,
        confidence_overall=_CONF_WITH_AMOUNT if has_amount else _CONF_NO_AMOUNT,
        verification_status="verified" if has_amount else "auto",
        verdict_reason="bank-first: jar from corpus",
        extracted_at=now,
        extracted_by_model="bank-first",
    )


# ── run_bank_first ───────────────────────────────────────────────────────────


def run_bank_first(
    conn: Any,
    *,
    raw_dir: Path | str | None = None,
    jars_cache_path: Path | str | None = None,
    cases_json: Path | str | None = None,
    _render: Callable[[str], str | None] | None = None,
    max_items: int | None = None,
    render: bool = True,
    now: str | None = None,
) -> dict:
    """Піднімає осиротілі банки у збір-кампанії (детерміновано, з дедупом).

    Кроки:
      1. orphans = orphan_banks(conn, raw_dir).
      2. Для кожної банки (cap max_items): опційно render_jar_cached → суми/назва;
         build_campaign_from_bank; дедуп (skip якщо id або призначення-банка вже
         в БД); інакше upsert_campaign.
      3. build_posts(conn, raw_dir) — привʼязка інфо-історії.
      4. export_cases(conn, cases_json).

    Ідемпотентний: повторний запуск створює 0 (стабільні id + дедуп).

    Повертає {orphans, created, skipped, with_amount, campaigns_before,
    campaigns_after}.
    """
    rd = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
    jcp = jars_cache_path if jars_cache_path is not None else config.JARS_CACHE_PATH
    cj = cases_json if cases_json is not None else config.CASES_JSON

    before = store.load_campaigns(conn)
    campaigns_before = len(before)
    existing_ids = {c.id for c in before}
    existing_jars = {
        jar for c in before if (jar := campaign_jar_id(c)) is not None
    }

    orphans = orphan_banks(conn, rd)
    orphan_items = list(orphans.items())
    if max_items is not None:
        orphan_items = orphan_items[:max_items]

    created = 0
    skipped = 0
    with_amount = 0

    for jar_id, metas in orphan_items:
        render_data: dict | None = None
        if render:
            try:
                from .collect.jar_render import render_jar_cached  # noqa: PLC0415

                render_data = render_jar_cached(
                    jar_id, cache_path=jcp, _render=_render, force=False, now=now
                )
            except Exception as exc:  # noqa: BLE001
                print(f"bank_first: render failed for {jar_id}: {exc}", file=sys.stderr)
                render_data = None

        campaign = build_campaign_from_bank(jar_id, metas, render=render_data, now=now)

        # Дедуп: id або призначення-банка вже існують → skip.
        if campaign.id in existing_ids or jar_id in existing_jars:
            skipped += 1
            print(f"bank_first: skip {jar_id} (вже є кампанія)")
            continue

        # Гарантуємо наявність актора (FK campaigns.actor_id → actors.id).
        store.upsert_actor(
            conn,
            Actor(id=campaign.actor_id, name=f"auto:{campaign.actor_id}", type="unknown"),
        )
        store.upsert_campaign(conn, campaign)
        existing_ids.add(campaign.id)
        existing_jars.add(jar_id)
        created += 1
        if campaign.amount_uah is not None:
            with_amount += 1
        amt = campaign.amount_uah
        print(
            f"bank_first: + {jar_id} → {campaign.id} "
            f"amount={amt if amt is not None else '—'} posts={len(metas)}"
        )

    # Привʼязка інфо-історії (пости↔збори) + експорт.
    from . import export as _export  # noqa: PLC0415
    from .posts import build_posts  # noqa: PLC0415

    try:
        build_posts(conn, rd)
    except Exception as exc:  # noqa: BLE001
        print(f"bank_first: build_posts failed: {exc}", file=sys.stderr)

    try:
        _export.export_cases(conn, cj, jars_cache_path=jcp, raw_dir=str(rd))
    except Exception as exc:  # noqa: BLE001
        print(f"bank_first: export failed: {exc}", file=sys.stderr)

    campaigns_after = len(store.load_campaigns(conn))
    return {
        "orphans": len(orphan_items),
        "created": created,
        "skipped": skipped,
        "with_amount": with_amount,
        "campaigns_before": campaigns_before,
        "campaigns_after": campaigns_after,
    }


# ── звіт (read-only) ─────────────────────────────────────────────────────────


def _format_report(orphans: dict[str, list[dict]]) -> str:
    """Текстовий звіт: список осиротілих банок + к-ть постів + sample-текст."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"ОСИРОТІЛІ БАНКИ (orphan jars) — {len(orphans)}")
    lines.append("=" * 64)
    for jar_id, metas in sorted(orphans.items(), key=lambda kv: -len(kv[1])):
        primary = _primary_meta(metas)
        channels = sorted({m.get("channel") for m in metas if m.get("channel")})
        sample = ""
        if primary and primary.get("text"):
            sample = " ".join(str(primary["text"]).split())[:80]
        lines.append(
            f"  {jar_id:<24} posts={len(metas):>3} "
            f"channels={','.join(channels) or '—'}"
        )
        if sample:
            lines.append(f"      «{sample}»")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.bank_first.

    Default       → run_bank_first (рендер jar + інфо-історія + дедуп + експорт).
    --report-only → лише список осиротілих банок (read-only, без записів).
    --no-render   → пропустити рендер банок (швидше; суми лишаються None).
    Прапори: --max N, --raw-dir, --db.
    """
    # Windows-консоль (cp1252) падає на ₴/→ — форсуємо UTF-8.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="bank-first: підняття осиротілих банок у збір-кампанії."
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД.")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія raw-кешу."
    )
    parser.add_argument("--max", type=int, default=None, help="Обмежити к-ть банок.")
    parser.add_argument(
        "--no-render", action="store_true", help="Не рендерити банки (суми None)."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Лише список осиротілих банок (read-only, без записів).",
    )
    args = parser.parse_args(argv)

    conn = store.connect(args.db)
    store.init_db(conn)

    if args.report_only:
        orphans = orphan_banks(conn, args.raw_dir)
        print(_format_report(orphans))
        return 0

    summary = run_bank_first(
        conn,
        raw_dir=args.raw_dir,
        max_items=args.max,
        render=not args.no_render,
    )
    print(
        f"bank-first: orphans={summary['orphans']} created={summary['created']} "
        f"skipped={summary['skipped']} with_amount={summary['with_amount']} "
        f"campaigns {summary['campaigns_before']}→{summary['campaigns_after']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
