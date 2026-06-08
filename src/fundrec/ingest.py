"""Єдиний live-pipeline оркестратор + CLI.

run_ingest(theme, *, sources, max_items, db_path, out_path, raw_dir, _components, dry_run) -> dict:
  discover (web search) → collect (per-source, gated by keys) → extract (Campaigns + Cases) →
  verify (critic+crosscheck) → analyze → export.

Mandatory corrections (spec override):
1. Витягує CAMPAIGNS (extract_campaign) як основний об'єкт, а не лише Cases.
   Також витягує Case там де є числові дані.
2. Зберігає сирі payload у data/raw/ (configurable через raw_dir).

Кожна зовнішня взаємодія інжектується через _components:
  {
    "search":   fn(query) -> list[str],
    "collect":  {"reports": fn, "news": fn, "monobank": fn,
                 "youtube": fn(theme) -> list[dict],
                 "meta":    fn(theme) -> list[dict], ...},
    "complete": fn(prompt) -> dict,
    "judge":    fn(prompt) -> dict,
    "sleep":    fn(seconds) -> None,   # no-op в тестах
  }

Резюмованість: URL вже в БД → пропускається.
Graceful-skip: джерело без ключа → лог + skipped_no_key.

Збір відбувається у два етапи:
  1. URL-based (reports/news): discovered_urls → collectors.
  2. Search-based (youtube, meta, telegram): theme search → list[dict] raw_items.
Обидва етапи об'єднуються в єдиний список перед екстракцією.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import config, export, extract, jars, relevance, store, validate
from .analyze import text_signals_goal_reached
from .critic import critique_campaign
from .discover import discover_sources
from .extract import _TIER_CONFIDENCE
from .pipeline_analyze import analyze_all
from .pipeline_verify import verify_cases
from .schema import Actor, Source

# Яким ключам відповідають джерела
# telegram: порожній список — web-шлях (t.me/s/<channel>) не потребує ключів.
# Telethon-шлях (collect/telegram.py) потребує TELEGRAM_API_ID/HASH,
# але за замовчуванням використовується web-шлях.
_SOURCE_KEY_MAP: dict[str, list[str]] = {
    "meta": ["META_ADS_TOKEN"],
    "youtube": ["YOUTUBE_API_KEY"],
    "telegram": [],  # web-шлях: без ключів (t.me/s/<channel>)
    # Без ключів:
    "monobank": [],
    "reports": [],
    "news": [],
}

_ALL_SOURCES = list(_SOURCE_KEY_MAP.keys())

# Пошукові джерела (не URL-based): theme → list[dict]
_SEARCH_SOURCES = {"youtube", "meta", "telegram"}

# Source type + tier для кожного пошукового джерела
_SEARCH_SOURCE_META: dict[str, dict[str, Any]] = {
    "youtube": {"type": "social", "tier": 3},
    "meta": {"type": "social", "tier": 1},
    "telegram": {"type": "social", "tier": 3},
}


def _source_active(source: str, keys: dict[str, bool]) -> bool:
    """Повертає True якщо всі потрібні ключі задані."""
    required = _SOURCE_KEY_MAP.get(source, [])
    return all(keys.get(k, False) for k in required)


def _make_id(url: str, prefix: str = "auto") -> str:
    """Детермінований ID з URL (перші 12 символів SHA256)."""
    return f"{prefix}-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _url_already_in_db(conn: Any, url: str) -> bool:
    """Перевіряє чи URL вже присутній як кампанія у БД."""
    row = conn.execute("SELECT id FROM campaigns WHERE id = ?", (_make_id(url, "camp"),)).fetchone()
    return row is not None


def _jar_already_in_db(conn: Any, jar_id: str) -> bool:
    """Перевіряє чи jar-id вже присутній у provenance будь-якої кампанії в БД.

    Шукає source_url банки (send.monobank.ua/jar/<jar_id>) у JSON-полі provenance.
    """
    jar_url = f"https://send.monobank.ua/jar/{jar_id}"
    # Шукаємо в JSON-тексті provenance колонки campaigns
    row = conn.execute(
        "SELECT id FROM campaigns WHERE provenance LIKE ?",
        (f"%{jar_url}%",),
    ).fetchone()
    return row is not None


def _write_raw_cache(raw_dir: Path, url: str, payload: dict[str, Any]) -> None:
    """Записує сирий payload як JSON у raw_dir/{url_hash}.json."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    out_file = raw_dir / f"{file_id}.json"
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_sleep(seconds: float) -> None:  # pragma: no cover
    import time

    time.sleep(seconds)


def _get_default_search_collector(src_name: str) -> Any | None:
    """Повертає lazy real collector для пошукового джерела (або None)."""
    if src_name == "youtube":
        try:
            from .collect.youtube import search_fundraising  # noqa: PLC0415

            return search_fundraising
        except ImportError:  # pragma: no cover
            return None
    if src_name == "meta":
        try:
            from .collect.meta_ads import search_ads  # noqa: PLC0415

            return search_ads
        except ImportError:  # pragma: no cover
            return None
    if src_name == "telegram":
        try:
            from .collect.telegram_web import search_channels  # noqa: PLC0415

            # Обгортаємо: search_channels(theme, max_results=...) — сигнатура theme->list[dict]
            return search_channels
        except ImportError:  # pragma: no cover
            return None
    return None


def _default_jar_fetch_fn() -> Any:
    """Повертає live jar fetcher: render_jar_cached якщо playwright доступний,
    інакше — fetch_jar_data (HTTP fallback)."""
    try:
        from .collect.jar_render import render_jar_cached  # noqa: PLC0415

        return render_jar_cached
    except ImportError:  # pragma: no cover
        return jars.fetch_jar_data


def _collect_search_items(
    src_name: str,
    theme: str,
    max_results: int,
    collect_fns: dict[str, Any],
    active_sources: list[str],
) -> list[tuple[dict[str, Any], str, str, int]]:
    """Збирає raw_items з пошукового джерела.

    Повертає список (raw_item, source_url, platform, tier).
    Повертає [] якщо джерело не активне або повертає порожній список.
    """
    if src_name not in active_sources:
        return []

    src_meta = _SEARCH_SOURCE_META.get(src_name, {"type": "social", "tier": 2})
    tier = src_meta["tier"]

    # Інжектований колектор має пріоритет
    collector_fn = collect_fns.get(src_name)
    if collector_fn is None:
        collector_fn = _get_default_search_collector(src_name)  # pragma: no cover

    if collector_fn is None:
        return []

    try:
        items: list[dict[str, Any]] = collector_fn(theme)
    except Exception as exc:  # noqa: BLE001
        print(
            f"ingest: search collector '{src_name}' failed: {exc}",
            file=sys.stderr,
        )
        return []

    result: list[tuple[dict[str, Any], str, str, int]] = []
    for item in items:
        url = item.get("source_url") or ""
        if not url:
            continue
        platform = item.get("platform", src_name)
        result.append((item, url, platform, tier))

    return result


_TIER1_CONFIDENCE = 0.95  # extract._TIER_CONFIDENCE[1]


def _apply_jar_to_campaign(campaign: Any, jar_data: dict[str, Any]) -> None:
    """Перезаписує campaign.amount_uah значенням банки і ставить tier-1 provenance.
    Також встановлює goal_amount якщо присутнє у jar_data."""
    amount = jar_data.get("amount_uah")
    if amount is None:
        return
    campaign.amount_uah = amount
    campaign.provenance["amount_uah"] = {
        "source_url": jar_data["url"],
        "confidence": _TIER1_CONFIDENCE,
        "tier": 1,
        "note": "monobank jar tier-1",
    }
    goal = jar_data.get("goal_amount")
    if goal is not None:
        campaign.goal_amount = goal


def _apply_jar_to_case(case: Any, jar_data: dict[str, Any]) -> None:
    """Перезаписує case.amount_uah значенням банки і ставить tier-1 provenance."""
    amount = jar_data.get("amount_uah")
    if amount is None:
        return
    case.amount_uah = amount
    case.provenance["amount_uah"] = {
        "source_url": jar_data["url"],
        "confidence": _TIER1_CONFIDENCE,
        "tier": 1,
        "note": "monobank jar tier-1",
    }


def _apply_signals(campaign: Any, raw_item: dict[str, Any], tier: int) -> None:
    """Встановлює reach/engagement кампанії детерміновано з сирих платформних даних.

    Telegram: reach = views; engagement = forwards (БЕЗ fallback на views →
        лишається None якщо forwards відсутній — публічний t.me/s/ не дає
        forwards/реакцій, тож engagement здебільшого None, і це чесно).
    YouTube:  reach = views; engagement = likes (БЕЗ fallback на views).
    Встановлює лише якщо значення ненульове; перезаписує LLM-здогад реальним числом.
    Кожне встановлене поле отримує provenance з tier та confidence.
    """
    platform = (raw_item.get("platform") or "").lower()
    source_url = raw_item.get("source_url") or ""
    confidence = _TIER_CONFIDENCE.get(tier, 0.35)

    views = raw_item.get("views")
    forwards = raw_item.get("forwards")
    likes = raw_item.get("likes")

    reach_val: int | float | None = None
    engagement_val: int | float | None = None

    if platform in ("telegram",):
        if views is not None:
            reach_val = views
            engagement_val = forwards  # None якщо forwards відсутній — чесно
    elif platform in ("youtube",):
        if views is not None:
            reach_val = views
            engagement_val = likes  # None якщо likes відсутній — чесно

    if reach_val is not None:
        campaign.reach = reach_val
        campaign.provenance["reach"] = {
            "source_url": source_url,
            "confidence": confidence,
            "tier": tier,
            "note": "platform signal",
        }
    if engagement_val is not None:
        campaign.engagement = engagement_val
        campaign.provenance["engagement"] = {
            "source_url": source_url,
            "confidence": confidence,
            "tier": tier,
            "note": "platform signal",
        }


def _ingest_one(
    conn: Any,
    raw_item: dict[str, Any],
    source: Source,
    *,
    raw_dir: Path,
    actor_id: str,
    complete_fn: Any,
    sleep_fn: Any,
    source_key: str,
    collected_per_source: dict[str, int],
    jar_fetch_fn: Any | None = None,
    seen_jar_ids: set[str] | None = None,
) -> tuple[bool, bool]:
    """Екстрагує та зберігає одну кампанію + case.

    jar_fetch_fn: fn(jar_id, *, _client=None) -> dict | None  — injectable.
    seen_jar_ids: set для внутрішнього jar-dedup протягом поточного запуску.

    Повертає (campaign_stored, case_stored).
    """
    url = source.url

    # --- Jar: витяг id зі збіркового тексту ---
    text_for_jar = raw_item.get("text") or raw_item.get("raw_text") or ""
    found_jar_ids = jars.extract_jar_ids(text_for_jar)

    # Jar-dedup: якщо jar_id вже оброблений у цьому запуску або є в БД — пропускаємо
    if found_jar_ids and seen_jar_ids is not None:
        first_jar = found_jar_ids[0]
        if first_jar in seen_jar_ids or _jar_already_in_db(conn, first_jar):
            return False, False
        seen_jar_ids.add(first_jar)

    _write_raw_cache(raw_dir, url, raw_item)
    store.upsert_source(conn, source)

    campaign_id = _make_id(url, "camp")
    try:
        campaign, creatives, partners = extract.extract_campaign(
            raw_item,
            source,
            campaign_id=campaign_id,
            actor_id=actor_id,
            model=config.EXTRACT_MODEL,
            _complete=complete_fn,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ingest: extract_campaign failed for {url}: {exc}", file=sys.stderr)
        return False, False

    # --- Детерміновані сигнали (reach/engagement) з сирих платформних даних ---
    _apply_signals(campaign, raw_item, tier=source.tier)

    # --- goal_reached: keyword fallback якщо LLM не встановив ---
    if campaign.goal_reached is None:
        text_for_kw = raw_item.get("text") or raw_item.get("raw_text") or ""
        kw_result = text_signals_goal_reached(text_for_kw)
        if kw_result is not None:
            campaign.goal_reached = kw_result

    # --- Збагачення jar-даними (tier-1) ---
    jar_data: dict[str, Any] | None = None
    if found_jar_ids and jar_fetch_fn is not None:
        try:
            jar_data = jar_fetch_fn(found_jar_ids[0])
        except Exception as exc:  # noqa: BLE001
            print(f"ingest: jar fetch failed for {found_jar_ids[0]}: {exc}", file=sys.stderr)

    jar_applied = False
    if jar_data is not None:
        _apply_jar_to_campaign(campaign, jar_data)
        if jar_data.get("amount_uah") is not None:
            jar_applied = True

    for partner in partners:
        store.upsert_partner(conn, partner)
    store.upsert_campaign(conn, campaign)
    for creative in creatives:
        store.upsert_creative(conn, creative)
    for partner in partners:
        store.link_campaign_partner(conn, campaign_id, partner.id)

    # Tier-1 jar amount = публічне перевірене джерело → статус "verified"
    if jar_applied:
        store.set_campaign_verification(conn, campaign_id, "verified", reason="monobank jar tier-1")

    collected_per_source[source_key] = collected_per_source.get(source_key, 0) + 1
    campaign_stored = True

    # --- Also extract Case where numeric data present ---
    case_id = _make_id(url, "case")
    case_stored = False
    try:
        case = extract.extract_case(
            raw_item,
            source,
            case_id=case_id,
            actor_id=actor_id,
            model=config.EXTRACT_MODEL,
            _complete=complete_fn,
        )
        if jar_data is not None:
            _apply_jar_to_case(case, jar_data)

        problems = validate.validate_case(case)
        if problems:
            print(f"ingest: validate [{case_id}]: {problems}", file=sys.stderr)
        store.upsert_case(conn, case)
        case_stored = True
    except Exception as exc:  # noqa: BLE001
        print(f"ingest: extract_case failed for {url}: {exc}", file=sys.stderr)

    sleep_fn(0.5)
    return campaign_stored, case_stored


def run_ingest(
    theme: str,
    *,
    sources: list[str] | None = None,
    max_items: int = 25,
    db_path: Path | str = config.DB_PATH,
    out_path: Path | str = config.CASES_JSON,
    raw_dir: Path | str = config.RAW_DIR,
    _components: dict[str, Any] | None = None,
    dry_run: bool = False,
    verify: bool = True,
) -> dict[str, Any]:
    """Запускає повний live-pipeline.

    Args:
        theme:       Тема/запит для пошуку.
        sources:     Список джерел. За замовчуванням — всі.
        max_items:   Максимальна кількість кампаній для збереження.
        db_path:     Шлях до SQLite БД.
        out_path:    Шлях до cases.json.
        raw_dir:     Шлях до директорії сирих кешів (data/raw/).
        _components: Ін'єктовані компоненти (для тестів).
        dry_run:     Якщо True — лише discover + звіт, без LLM/записів.

    Returns:
        Словник-summary: discovered, collected_per_source, campaigns, cases,
        skipped_no_key, exported.
    """
    comps = _components or {}
    search_fn = comps.get("search")
    collect_fns: dict[str, Any] = comps.get("collect", {})
    complete_fn = comps.get("complete")
    judge_fn = comps.get("judge")
    sleep_fn = comps.get("sleep", _default_sleep)
    # Jar fetcher: injectable через _components["collect"]["jar"]; live — render_jar_cached
    jar_fetch_fn: Any = collect_fns.get("jar") or _default_jar_fetch_fn()

    requested_sources = sources or _ALL_SOURCES
    keys = config.keys_status()

    # --- Активні та пропущені джерела ---
    active_sources: list[str] = []
    skipped_no_key: list[str] = []
    for src in requested_sources:
        if _source_active(src, keys):
            active_sources.append(src)
        else:
            required = _SOURCE_KEY_MAP.get(src, [])
            if required:  # тільки ті, що реально потребують ключів
                # Перевіряємо, чи є ін'єктований колектор для пошукових джерел
                if src in _SEARCH_SOURCES and src in collect_fns:
                    # Є ін'єктований fake/test колектор — джерело активне навіть без ключа
                    active_sources.append(src)
                else:
                    skipped_no_key.append(src)
                    print(
                        f"ingest: джерело '{src}' пропущено — нема ключів: {required}",
                        file=sys.stderr,
                    )
            else:
                active_sources.append(src)

    # --- Discover ---
    discovered_urls: list[str] = []
    if search_fn is not None:
        discovered_urls = discover_sources(theme, existing_urls=set(), _search=search_fn)
    elif not dry_run and any(s in active_sources for s in ("reports", "news")):
        # Web-discovery (DDG) потрібен лише для URL-джерел (reports/news).
        # DDG нестабільний → збій НЕ фатальний (pragma: no cover — мережа).
        try:  # pragma: no cover
            discovered_urls = discover_sources(theme, existing_urls=set())
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            print(f"ingest: web-discovery (DDG) не вдалась, пропускаю: {exc}", file=sys.stderr)
            discovered_urls = []

    if dry_run:
        return {
            "discovered": len(discovered_urls),
            "active_sources": active_sources,
            "skipped_no_key": skipped_no_key,
            "dry_run": True,
        }

    # --- Init DB ---
    db_path = Path(db_path)
    raw_dir = Path(raw_dir)
    conn = store.connect(db_path)
    store.init_db(conn)

    # --- Загальний актор для цієї теми ---
    actor_id = "auto-" + hashlib.sha256(theme.encode()).hexdigest()[:8]
    actor = Actor(id=actor_id, name=f"auto:{theme[:50]}", type="unknown")
    store.upsert_actor(conn, actor)

    stored_campaigns = 0
    stored_cases = 0
    skipped_irrelevant = 0
    collected_per_source: dict[str, int] = {}
    # Jar-dedup: jar_id → вже оброблено у цьому запуску (міжсесійний dedup — _jar_already_in_db)
    seen_jar_ids: set[str] = set()

    # -----------------------------------------------------------------------
    # Етап 1: URL-based (reports, news) — зі списку discovered_urls
    # -----------------------------------------------------------------------
    for url in discovered_urls:
        if stored_campaigns >= max_items:
            break
        if _url_already_in_db(conn, url):
            continue

        # Collect raw item
        raw_item: dict[str, Any] | None = None
        matched_src: str = "reports"
        for src_name in active_sources:
            if src_name in ("reports", "news"):
                collector_fn = collect_fns.get(src_name)
                if collector_fn is None:
                    # live fallback (pragma: no cover)
                    if src_name == "reports":
                        from .collect.reports import fetch_report  # pragma: no cover

                        collector_fn = fetch_report  # pragma: no cover
                    elif src_name == "news":
                        from .collect.news import fetch_news  # pragma: no cover

                        collector_fn = fetch_news  # pragma: no cover
                if collector_fn is not None:
                    try:
                        raw_item = collector_fn(url)
                        matched_src = src_name
                        break
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"ingest: collector '{src_name}' failed for {url}: {exc}",
                            file=sys.stderr,
                        )

        if raw_item is None:
            raw_item = {"url": url, "title": None, "raw_text": ""}

        # --- Гейт релевантності: пропускаємо не-збори ---
        if not relevance.is_fundraising(raw_item):
            print(f"ingest: пропущено (не збір): {url}", file=sys.stderr)
            skipped_irrelevant += 1
            continue

        source = Source(
            url=url,
            type="web",
            tier=2,
            access="public",
            license="unknown",
            actor_id=actor_id,
        )

        campaign_stored, case_stored = _ingest_one(
            conn,
            raw_item,
            source,
            raw_dir=raw_dir,
            actor_id=actor_id,
            complete_fn=complete_fn,
            sleep_fn=sleep_fn,
            source_key=matched_src,
            collected_per_source=collected_per_source,
            jar_fetch_fn=jar_fetch_fn,
            seen_jar_ids=seen_jar_ids,
        )
        if campaign_stored:
            stored_campaigns += 1
        if case_stored:
            stored_cases += 1

    # -----------------------------------------------------------------------
    # Етап 2: Search-based (youtube, meta, telegram)
    # -----------------------------------------------------------------------
    for src_name in _SEARCH_SOURCES:
        if stored_campaigns >= max_items:
            break

        remaining = max_items - stored_campaigns
        search_items = _collect_search_items(
            src_name,
            theme,
            max_results=remaining,
            collect_fns=collect_fns,
            active_sources=active_sources,
        )

        src_meta = _SEARCH_SOURCE_META.get(src_name, {"type": "social", "tier": 2})

        for raw_item, item_url, _platform, tier in search_items:
            if stored_campaigns >= max_items:
                break
            if _url_already_in_db(conn, item_url):
                continue

            # --- Гейт релевантності: пропускаємо не-збори ---
            if not relevance.is_fundraising(raw_item):
                print(f"ingest: пропущено (не збір): {item_url}", file=sys.stderr)
                skipped_irrelevant += 1
                continue

            source = Source(
                url=item_url,
                type=src_meta["type"],
                tier=tier,
                access="public",
                license="unknown",
                actor_id=actor_id,
            )

            campaign_stored, case_stored = _ingest_one(
                conn,
                raw_item,
                source,
                raw_dir=raw_dir,
                actor_id=actor_id,
                complete_fn=complete_fn,
                sleep_fn=sleep_fn,
                source_key=src_name,
                collected_per_source=collected_per_source,
                jar_fetch_fn=jar_fetch_fn,
                seen_jar_ids=seen_jar_ids,
            )
            if campaign_stored:
                stored_campaigns += 1
            if case_stored:
                stored_cases += 1

    # --- Verify (критик/крос-чек) — опційно; для tier-3 джерел нічого не змінює,
    #     тому при масовому зборі (--no-verify) пропускаємо заради швидкості/вартості ---
    if verify:
        _verify_campaigns(conn, judge_fn=judge_fn)
        verify_cases(conn, _judge=judge_fn)

    # --- Analyze ---
    analyze_all(conn)

    # --- Export ---
    exported = export.export_cases(conn, out_path)

    return {
        "discovered": len(discovered_urls),
        "collected_per_source": collected_per_source,
        "campaigns": stored_campaigns,
        "cases": stored_cases,
        "skipped_no_key": skipped_no_key,
        "skipped_irrelevant": skipped_irrelevant,
        "exported": exported,
    }


def _verify_campaigns(conn: Any, *, judge_fn: Any = None) -> None:
    """Виконує критика для всіх кампаній (аналог verify_cases для campaigns)."""
    campaigns = store.load_campaigns(conn)
    if not campaigns:
        return
    for campaign in campaigns:
        base_status = "auto"
        # Якщо є provenance з tier=1 — cross-checked
        for entry in campaign.provenance.values():
            if isinstance(entry, dict) and entry.get("tier") == 1:
                base_status = "cross-checked"
                break
        final_status, reason = critique_campaign(campaign, base_status=base_status, _judge=judge_fn)
        store.set_campaign_verification(conn, campaign.id, final_status, reason=reason or None)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint для live-ingest."""
    import argparse  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec live ingest: discover → collect → extract → verify → analyze → export"
    )
    parser.add_argument("--theme", required=True, help="Тема/запит для пошуку")
    parser.add_argument(
        "--sources",
        default=",".join(_ALL_SOURCES),
        help=f"Джерела через кому (за замовчуванням: {','.join(_ALL_SOURCES)})",
    )
    parser.add_argument("--max", type=int, default=25, dest="max_items", help="Максимум кампаній")
    parser.add_argument(
        "--dry-run", action="store_true", help="Лише discover + звіт (без LLM/записів)"
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument("--out", default=str(config.CASES_JSON), help="Шлях до cases.json")
    parser.add_argument("--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Пропустити критик/крос-чек (швидше/дешевше; для tier-3 не змінює статус)",
    )
    args = parser.parse_args(argv)

    requested = [s.strip() for s in args.sources.split(",") if s.strip()]

    summary = run_ingest(
        args.theme,
        sources=requested,
        max_items=args.max_items,
        db_path=args.db,
        out_path=args.out,
        raw_dir=args.raw_dir,
        dry_run=args.dry_run,
        verify=not args.no_verify,
    )

    if args.dry_run:
        print(
            f"[dry-run] тема='{args.theme}' discovered={summary['discovered']} "
            f"active={summary['active_sources']} skipped={summary['skipped_no_key']}",
            file=sys.stderr,
        )
    else:
        print(
            f"discovered={summary['discovered']} "
            f"campaigns={summary['campaigns']} cases={summary['cases']} "
            f"exported={summary['exported']} "
            f"skipped_no_key={summary['skipped_no_key']}",
            file=sys.stdout,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
