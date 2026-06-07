"""Unit 1 — детерміновані engagement/reach з сирих сигналів.

Тести підтверджують, що _apply_signals встановлює reach/engagement з
реальних платформних даних (НЕ LLM) з правильним provenance.
"""
from __future__ import annotations

import pytest

from fundrec.schema import Campaign


def _base_campaign(**kw) -> Campaign:
    defaults = dict(
        id="c1", actor_id="a1", title="тест", goal="military", type="mixed",
    )
    defaults.update(kw)
    return Campaign(**defaults)


# ---------------------------------------------------------------------------
# _apply_signals — telegram
# ---------------------------------------------------------------------------

def test_telegram_sets_reach_from_views():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 1000, "platform": "telegram", "source_url": "https://t.me/ch/1"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.reach == 1000


def test_telegram_sets_engagement_from_forwards():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 1000, "forwards": 50, "platform": "telegram", "source_url": "https://t.me/ch/1"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.engagement == 50


def test_telegram_sets_engagement_from_views_when_no_forwards():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 800, "platform": "telegram", "source_url": "https://t.me/ch/1"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.engagement == 800


def test_telegram_provenance_stored():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 1000, "forwards": 50, "platform": "telegram", "source_url": "https://t.me/ch/1"}
    _apply_signals(campaign, raw, tier=3)
    assert "reach" in campaign.provenance
    assert campaign.provenance["reach"]["tier"] == 3
    assert "signal" in campaign.provenance["reach"]["note"]
    assert "engagement" in campaign.provenance
    assert campaign.provenance["engagement"]["tier"] == 3


def test_telegram_none_views_not_set():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": None, "platform": "telegram", "source_url": "https://t.me/ch/1"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.reach is None
    assert campaign.engagement is None


# ---------------------------------------------------------------------------
# _apply_signals — youtube
# ---------------------------------------------------------------------------

def test_youtube_sets_reach_and_engagement():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 2000, "likes": 80, "platform": "youtube", "source_url": "https://youtube.com/v/x"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.reach == 2000
    assert campaign.engagement == 80


def test_youtube_engagement_falls_back_to_views_when_no_likes():
    from fundrec.ingest import _apply_signals

    campaign = _base_campaign()
    raw = {"views": 2000, "platform": "youtube", "source_url": "https://youtube.com/v/x"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.reach == 2000
    assert campaign.engagement == 2000


def test_youtube_provenance_confidence_tier3():
    from fundrec.ingest import _apply_signals
    from fundrec.extract import _TIER_CONFIDENCE

    campaign = _base_campaign()
    raw = {"views": 2000, "likes": 80, "platform": "youtube", "source_url": "https://youtube.com/v/x"}
    _apply_signals(campaign, raw, tier=3)
    assert campaign.provenance["reach"]["confidence"] == _TIER_CONFIDENCE[3]
    assert campaign.provenance["engagement"]["confidence"] == _TIER_CONFIDENCE[3]


# ---------------------------------------------------------------------------
# Інтеграційний: _ingest_one застосовує signals після extract
# ---------------------------------------------------------------------------

def _fake_complete(prompt):
    if "creatives" in prompt:
        return {
            "title": "тест", "goal": "military", "type": "mixed",
            "channels": ["telegram"], "date_start": None, "date_end": None,
            "year": 2024, "form_factor": ["text"], "cta_type": None,
            "tone": ["urgency"], "face": None, "cadence": None,
            "playbook_note": "", "amount_uah": None, "amount_usd": None,
            "reach": None, "engagement": None, "spend": None, "assets_count": None,
            "creatives": [], "partners": [],
        }
    return {
        "title": "тест", "goal": "military", "style": [], "method": [],
        "year": 2024, "amount_uah": None, "amount_usd": None,
        "goal_amount": None, "currency_raw": None,
    }


def test_ingest_one_telegram_signals_land_in_db(tmp_path):
    """_ingest_one: telegram raw з views/forwards → stored campaign має reach/engagement."""
    import sqlite3
    from fundrec import store, ingest
    from fundrec.schema import Source

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    from fundrec.schema import Actor
    store.upsert_actor(conn, Actor(id="a1", name="Test", type="individual"))

    raw = {
        "source_url": "https://t.me/ch/1",
        "platform": "telegram",
        "text": "збір на дрони",
        "views": 1000,
        "forwards": 50,
    }
    source = store.Source.__class__  # type: ignore  # use schema directly
    from fundrec.schema import Source
    src = Source(url="https://t.me/ch/1", type="social", tier=3,
                 access="public", license="unknown", actor_id="a1")

    result = ingest._ingest_one(
        conn, raw, src,
        raw_dir=tmp_path / "raw",
        actor_id="a1",
        complete_fn=_fake_complete,
        sleep_fn=lambda s: None,
        source_key="telegram",
        collected_per_source={},
        jar_fetch_fn=None,
        seen_jar_ids=set(),
    )
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    c = campaigns[0]
    assert c.reach == 1000
    assert c.engagement == 50
    assert "reach" in c.provenance
    assert "engagement" in c.provenance


def test_ingest_one_youtube_signals_land_in_db(tmp_path):
    """_ingest_one: youtube raw з views/likes → stored campaign має reach/engagement."""
    from fundrec import store, ingest
    from fundrec.schema import Source, Actor

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Test", type="individual"))

    raw = {
        "source_url": "https://youtube.com/watch?v=abc",
        "platform": "youtube",
        "title": "збір",
        "views": 2000,
        "likes": 80,
    }
    src = Source(url="https://youtube.com/watch?v=abc", type="social", tier=3,
                 access="public", license="unknown", actor_id="a1")

    ingest._ingest_one(
        conn, raw, src,
        raw_dir=tmp_path / "raw",
        actor_id="a1",
        complete_fn=_fake_complete,
        sleep_fn=lambda s: None,
        source_key="youtube",
        collected_per_source={},
        jar_fetch_fn=None,
        seen_jar_ids=set(),
    )
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    c = campaigns[0]
    assert c.reach == 2000
    assert c.engagement == 80
