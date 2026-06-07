"""Звʼязок ПОСТИ↔ЗБІР: пости = інформаційна історія збору (охоплення).

Збір (campaign) — це призначення донату. Пости, що згадують/промотують цей
збір, формують його інформаційну історію та сукупне охоплення (reach).

build_posts(conn, raw_dir, *, title_sim=0.5, day_window=21) -> dict
  Перебудовує таблицю posts з усіх raw-файлів і привʼязує кожен пост до
  щонайбільше ОДНОГО збору:
    1. перетин призначень (extract_destinations) з призначеннями збору → лінк;
    2. інакше, якщо пост БЕЗ призначення — нечіткий лінк до збору того самого
       каналу/актора з title_similarity ≥ title_sim і |різниця дат| ≤ day_window;
    3. інакше campaign_id=None (вільна згадка).
  Повертає {posts, linked, free}.

CLI:
  python -m fundrec.posts [--db PATH] [--raw-dir PATH]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import config, store
from .dedup import normalize_title, title_similarity
from .dedup_pass import _find_raw_for_campaign
from .destinations import extract_destinations
from .schema import Post


def _post_id(source_url: str) -> str:
    """Стабільний id поста: sha1(source_url)[:16]."""
    return hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]


def _parse_date(raw_date: str | None) -> str | None:
    """Нормалізує ISO-дату/datetime до YYYY-MM-DD. Повертає None якщо нема."""
    if not raw_date:
        return None
    s = str(raw_date).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":  # noqa: PLR2004
        return s[:10]
    if len(s) >= 7 and s[4] == "-":  # noqa: PLR2004
        return s[:7]
    return None


def _raw_date(raw: dict[str, Any]) -> str | None:
    """Дата raw-поста: telegram 'date' або youtube 'published' → YYYY-MM-DD."""
    return _parse_date(raw.get("date") or raw.get("published"))


def _raw_views(raw: dict[str, Any]) -> int | None:
    """Перегляди поста (int) або None — honest null, не вигадуємо."""
    v = raw.get("views")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _raw_engagement(raw: dict[str, Any]) -> int | None:
    """Залучення поста: forwards (telegram) або likes (youtube); None якщо нема."""
    val = raw.get("forwards")
    if val is None:
        val = raw.get("likes")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _raw_title(raw: dict[str, Any]) -> str:
    """Текст для нечіткого порівняння: title (youtube) або text (telegram)."""
    return raw.get("title") or raw.get("text") or ""


def _raw_snippet(raw: dict[str, Any], limit: int = 200) -> str | None:
    """Короткий фрагмент тексту поста (для таймлайну)."""
    txt = raw.get("text") or raw.get("description") or raw.get("title") or ""
    txt = txt.strip()
    if not txt:
        return None
    return txt[:limit]


def _day_diff(d1: str | None, d2: str | None) -> int | None:
    """Абсолютна різниця у днях між двома YYYY-MM-DD; None якщо бракує дати."""
    if not d1 or not d2:
        return None
    from datetime import date  # noqa: PLC0415

    try:
        a = date.fromisoformat(d1[:10])
        b = date.fromisoformat(d2[:10])
    except ValueError:
        return None
    return abs((a - b).days)


def _post_from_raw(raw: dict[str, Any]) -> Post | None:
    """Будує Post із raw (без campaign_id). None якщо немає source_url."""
    source_url = raw.get("source_url") or raw.get("url")
    if not source_url:
        return None
    return Post(
        id=_post_id(source_url),
        campaign_id=None,
        source_url=source_url,
        channel=raw.get("channel"),
        platform=raw.get("platform"),
        date=_raw_date(raw),
        views=_raw_views(raw),
        engagement=_raw_engagement(raw),
        text_snippet=_raw_snippet(raw),
    )


def _build_campaign_index(conn: Any, raw_dir: Path) -> list[dict[str, Any]]:
    """Будує індекс зборів: для кожного — призначення/канал/нормалізована назва/дата.

    Дата збору: campaign.date_start, інакше дата raw-поста.
    """
    campaigns = store.load_campaigns(conn)
    index: list[dict[str, Any]] = []
    for c in campaigns:
        raw = _find_raw_for_campaign(c, raw_dir)
        dests = set(extract_destinations(raw, _client=None)) if raw else set()
        channel = raw.get("channel") if raw else None
        camp_date = c.date_start or (_raw_date(raw) if raw else None)
        index.append(
            {
                "id": c.id,
                "dests": dests,
                "channel": channel,
                "norm_title": normalize_title(c.title or ""),
                "title": c.title or "",
                "date": camp_date,
            }
        )
    return index


def _link_post(
    raw: dict[str, Any],
    index: list[dict[str, Any]],
    *,
    title_sim: float,
    day_window: int,
) -> str | None:
    """Визначає campaign_id для raw-поста (≤1 збір) за правилами привʼязки."""
    post_dests = set(extract_destinations(raw, _client=None))

    # 1. Перетин призначень — найнадійніший сигнал.
    if post_dests:
        for entry in index:
            if post_dests & entry["dests"]:
                return entry["id"]
        return None  # має призначення, але не збігається з жодним збором

    # 2. Нечіткий лінк (лише для постів БЕЗ призначення).
    post_channel = raw.get("channel")
    post_title = _raw_title(raw)
    post_date = _raw_date(raw)
    if not post_channel or not post_title:
        return None

    best_id: str | None = None
    best_sim = title_sim
    for entry in index:
        if entry["channel"] != post_channel:
            continue
        diff = _day_diff(post_date, entry["date"])
        if diff is None or diff > day_window:
            continue
        sim = title_similarity(post_title, entry["title"])
        if sim >= best_sim:
            best_sim = sim
            best_id = entry["id"]
    return best_id


def build_posts(
    conn: Any,
    raw_dir: Path | str,
    *,
    title_sim: float = 0.5,
    day_window: int = 21,
) -> dict[str, int]:
    """Перебудовує таблицю posts з усіх raw-файлів і привʼязує до зборів.

    Args:
        conn: відкрите SQLite-зʼєднання (init_db вже викликано).
        raw_dir: директорія з raw-кешами JSON.
        title_sim: поріг title_similarity для нечіткого лінку (≥).
        day_window: вікно дат (±днів) для нечіткого лінку.

    Returns:
        {posts, linked, free} — кількість збережених постів, привʼязаних, вільних.
    """
    raw_dir = Path(raw_dir)
    index = _build_campaign_index(conn, raw_dir)

    posts: list[Post] = []
    linked = 0
    for raw_file in sorted(raw_dir.glob("*.json")):
        try:
            raw: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"posts: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            continue
        post = _post_from_raw(raw)
        if post is None:
            continue
        cid = _link_post(raw, index, title_sim=title_sim, day_window=day_window)
        post.campaign_id = cid
        if cid is not None:
            linked += 1
        posts.append(post)

    store.clear_posts(conn)
    for p in posts:
        store.upsert_post(conn, p)

    return {"posts": len(posts), "linked": linked, "free": len(posts) - linked}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.posts [--db PATH] [--raw-dir PATH]."""
    import argparse  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec posts: будує таблицю posts і привʼязує пости до зборів"
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів"
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"posts: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    store.init_db(conn)
    summary = build_posts(conn, args.raw_dir)
    print(
        f"posts={summary['posts']} linked={summary['linked']} free={summary['free']}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
