"""Unit 4 — goal_reached_rate, engagement summaries, build_analytics blocks.

Тести:
- goal_reached_rate обчислює частку goal_reached==True серед non-null
- campaign_axis_summary підтримує metric="engagement" і "reach"
- build_analytics включає success_rates і нові осьові підсумки
"""
from __future__ import annotations

import pytest

from fundrec.schema import Campaign, Actor
from fundrec import store
from fundrec.pipeline_analyze import build_analytics


def _actor(id="a1"):
    return Actor(id=id, name="T", type="individual")


def _camp(id, goal_reached=None, tone=None, channels=None, reach=None, engagement=None, **kw):
    defaults = dict(
        id=id, actor_id="a1", title=f"camp {id}", goal="military", type="mixed",
        channels=channels or ["telegram"],
        tone=tone or ["urgency"],
        reach=reach,
        engagement=engagement,
    )
    defaults.update(kw)
    if goal_reached is not None:
        defaults["goal_reached"] = goal_reached
    return Campaign(**defaults)


# ---------------------------------------------------------------------------
# goal_reached_rate — чистий (не БД)
# ---------------------------------------------------------------------------

def test_goal_reached_rate_basic():
    from fundrec.analyze import goal_reached_rate

    camps = [
        _camp("c1", tone=["urgency"], goal_reached=True),
        _camp("c2", tone=["urgency"], goal_reached=False),
        _camp("c3", tone=["urgency"], goal_reached=None),
        _camp("c4", tone=["emotional"], goal_reached=True),
        _camp("c5", tone=["emotional"], goal_reached=None),
    ]
    rows = goal_reached_rate(camps, axis="tone")
    by_key = {r["key"]: r for r in rows}

    # urgency: 1 True, 1 False → rate = 0.5; n = 3 (all under this tone)
    assert "urgency" in by_key
    assert by_key["urgency"]["value"] == pytest.approx(0.5)
    assert by_key["urgency"]["n"] == 3

    # emotional: 1 True, 0 False (1 None) → rate = 1.0; n = 2
    assert "emotional" in by_key
    assert by_key["emotional"]["value"] == pytest.approx(1.0)
    assert by_key["emotional"]["n"] == 2


def test_goal_reached_rate_all_none():
    from fundrec.analyze import goal_reached_rate

    camps = [
        _camp("c1", tone=["urgency"], goal_reached=None),
        _camp("c2", tone=["urgency"], goal_reached=None),
    ]
    rows = goal_reached_rate(camps, axis="tone")
    by_key = {r["key"]: r for r in rows}
    # Всі None → value=None (честний null)
    assert by_key["urgency"]["value"] is None


def test_goal_reached_rate_empty():
    from fundrec.analyze import goal_reached_rate

    rows = goal_reached_rate([], axis="tone")
    assert rows == []


def test_goal_reached_rate_channel_axis():
    from fundrec.analyze import goal_reached_rate

    camps = [
        _camp("c1", channels=["telegram"], goal_reached=True),
        _camp("c2", channels=["youtube"], goal_reached=False),
        _camp("c3", channels=["telegram"], goal_reached=True),
    ]
    rows = goal_reached_rate(camps, axis="channels")
    by_key = {r["key"]: r for r in rows}
    assert by_key["telegram"]["value"] == pytest.approx(1.0)
    assert by_key["youtube"]["value"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# campaign_axis_summary — metric="engagement" та "reach"
# ---------------------------------------------------------------------------

def test_axis_summary_engagement_median():
    from fundrec.analyze import campaign_axis_summary

    camps = [
        _camp("c1", tone=["urgency"], engagement=100),
        _camp("c2", tone=["urgency"], engagement=200),
        _camp("c3", tone=["urgency"], engagement=None),
        _camp("c4", tone=["emotional"], engagement=50),
    ]
    rows = campaign_axis_summary(camps, axis="tone", metric="engagement")
    by_key = {r["key"]: r for r in rows}

    # urgency: median(100, 200) = 150
    assert by_key["urgency"]["value"] == pytest.approx(150.0)
    assert by_key["urgency"]["n"] == 3  # включно з None

    # emotional: median(50) = 50
    assert by_key["emotional"]["value"] == pytest.approx(50.0)


def test_axis_summary_reach_median():
    from fundrec.analyze import campaign_axis_summary

    camps = [
        _camp("c1", channels=["telegram"], reach=1000),
        _camp("c2", channels=["telegram"], reach=3000),
        _camp("c3", channels=["youtube"], reach=5000),
    ]
    rows = campaign_axis_summary(camps, axis="channels", metric="reach")
    by_key = {r["key"]: r for r in rows}
    assert by_key["telegram"]["value"] == pytest.approx(2000.0)
    assert by_key["youtube"]["value"] == pytest.approx(5000.0)


def test_axis_summary_engagement_all_none():
    from fundrec.analyze import campaign_axis_summary

    camps = [_camp("c1", tone=["urgency"], engagement=None)]
    rows = campaign_axis_summary(camps, axis="tone", metric="engagement")
    assert rows[0]["value"] is None


# ---------------------------------------------------------------------------
# build_analytics: нові блоки присутні
# ---------------------------------------------------------------------------

def _setup(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, _actor())
    return conn


def test_build_analytics_has_success_rates(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("c1", goal_reached=True))
    store.upsert_campaign(conn, _camp("c2", goal_reached=False))

    result = build_analytics(conn)
    ca = result["campaign_analytics"]
    assert "success_rates" in ca
    assert "tone" in ca["success_rates"]
    assert "channels" in ca["success_rates"]


def test_build_analytics_has_engagement_summaries(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("c1", engagement=100, reach=1000))

    result = build_analytics(conn)
    ca = result["campaign_analytics"]
    axs = ca["axis_summaries"]
    assert "tone_engagement" in axs
    assert "channel_engagement" in axs


def test_build_analytics_success_rates_values(tmp_path):
    """Значення success_rates коректні для відомого набору даних."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("c1", tone=["urgency"], channels=["telegram"],
                                      goal_reached=True))
    store.upsert_campaign(conn, _camp("c2", tone=["urgency"], channels=["telegram"],
                                      goal_reached=False))
    store.upsert_campaign(conn, _camp("c3", tone=["emotional"], channels=["youtube"],
                                      goal_reached=None))

    result = build_analytics(conn)
    sr = result["campaign_analytics"]["success_rates"]

    # urgency: 1/2 = 0.5
    tone_rows = {r["key"]: r for r in sr["tone"]}
    assert tone_rows["urgency"]["value"] == pytest.approx(0.5)

    # emotional: all None → value=None
    assert tone_rows["emotional"]["value"] is None


def test_build_analytics_existing_keys_unchanged(tmp_path):
    """backward-compat: попередні ключі лишаються."""
    conn = _setup(tmp_path)
    result = build_analytics(conn)
    for key in ("kpis", "trends", "crosstabs", "campaign_analytics"):
        assert key in result
    ca = result["campaign_analytics"]
    for key in ("kpis", "crosstabs", "axis_summaries"):
        assert key in ca
    # Старі axis summaries збереглися
    for key in ("tone_amount", "cta_amount", "face_amount", "channel_amount"):
        assert key in ca["axis_summaries"]
