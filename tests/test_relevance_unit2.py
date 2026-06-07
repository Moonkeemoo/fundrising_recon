"""Unit 2 — гейт релевантності в ingest: топічний контент пропускається.

TDD: тести написані ДО змін у ingest.py.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Спільні fake-дані
# ---------------------------------------------------------------------------

# Топічний відеоролик — немає jar/card/ask
_TOPICAL_ITEM = {
    "source_url": "https://www.youtube.com/watch?v=tccc_video",
    "platform": "youtube",
    "video_id": "tccc_video",
    "title": "ТАКТИЧНА АПТЕЧКА TCCC для військових по системі MARCH",
    "text": (
        "У цьому відео ми розглядаємо комплектацію тактичної аптечки "
        "за стандартом TCCC та системою MARCH. Навчальний контент."
    ),
    "description": "Навчальний контент про медицину на полі бою.",
    "views": 50000,
    "likes": 1200,
    "published": "2024-05-01T00:00:00Z",
    "channel": "TacticalUA",
}

# Реальний збір — є jar-link
_REAL_ZBIR_ITEM = {
    "source_url": "https://www.youtube.com/watch?v=real_zbir",
    "platform": "youtube",
    "video_id": "real_zbir",
    "title": "Збір на FPV дрони для ЗСУ",
    "text": "Збираємо кошти на FPV! Банка: send.monobank.ua/jar/REALJAR1",
    "description": "Підтримайте збір!",
    "views": 12000,
    "likes": 600,
    "published": "2024-06-01T00:00:00Z",
    "channel": "DefenseUA",
}

_FAKE_LLM_CAMPAIGN = {
    "title": "FPV кампанія",
    "goal": "military/fpv",
    "type": "awareness",
    "channels": ["youtube"],
    "date_start": None,
    "date_end": None,
    "year": 2024,
    "form_factor": ["video"],
    "cta_type": "donate",
    "tone": ["urgency"],
    "face": None,
    "cadence": None,
    "playbook_note": "FPV campaign",
    "amount_uah": None,
    "amount_usd": None,
    "reach": None,
    "engagement": None,
    "spend": None,
    "assets_count": None,
    "case_id": None,
    "creatives": [],
    "partners": [],
}

_FAKE_LLM_CASE = {
    "title": "FPV для бригади",
    "goal": "military/fpv",
    "style": ["urgency"],
    "method": ["monobank_jar"],
    "year": 2024,
    "amount_uah": None,
    "amount_usd": None,
    "goal_amount": None,
    "currency_raw": "UAH",
}


def _make_components_with_both_items():
    """_components з двома youtube-відео: 1 топічний + 1 реальний збір."""

    def fake_collector(theme):
        return [_TOPICAL_ITEM, _REAL_ZBIR_ITEM]

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    return {
        "search": lambda q: [],
        "collect": {"youtube": fake_collector},
        "complete": fake_complete,
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }


# ---------------------------------------------------------------------------
# Тести
# ---------------------------------------------------------------------------

def test_topical_item_skipped_real_item_stored(tmp_path):
    """Топічний (no ask) пропускається; реальний збір зберігається.

    1 топічний + 1 реальний → campaigns==1, skipped_irrelevant==1.
    """
    from fundrec import ingest, store

    components = _make_components_with_both_items()
    summary = ingest.run_ingest(
        "TCCC аптечка",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert summary["campaigns"] == 1, (
        f"Очікувалась 1 кампанія (збір), отримано {summary['campaigns']}"
    )
    assert summary.get("skipped_irrelevant", 0) == 1, (
        f"Очікувався 1 пропущений, отримано {summary.get('skipped_irrelevant')}"
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    # Збережено саме реальний збір, не топічний
    urls = [c.id for c in campaigns]
    # id формується з URL real_zbir
    import hashlib
    real_id = "camp-" + hashlib.sha256(
        "https://www.youtube.com/watch?v=real_zbir".encode()
    ).hexdigest()[:12]
    assert real_id in urls


def test_skipped_irrelevant_in_summary(tmp_path):
    """skipped_irrelevant є у summary і відповідає кількості відкинутих."""
    from fundrec import ingest

    components = _make_components_with_both_items()
    summary = ingest.run_ingest(
        "TCCC аптечка",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert "skipped_irrelevant" in summary
    assert summary["skipped_irrelevant"] == 1


def test_all_real_items_no_skipped(tmp_path):
    """Якщо всі item-и є реальними зборами → skipped_irrelevant==0."""
    from fundrec import ingest

    real_item2 = {
        **_REAL_ZBIR_ITEM,
        "source_url": "https://www.youtube.com/watch?v=zbir2",
        "video_id": "zbir2",
        "text": "Донат на машину: send.monobank.ua/jar/JAR002",
    }

    def fake_collector(theme):
        return [_REAL_ZBIR_ITEM, real_item2]

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    components = {
        "search": lambda q: [],
        "collect": {"youtube": fake_collector},
        "complete": fake_complete,
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }

    summary = ingest.run_ingest(
        "збір дрони",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert summary["campaigns"] == 2
    assert summary["skipped_irrelevant"] == 0


def test_topical_item_not_written_to_raw_cache(tmp_path):
    """Топічний item пропускається до _write_raw_cache — сирий файл не записується.

    Лише 1 raw-файл (реальний збір), не 2.
    """
    from fundrec import ingest

    components = _make_components_with_both_items()
    raw_dir = tmp_path / "raw"
    ingest.run_ingest(
        "TCCC аптечка",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=raw_dir,
        _components=components,
    )

    raw_files = list(raw_dir.glob("*.json"))
    assert len(raw_files) == 1


def test_skipped_irrelevant_logged_to_stderr(tmp_path, capsys):
    """Пропущений топічний item логується до stderr."""
    from fundrec import ingest

    components = _make_components_with_both_items()
    ingest.run_ingest(
        "TCCC аптечка",
        sources=["youtube"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    captured = capsys.readouterr()
    # URL топічного item має бути в stderr
    assert "tccc_video" in captured.err or "пропущено" in captured.err


def test_url_based_topical_item_skipped(tmp_path):
    """URL-based (reports) топічний item також пропускається."""
    from fundrec import ingest, store

    topical_url = "https://example.com/tccc-article"
    topical_raw = {
        "url": topical_url,
        "title": "Тактична медицина TCCC для бійців",
        "raw_text": "Навчальний курс з тактичної медицини. MARCH протокол.",
    }

    real_url = "https://example.com/zbir-drones"
    real_raw = {
        "url": real_url,
        "title": "Збір на дрони",
        "raw_text": "Донат: send.monobank.ua/jar/DRONE99",
    }

    def fake_search(q):
        return [topical_url, real_url]

    def fake_reports_fetch(url, *, _client=None):
        if url == topical_url:
            return topical_raw
        return real_raw

    call_count = {"n": 0}

    def fake_complete(prompt):
        call_count["n"] += 1
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    components = {
        "search": fake_search,
        "collect": {"reports": fake_reports_fetch},
        "complete": fake_complete,
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }

    summary = ingest.run_ingest(
        "медицина дрони",
        sources=["reports"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    assert summary["campaigns"] == 1
    assert summary["skipped_irrelevant"] == 1

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
