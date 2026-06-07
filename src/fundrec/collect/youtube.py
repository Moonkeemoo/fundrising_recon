"""Колектор YouTube Data API v3: пошук відео + статистика.

parse_video(item) -> dict — чиста функція, повністю тестується на фікстурі.
search_fundraising(query, *, api_key, _client, max_results) -> list[dict]
  — мережа ізольована через _client; graceful-skip без ключа.
"""
from __future__ import annotations

import sys
from typing import Any

_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
_VIDEO_URL_TMPL = "https://www.youtube.com/watch?v={video_id}"


def parse_video(item: dict[str, Any]) -> dict[str, Any]:
    """Нормалізує елемент videos.list -> dict з провенансом.

    Honest null: views/likes = None якщо відсутні у statistics.
    """
    video_id: str = item.get("id", "") if isinstance(item.get("id"), str) else ""
    snippet: dict = item.get("snippet", {})
    statistics: dict = item.get("statistics", {})

    def _int_or_none(key: str) -> int | None:
        val = statistics.get(key)
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    return {
        "source_url": _VIDEO_URL_TMPL.format(video_id=video_id),
        "platform": "youtube",
        "video_id": video_id,
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "published": snippet.get("publishedAt"),
        "channel": snippet.get("channelTitle"),
        "views": _int_or_none("viewCount"),
        "likes": _int_or_none("likeCount"),
    }


def search_fundraising(
    query: str,
    *,
    api_key: str | None = None,
    _client: Any | None = None,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """Шукає відео за запитом; повертає list[dict] нормалізованих відео.

    Якщо api_key не задано (або порожній рядок) — graceful-skip: [] + лог.
    _client інжектиться в тестах (має метод .get(url, params=..., timeout=...)).
    """
    from fundrec import config  # pylint: disable=import-outside-toplevel

    if api_key is None:
        api_key = config.YOUTUBE_API_KEY

    if not api_key:
        print("youtube: нема ключа, пропускаю", file=sys.stderr)
        return []

    if _client is None:
        import httpx  # pragma: no cover
        _client = httpx.Client(timeout=20)  # pragma: no cover

    # 1. search.list -> список video_id
    search_url = f"{_YOUTUBE_API_BASE}/search"
    search_params = {
        "part": "id",
        "q": query,
        "type": "video",
        "maxResults": str(max_results),
        "key": api_key,
    }
    resp = _client.get(search_url, params=search_params, timeout=20)
    resp.raise_for_status()
    search_data: dict = resp.json()

    video_ids = [
        item["id"]["videoId"]
        for item in search_data.get("items", [])
        if item.get("id", {}).get("kind") == "youtube#video"
    ]
    if not video_ids:
        return []

    # 2. videos.list -> деталі + статистика
    videos_url = f"{_YOUTUBE_API_BASE}/videos"
    videos_params = {
        "part": "snippet,statistics",
        "id": ",".join(video_ids),
        "key": api_key,
    }
    resp2 = _client.get(videos_url, params=videos_params, timeout=20)
    resp2.raise_for_status()
    videos_data: dict = resp2.json()

    return [parse_video(item) for item in videos_data.get("items", [])]
