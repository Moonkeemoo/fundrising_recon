"""Тести колектора YouTube Data API v3."""
from __future__ import annotations

import json
from pathlib import Path

from fundrec.collect import youtube

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH_FIXTURE = json.loads((FIXTURES / "youtube_search.json").read_text(encoding="utf-8"))
VIDEOS_FIXTURE = json.loads((FIXTURES / "youtube_videos.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# parse_video
# ---------------------------------------------------------------------------

def test_parse_video_full_fields():
    item = VIDEOS_FIXTURE["items"][0]
    result = youtube.parse_video(item)
    assert result["platform"] == "youtube"
    assert result["video_id"] == "abc123XYZ"
    assert result["source_url"] == "https://www.youtube.com/watch?v=abc123XYZ"
    assert result["title"] == "Телетон UNITED24: збір на дрони для ЗСУ"
    assert "FPV" in result["description"]
    assert result["published"] == "2023-08-15T10:00:00Z"
    assert result["channel"] == "UNITED24 Media"
    assert result["views"] == 1_500_000
    assert result["likes"] == 45_000


def test_parse_video_second_item():
    item = VIDEOS_FIXTURE["items"][1]
    result = youtube.parse_video(item)
    assert result["video_id"] == "def456QRS"
    assert result["views"] == 320_000
    assert result["likes"] == 12_000


def test_parse_video_missing_statistics():
    item = {
        "kind": "youtube#video",
        "id": "noStats",
        "snippet": {
            "publishedAt": "2023-01-01T00:00:00Z",
            "channelTitle": "Test Channel",
            "title": "Test",
            "description": "Desc",
        },
    }
    result = youtube.parse_video(item)
    assert result["views"] is None
    assert result["likes"] is None


def test_parse_video_views_is_int_not_string():
    item = VIDEOS_FIXTURE["items"][0]
    result = youtube.parse_video(item)
    assert isinstance(result["views"], int)
    assert isinstance(result["likes"], int)


def test_parse_video_honest_none_for_absent_likes():
    """Якщо likes відсутній у statistics — None, не 0."""
    item = {
        "kind": "youtube#video",
        "id": "noLikes",
        "snippet": {
            "publishedAt": "2023-01-01T00:00:00Z",
            "channelTitle": "Ch",
            "title": "T",
            "description": "D",
        },
        "statistics": {"viewCount": "100"},
    }
    result = youtube.parse_video(item)
    assert result["views"] == 100
    assert result["likes"] is None


# ---------------------------------------------------------------------------
# search_fundraising — graceful-skip без ключа
# ---------------------------------------------------------------------------

def test_search_fundraising_no_key_returns_empty(capsys):
    result = youtube.search_fundraising("телетон", api_key="")
    assert result == []
    captured = capsys.readouterr()
    assert "youtube" in (captured.out + captured.err).lower()


def test_search_fundraising_none_key_returns_empty():
    result = youtube.search_fundraising("test", api_key=None)
    assert result == []


# ---------------------------------------------------------------------------
# search_fundraising — injected client happy path
# ---------------------------------------------------------------------------

class _FakeYouTubeClient:
    """Симулює два запити: search.list та videos.list."""

    def __init__(self, search_resp: dict, videos_resp: dict):
        self._search = search_resp
        self._videos = videos_resp
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict | None = None, timeout: int = 20):
        params = params or {}
        self.calls.append((url, params))
        return _FakeResp(self._search if "search" in url else self._videos)


class _FakeResp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_search_fundraising_injected_client_returns_videos():
    client = _FakeYouTubeClient(SEARCH_FIXTURE, VIDEOS_FIXTURE)
    results = youtube.search_fundraising(
        "телетон", api_key="fake-key", _client=client
    )
    assert len(results) == 2
    assert results[0]["platform"] == "youtube"
    assert results[0]["video_id"] == "abc123XYZ"
    assert results[1]["video_id"] == "def456QRS"


def test_search_fundraising_default_api_key_from_config(monkeypatch):
    """Якщо api_key не передано — бере з env YOUTUBE_API_KEY."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    # Без ключа — graceful-skip
    result = youtube.search_fundraising("test")
    assert result == []


def test_search_fundraising_all_fields_present():
    client = _FakeYouTubeClient(SEARCH_FIXTURE, VIDEOS_FIXTURE)
    results = youtube.search_fundraising("test", api_key="k", _client=client)
    for r in results:
        assert "source_url" in r
        assert "platform" in r
        assert "video_id" in r
        assert "title" in r
        assert "description" in r
        assert "published" in r
        assert "channel" in r
        assert "views" in r
        assert "likes" in r
