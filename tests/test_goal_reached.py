"""Unit 2 — goal_reached: успіх-прапор з LLM + keyword fallback + store round-trip.

Тести:
- Campaign має поле goal_reached (bool | None)
- parse_campaign_extraction читає goal_reached з LLM JSON
- text_signals_goal_reached визначає флаг за ключовими словами
- _ingest_one: якщо LLM не встановив, keyword fallback застосовується
- store round-trip: bool/None ↔ int/NULL у SQLite
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
# Schema: goal_reached поле існує
# ---------------------------------------------------------------------------

def test_campaign_has_goal_reached_field():
    c = _base_campaign()
    assert hasattr(c, "goal_reached")
    assert c.goal_reached is None  # за замовч.


def test_campaign_goal_reached_true():
    c = _base_campaign(goal_reached=True)
    assert c.goal_reached is True


def test_campaign_goal_reached_false():
    c = _base_campaign(goal_reached=False)
    assert c.goal_reached is False


# ---------------------------------------------------------------------------
# parse_campaign_extraction — читає goal_reached з LLM JSON
# ---------------------------------------------------------------------------

def _fake_source():
    from fundrec.schema import Source
    return Source(url="https://t.me/ch/1", type="social", tier=3,
                  access="public", license="unknown", actor_id="a1")


def test_parse_campaign_extraction_goal_reached_true():
    from fundrec.extract import parse_campaign_extraction

    obj = {
        "title": "збір", "goal": "military", "type": "mixed",
        "channels": [], "form_factor": [], "tone": [], "cta_type": None,
        "face": None, "cadence": None, "playbook_note": "",
        "amount_uah": None, "amount_usd": None, "reach": None, "engagement": None,
        "spend": None, "assets_count": None, "creatives": [], "partners": [],
        "goal_reached": True,
    }
    campaign, _, _ = parse_campaign_extraction(
        obj, {}, _fake_source(), model="test", campaign_id="c1", actor_id="a1"
    )
    assert campaign.goal_reached is True


def test_parse_campaign_extraction_goal_reached_false():
    from fundrec.extract import parse_campaign_extraction

    obj = {
        "title": "збір", "goal": "military", "type": "mixed",
        "channels": [], "form_factor": [], "tone": [], "cta_type": None,
        "face": None, "cadence": None, "playbook_note": "",
        "amount_uah": None, "amount_usd": None, "reach": None, "engagement": None,
        "spend": None, "assets_count": None, "creatives": [], "partners": [],
        "goal_reached": False,
    }
    campaign, _, _ = parse_campaign_extraction(
        obj, {}, _fake_source(), model="test", campaign_id="c1", actor_id="a1"
    )
    assert campaign.goal_reached is False


def test_parse_campaign_extraction_goal_reached_null():
    from fundrec.extract import parse_campaign_extraction

    obj = {
        "title": "збір", "goal": "military", "type": "mixed",
        "channels": [], "form_factor": [], "tone": [], "cta_type": None,
        "face": None, "cadence": None, "playbook_note": "",
        "amount_uah": None, "amount_usd": None, "reach": None, "engagement": None,
        "spend": None, "assets_count": None, "creatives": [], "partners": [],
        "goal_reached": None,
    }
    campaign, _, _ = parse_campaign_extraction(
        obj, {}, _fake_source(), model="test", campaign_id="c1", actor_id="a1"
    )
    assert campaign.goal_reached is None


# ---------------------------------------------------------------------------
# text_signals_goal_reached — keyword fallback
# ---------------------------------------------------------------------------

def test_text_signals_goal_reached_closing_text():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Ціль досягнута! Дякуємо всім!") is True


def test_text_signals_goal_reached_zibrani():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Збір завершено, зібрали повністю 2 млн, дякуємо!") is True


def test_text_signals_goal_reached_100_percent():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Зібрано 100% від цілі") is True


def test_text_signals_goal_reached_zakryly():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Закрили збір, всім дякуємо") is True


def test_text_signals_goal_reached_none_for_no_signal():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Збір на FPV дрони, допоможіть") is None


def test_text_signals_goal_reached_none_for_empty():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("") is None
    assert text_signals_goal_reached(None) is None


def test_text_signals_goal_reached_metu_dosyagnuto():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Мету досягнуто завдяки вашій підтримці") is True


def test_text_signals_goal_reached_dyakuyemo_zibraly():
    from fundrec.analyze import text_signals_goal_reached

    assert text_signals_goal_reached("Дякуємо, зібрали! Відправляємо техніку") is True


# ---------------------------------------------------------------------------
# store round-trip: bool ↔ int ↔ bool/None
# ---------------------------------------------------------------------------

def test_store_roundtrip_goal_reached_true(tmp_path):
    from fundrec import store
    from fundrec.schema import Actor

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))

    c = _base_campaign(goal_reached=True)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].goal_reached is True


def test_store_roundtrip_goal_reached_false(tmp_path):
    from fundrec import store
    from fundrec.schema import Actor

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))

    c = _base_campaign(goal_reached=False)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].goal_reached is False


def test_store_roundtrip_goal_reached_none(tmp_path):
    from fundrec import store
    from fundrec.schema import Actor

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))

    c = _base_campaign(goal_reached=None)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].goal_reached is None


# ---------------------------------------------------------------------------
# Keyword fallback в _ingest_one: якщо LLM не встановив → keyword fallback
# ---------------------------------------------------------------------------

def _fake_complete_no_goal_reached(prompt):
    if "creatives" in prompt:
        return {
            "title": "Збір завершено, зібрали!", "goal": "military", "type": "mixed",
            "channels": [], "date_start": None, "date_end": None,
            "year": 2024, "form_factor": [], "cta_type": None,
            "tone": [], "face": None, "cadence": None, "playbook_note": "",
            "amount_uah": None, "amount_usd": None, "reach": None, "engagement": None,
            "spend": None, "assets_count": None, "creatives": [], "partners": [],
            # LLM не встановив goal_reached (відсутнє поле → None)
        }
    return {
        "title": "тест", "goal": "military", "style": [], "method": [],
        "year": 2024, "amount_uah": None, "amount_usd": None,
        "goal_amount": None, "currency_raw": None,
    }


def test_ingest_one_keyword_fallback_sets_goal_reached(tmp_path):
    """Якщо LLM не встановив goal_reached, keyword fallback визначає True з тексту."""
    from fundrec import store, ingest
    from fundrec.schema import Source, Actor

    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Test", type="individual"))

    raw = {
        "source_url": "https://t.me/ch/1",
        "platform": "telegram",
        "text": "Збір завершено, зібрали повністю! Дякуємо, мету досягнуто.",
        "views": 500,
    }
    src = Source(url="https://t.me/ch/1", type="social", tier=3,
                 access="public", license="unknown", actor_id="a1")

    ingest._ingest_one(
        conn, raw, src,
        raw_dir=tmp_path / "raw",
        actor_id="a1",
        complete_fn=_fake_complete_no_goal_reached,
        sleep_fn=lambda s: None,
        source_key="telegram",
        collected_per_source={},
        jar_fetch_fn=None,
        seen_jar_ids=set(),
    )
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    assert campaigns[0].goal_reached is True
