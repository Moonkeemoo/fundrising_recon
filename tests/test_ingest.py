"""Tests for fundrec.ingest — run_ingest end-to-end (fakes), dry-run, resumability.

Mandatory corrections verified:
1. run_ingest extracts CAMPAIGNS (not just Cases) — campaigns land in sqlite.
2. data/raw/ cache — raw payloads written as JSON files (injectable raw_dir).
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

_FAKE_URLS = ["https://example.com/zbir1", "https://example.com/zbir2"]

_FAKE_RAW = {
    "url": "https://example.com/zbir1",
    "title": "FPV для бригади",
    "amount_uah": 500_000.0,
    "goal_amount": 1_000_000.0,
    "currency_raw": "UAH",
    "raw_text": "зібрано 500 000 грн",
}

_FAKE_LLM_CASE = {
    "title": "FPV для бригади",
    "goal": "military/fpv",
    "style": ["urgency"],
    "method": ["monobank_jar"],
    "year": 2024,
    "amount_uah": 500_000.0,
    "amount_usd": None,
    "goal_amount": 1_000_000.0,
    "currency_raw": "UAH",
}

_FAKE_LLM_CAMPAIGN = {
    "title": "FPV кампанія",
    "goal": "military/fpv",
    "type": "awareness",
    "channels": ["telegram"],
    "date_start": None,
    "date_end": None,
    "year": 2024,
    "form_factor": ["text_post"],
    "cta_type": "donate",
    "tone": ["urgency"],
    "face": None,
    "cadence": None,
    "playbook_note": "Urgency-based campaign for FPV drones",
    "amount_uah": 500_000.0,
    "amount_usd": None,
    "reach": None,
    "engagement": None,
    "spend": None,
    "assets_count": None,
    "case_id": None,
    "creatives": [],
    "partners": [],
}


def _make_components(*, extra_urls=None):
    """Builds a _components dict with all-fake injections."""
    urls = extra_urls or _FAKE_URLS

    def fake_search(query):
        return list(urls)

    def fake_reports_fetch(url, *, _client=None):
        return {**_FAKE_RAW, "url": url}

    call_count = {"n": 0}

    def fake_complete(prompt):
        # Alternate between campaign and case responses based on call index
        call_count["n"] += 1
        # Campaign prompt has "creatives" keyword, case does not
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    def fake_sleep(seconds):
        pass  # no-op in tests

    return {
        "search": fake_search,
        "collect": {
            "reports": fake_reports_fetch,
        },
        "complete": fake_complete,
        "judge": fake_judge,
        "sleep": fake_sleep,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_ingest_returns_summary(tmp_path):
    from fundrec import ingest
    components = _make_components()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    assert isinstance(summary, dict)
    assert "discovered" in summary
    assert "campaigns" in summary
    assert "exported" in summary
    assert "skipped_no_key" in summary
    assert summary["discovered"] >= 0
    assert summary["campaigns"] >= 1


def test_run_ingest_writes_sqlite(tmp_path):
    """Campaigns (mandatory correction 1) land in sqlite."""
    from fundrec import ingest, store
    components = _make_components()
    ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) >= 1
    assert campaigns[0].amount_uah == 500_000.0


def test_run_ingest_writes_cases_json(tmp_path):
    from fundrec import ingest
    components = _make_components()
    ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert "count" in data
    assert "cases" in data


def test_run_ingest_writes_raw_cache(tmp_path):
    """Mandatory correction 2: raw payloads written as JSON files under raw_dir."""
    from fundrec import ingest
    components = _make_components(extra_urls=["https://example.com/zbir1"])
    raw_dir = tmp_path / "raw"
    ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=raw_dir,
        _components=components,
    )
    raw_files = list(raw_dir.glob("*.json"))
    assert len(raw_files) >= 1
    # Verify the content is valid JSON with url field
    payload = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert "url" in payload


def test_run_ingest_skips_no_key_sources(tmp_path):
    """Sources that need a key (youtube, telegram, meta) are reported in skipped_no_key."""
    from fundrec import ingest
    # _components has no youtube/telegram/meta collectors — they rely on env keys
    components = _make_components()
    summary = ingest.run_ingest(
        "FPV",
        sources=["reports", "youtube", "telegram", "meta"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    # youtube/telegram/meta should be in skipped because conftest clears those env vars
    assert "youtube" in summary["skipped_no_key"] or "telegram" in summary["skipped_no_key"]


def test_run_ingest_resumable_no_duplicates(tmp_path):
    """Re-running ingest with same data does not create duplicate campaigns."""
    from fundrec import ingest, store

    components = _make_components(extra_urls=["https://example.com/zbir1"])

    db_path = tmp_path / "test.sqlite"
    out_path = tmp_path / "cases.json"
    raw_dir = tmp_path / "raw"

    ingest.run_ingest("FPV", sources=["reports"], max_items=5,
                      db_path=db_path, out_path=out_path, raw_dir=raw_dir,
                      _components=components)
    ingest.run_ingest("FPV", sources=["reports"], max_items=5,
                      db_path=db_path, out_path=out_path, raw_dir=raw_dir,
                      _components=components)

    conn = store.connect(db_path)
    campaigns = store.load_campaigns(conn)
    # Should have exactly 1 campaign for zbir1, not 2
    urls = [c.id for c in campaigns]
    # Dedup by campaign_id (URL-derived)
    assert len(set(urls)) == len(urls)
    assert len(campaigns) == 1


def test_dry_run_returns_summary_without_writes(tmp_path):
    from fundrec import ingest

    components = _make_components()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["reports"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
        dry_run=True,
    )
    assert "discovered" in summary
    assert "active_sources" in summary
    # No database written in dry-run
    assert not (tmp_path / "test.sqlite").exists()


def test_main_dry_run_cli(tmp_path, capsys):
    """CLI --dry-run prints honest report to stderr."""
    from fundrec.ingest import main

    result = main([
        "--theme", "тест",
        "--sources", "reports",
        "--dry-run",
        "--db", str(tmp_path / "test.sqlite"),
        "--out", str(tmp_path / "cases.json"),
    ])
    assert result == 0
    captured = capsys.readouterr()
    # dry-run output should mention the theme or sources
    assert "тест" in captured.err or "reports" in captured.err or "dry" in captured.err.lower()


# ---------------------------------------------------------------------------
# Search-based collection (youtube / meta) — нові тести
# ---------------------------------------------------------------------------

_FAKE_YOUTUBE_ITEMS = [
    {
        "source_url": "https://www.youtube.com/watch?v=aaa111",
        "platform": "youtube",
        "video_id": "aaa111",
        "title": "FPV дрони для ЗСУ",
        "description": "Збираємо кошти на FPV дрони",
        "published": "2024-01-01T00:00:00Z",
        "channel": "TestChannel",
        "views": 10000,
        "likes": 500,
    },
    {
        "source_url": "https://www.youtube.com/watch?v=bbb222",
        "platform": "youtube",
        "video_id": "bbb222",
        "title": "Збір на броньований автомобіль",
        "description": "Допоможіть зібрати на авто",
        "published": "2024-02-01T00:00:00Z",
        "channel": "TestChannel",
        "views": 5000,
        "likes": 300,
    },
]


def _make_components_youtube_only():
    """_components без web-search (discovered_urls=[]), тільки youtube fake collector."""

    def fake_youtube_collector(theme):
        return list(_FAKE_YOUTUBE_ITEMS)

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    def fake_sleep(seconds):
        pass

    return {
        # Без "search" — discovered_urls лишається порожнім
        "collect": {
            "youtube": fake_youtube_collector,
        },
        "complete": fake_complete,
        "judge": fake_judge,
        "sleep": fake_sleep,
    }


def test_youtube_search_based_collection_yields_campaigns(tmp_path):
    """Search-based (youtube) збирає кампанії навіть без discovered_urls.

    Доводить, що youtube-колектор не залежить від web-discovery.
    """
    from fundrec import ingest, store

    components = _make_components_youtube_only()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    # Нема жодного discovered URL
    assert summary["discovered"] == 0

    # Але 2 кампанії збережені через youtube search
    assert summary["campaigns"] == 2
    assert summary["collected_per_source"].get("youtube", 0) == 2

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 2


def test_youtube_search_source_type_is_social(tmp_path):
    """Джерело youtube зберігається з type='social' і tier=3."""
    from fundrec import ingest, store

    components = _make_components_youtube_only()
    ingest.run_ingest(
        "FPV дрони",
        sources=["youtube"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    conn = store.connect(tmp_path / "test.sqlite")
    row = conn.execute(
        "SELECT type, tier FROM sources WHERE url = ?",
        ("https://www.youtube.com/watch?v=aaa111",),
    ).fetchone()
    assert row is not None
    assert row[0] == "social"
    assert row[1] == 3


def test_youtube_search_writes_raw_cache(tmp_path):
    """Сирі payload youtube-відео записуються у raw_dir."""
    from fundrec import ingest

    components = _make_components_youtube_only()
    raw_dir = tmp_path / "raw"
    ingest.run_ingest(
        "FPV дрони",
        sources=["youtube"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=raw_dir,
        _components=components,
    )
    raw_files = list(raw_dir.glob("*.json"))
    assert len(raw_files) == 2


def test_youtube_search_resumable_no_duplicates(tmp_path):
    """Повторний запуск з тими самими youtube-відео не дублює кампанії."""
    from fundrec import ingest, store

    db_path = tmp_path / "test.sqlite"
    out_path = tmp_path / "cases.json"
    raw_dir = tmp_path / "raw"

    components = _make_components_youtube_only()
    ingest.run_ingest("FPV", sources=["youtube"], max_items=10,
                      db_path=db_path, out_path=out_path, raw_dir=raw_dir,
                      _components=components)
    ingest.run_ingest("FPV", sources=["youtube"], max_items=10,
                      db_path=db_path, out_path=out_path, raw_dir=raw_dir,
                      _components=components)

    conn = store.connect(db_path)
    campaigns = store.load_campaigns(conn)
    ids = [c.id for c in campaigns]
    assert len(set(ids)) == len(ids)
    assert len(campaigns) == 2


def test_search_and_url_based_collection_combined(tmp_path):
    """Комбінований запуск: 1 URL (reports) + 2 youtube → 3 кампанії."""
    from fundrec import ingest, store

    def fake_search(query):
        return ["https://example.com/zbir_combined"]

    def fake_reports_fetch(url, *, _client=None):
        return {**_FAKE_RAW, "url": url}

    def fake_youtube_collector(theme):
        return list(_FAKE_YOUTUBE_ITEMS)

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    components = {
        "search": fake_search,
        "collect": {
            "reports": fake_reports_fetch,
            "youtube": fake_youtube_collector,
        },
        "complete": fake_complete,
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }

    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["reports", "youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert summary["discovered"] == 1
    assert summary["campaigns"] == 3
    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 3


def test_youtube_skipped_when_no_key_and_no_injected_collector(tmp_path):
    """youtube без ключа і без ін'єктованого колектора → skipped_no_key."""
    from fundrec import ingest

    # Тільки reports, youtube БЕЗ ін'єкції — повинен бути в skipped_no_key
    components = _make_components()
    summary = ingest.run_ingest(
        "FPV",
        sources=["reports", "youtube"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    assert "youtube" in summary["skipped_no_key"]


def test_youtube_active_when_injected_collector_no_key(tmp_path):
    """youtube з ін'єктованим колектором активний навіть без env-ключа."""
    from fundrec import ingest

    components = _make_components_youtube_only()
    summary = ingest.run_ingest(
        "FPV",
        sources=["youtube"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    # Не в skipped_no_key
    assert "youtube" not in summary["skipped_no_key"]
    # Кампанії зібрано
    assert summary["campaigns"] == 2


# ---------------------------------------------------------------------------
# Telegram web-path collection — нові тести
# ---------------------------------------------------------------------------

_FAKE_TELEGRAM_ITEMS = [
    {
        "source_url": "https://t.me/prytulafoundation/101",
        "platform": "telegram",
        "channel": "prytulafoundation",
        "text": "Збір на FPV дрони! Монобанк jar 5375411200012345",
        "views": 12300,
        "date": "2024-03-15T10:30:00+00:00",
        "message_id": 101,
    },
    {
        "source_url": "https://t.me/back_and_alive/201",
        "platform": "telegram",
        "channel": "back_and_alive",
        "text": "Банка на броньовик: mono.bank/send/xyz",
        "views": 3100,
        "date": "2024-03-10T09:00:00+00:00",
        "message_id": 201,
    },
]


def _make_components_telegram_only():
    """_components без web-search, тільки telegram fake collector."""

    def fake_telegram_collector(theme):
        return list(_FAKE_TELEGRAM_ITEMS)

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    def fake_sleep(seconds):
        pass

    return {
        "collect": {
            "telegram": fake_telegram_collector,
        },
        "complete": fake_complete,
        "judge": fake_judge,
        "sleep": fake_sleep,
    }


def test_telegram_search_based_collection_yields_campaigns(tmp_path):
    """Search-based (telegram web) збирає кампанії без ключів."""
    from fundrec import ingest, store

    components = _make_components_telegram_only()
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert summary["discovered"] == 0
    assert summary["campaigns"] == 2
    assert summary["collected_per_source"].get("telegram", 0) == 2

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 2


def test_telegram_active_by_default_no_keys(tmp_path):
    """telegram активний за замовчуванням через web-шлях (не потребує ключів).

    Підтверджує, що telegram НЕ в skipped_no_key навіть без env-ключів.
    """
    from fundrec import ingest

    components = _make_components_telegram_only()
    summary = ingest.run_ingest(
        "FPV",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    assert "telegram" not in summary["skipped_no_key"]
    assert summary["campaigns"] == 2


def test_telegram_search_source_type_is_social_tier3(tmp_path):
    """Джерело telegram зберігається з type='social' і tier=3."""
    from fundrec import ingest, store

    components = _make_components_telegram_only()
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )
    conn = store.connect(tmp_path / "test.sqlite")
    row = conn.execute(
        "SELECT type, tier FROM sources WHERE url = ?",
        ("https://t.me/prytulafoundation/101",),
    ).fetchone()
    assert row is not None
    assert row[0] == "social"
    assert row[1] == 3
