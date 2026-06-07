"""Релінк-прохід: заповнює amount_uah для наявних кампаній через jar-посилання.

relink_jars(conn, *, channels_file, only_no_amount, _fetch, _render, _resolve_client)
  -> dict (scanned, matched_posts, jars_found, filled)

CLI:
  python -m fundrec.relink [--db PATH] [--all]
    --all : релінкує всі кампанії (за замовч. лише без tier-1 суми).

Алгоритм:
  1. Для кожного каналу з channels_file — fetch_channel_web(ch, pages=2).
  2. Будуємо map {source_url → links} з усіх отриманих постів.
  3. Для кожної кампанії (опціонально лише без tier-1 amount):
     а. Шукаємо source_url у map.
     б. Для кожного link → resolve_jar_id → render_jar_cached.
     в. Якщо jar повернув amount → _apply_jar_to_campaign + verified + upsert.
  4. Re-export cases.json.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import config, export, store
from .collect.jar_render import render_jar_cached
from .collect.telegram_web import fetch_channel_web
from .ingest import _apply_jar_to_campaign
from .jars import resolve_jar_id

_DEFAULT_CHANNELS_FILE = config.SEEDS_DIR / "telegram_channels.txt"


def _load_channels(channels_file: Path) -> list[str]:
    """Зчитує список каналів з файлу (по одному на рядок, # — коментарі)."""
    if not channels_file.exists():
        return []
    lines = channels_file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _build_post_map(
    channels: list[str],
    *,
    pages: int = 2,
    _fetch: Any | None = None,
) -> dict[str, list[str]]:
    """Завантажує пости з каналів і будує {source_url: links}.

    _fetch: ін'єктована функція(channel, pages) -> list[dict] для тестів.
    """
    post_map: dict[str, list[str]] = {}

    for ch in channels:
        try:
            if _fetch is not None:
                posts = _fetch(ch, pages)
            else:
                posts = fetch_channel_web(ch, pages=pages)  # pragma: no cover
        except Exception as exc:  # noqa: BLE001
            print(f"relink: канал '{ch}' — помилка: {exc}", file=sys.stderr)
            continue

        for post in posts:
            src_url = post.get("source_url")
            if src_url:
                post_map[src_url] = post.get("links") or []

    return post_map


def _has_tier1_amount(campaign: Any) -> bool:
    """Повертає True якщо кампанія вже має tier-1 суму (з jar)."""
    prov = getattr(campaign, "provenance", {}) or {}
    amt_prov = prov.get("amount_uah")
    if isinstance(amt_prov, dict) and amt_prov.get("tier") == 1:
        return True
    return False


def relink_jars(
    conn: Any,
    *,
    channels_file: Path = _DEFAULT_CHANNELS_FILE,
    only_no_amount: bool = True,
    pages: int = 2,
    _fetch: Any | None = None,
    _render: Any | None = None,
    _resolve_client: Any | None = None,
    out_path: Path | str = config.CASES_JSON,
    jars_cache_path: Path | str = config.JARS_CACHE_PATH,
    export_results: bool = True,
) -> dict[str, int]:
    """Релінк-прохід: заповнює суми кампаній зі свіжих jar-даних.

    Параметри:
      conn             — відкрите SQLite-з'єднання.
      channels_file    — файл зі списком каналів (по рядку).
      only_no_amount   — True: лише кампанії без tier-1 суми (за замовч.).
      pages            — кількість сторінок fetch_channel_web на канал.
      _fetch           — ін'єкція fetch_channel_web(ch, pages) для тестів.
      _render          — ін'єкція render_jar_cached._render (jar_id → body_text).
      _resolve_client  — ін'єкція httpx-клієнту для resolve_jar_id.
      out_path         — шлях до cases.json для re-export.
      jars_cache_path  — шлях до кешу банок.
      export_results   — якщо True — re-export cases.json після оновлення.

    Повертає:
      {scanned, matched_posts, jars_found, filled}
    """
    channels = _load_channels(channels_file)

    # Будуємо post_map
    post_map = _build_post_map(channels, pages=pages, _fetch=_fetch)

    campaigns = store.load_campaigns(conn)

    scanned = 0
    matched_posts = 0
    jars_found = 0
    filled = 0

    resolve_cache: dict[str, str | None] = {}

    # Будуємо зворотній map: campaign_id → source_url зі збережених джерел
    # campaign.id = "camp-<sha256[:12](source_url)>" (з ingest._make_id)
    import hashlib  # noqa: PLC0415

    def _camp_id_from_url(url: str) -> str:
        return "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]

    # Будуємо {campaign_id: source_url} для всіх source_url з post_map
    camp_to_src: dict[str, str] = {}
    for src_url in post_map:
        camp_id = _camp_id_from_url(src_url)
        camp_to_src[camp_id] = src_url

    for campaign in campaigns:
        scanned += 1

        # Пропускаємо якщо вже є tier-1 сума
        if only_no_amount and _has_tier1_amount(campaign):
            continue

        src_url = camp_to_src.get(campaign.id)
        if not src_url:
            continue

        links = post_map.get(src_url) or []
        if not links:
            continue

        matched_posts += 1

        for link in links:
            jar_id = resolve_jar_id(
                link,
                _client=_resolve_client,
                _cache=resolve_cache,
            )
            if not jar_id:
                continue

            jars_found += 1

            # Рендеримо банку
            try:
                jar_data = render_jar_cached(
                    jar_id,
                    cache_path=jars_cache_path,
                    _render=_render,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"relink: render_jar_cached failed for {jar_id}: {exc}", file=sys.stderr)
                continue

            if jar_data is None or jar_data.get("amount_uah") is None:
                continue

            # Застосовуємо tier-1 суму
            _apply_jar_to_campaign(campaign, jar_data)
            campaign.verification_status = "verified"

            store.upsert_campaign(conn, campaign)
            store.set_campaign_verification(
                conn,
                campaign.id,
                "verified",
                reason="relink: monobank jar tier-1",
            )
            filled += 1
            break  # Достатньо однієї банки на кампанію

    if export_results:
        try:
            export.export_cases(conn, out_path, jars_cache_path=jars_cache_path)
        except Exception as exc:  # noqa: BLE001
            print(f"relink: export failed: {exc}", file=sys.stderr)

    return {
        "scanned": scanned,
        "matched_posts": matched_posts,
        "jars_found": jars_found,
        "filled": filled,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: python -m fundrec.relink [--db PATH] [--all]."""
    import argparse  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec relink: заповнює суми кампаній через jar-посилання з Telegram"
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_campaigns",
        help="Релінкувати всі кампанії (за замовч. лише без tier-1 суми)",
    )
    parser.add_argument(
        "--channels",
        default=str(_DEFAULT_CHANNELS_FILE),
        help="Файл зі списком каналів",
    )
    parser.add_argument("--out", default=str(config.CASES_JSON), help="Шлях до cases.json")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"relink: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    store.init_db(conn)

    summary = relink_jars(
        conn,
        channels_file=Path(args.channels),
        only_no_amount=not args.all_campaigns,
        out_path=args.out,
    )

    print(
        f"scanned={summary['scanned']} "
        f"matched_posts={summary['matched_posts']} "
        f"jars_found={summary['jars_found']} "
        f"filled={summary['filled']}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
