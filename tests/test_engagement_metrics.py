"""Unit 1 — engagement_rate, actor_median_engagement_rate, rel_resonance_map.

Дисципліна: None≠0. rel_resonance тепер = reach-резонанс (reach vs медіана
каналу), а НЕ engagement-нормалізація (engagement чесно відсутній з public TG).
"""
from __future__ import annotations

import pytest

from fundrec.analyze import (
    actor_median_engagement_rate,
    engagement_rate,
    rel_resonance_map,
)
from fundrec.schema import Campaign


def _camp(
    id: str,
    actor_id: str = "a1",
    reach: float | None = None,
    engagement: float | None = None,
    handle: str | None = None,
) -> Campaign:
    prov = {}
    if handle is not None:
        prov["reach"] = {"source_url": f"https://t.me/{handle}/1"}
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"camp {id}",
        goal="military",
        type="online_ad",
        reach=reach,
        engagement=engagement,
        provenance=prov,
    )


# ── engagement_rate ──────────────────────────────────────────────────────────


def test_engagement_rate_basic():
    c = _camp("k1", reach=1000.0, engagement=50.0)
    assert engagement_rate(c) == pytest.approx(0.05)


def test_engagement_rate_reach_zero_returns_none():
    c = _camp("k1", reach=0.0, engagement=50.0)
    assert engagement_rate(c) is None


def test_engagement_rate_reach_none_returns_none():
    c = _camp("k1", reach=None, engagement=50.0)
    assert engagement_rate(c) is None


def test_engagement_rate_engagement_none_returns_none():
    c = _camp("k1", reach=1000.0, engagement=None)
    assert engagement_rate(c) is None


def test_engagement_rate_both_none_returns_none():
    c = _camp("k1", reach=None, engagement=None)
    assert engagement_rate(c) is None


def test_engagement_rate_zero_engagement_is_valid():
    """Нульове залучення при ненульовому охопленні — валідне: 0.0, не None."""
    c = _camp("k1", reach=1000.0, engagement=0.0)
    assert engagement_rate(c) == pytest.approx(0.0)


# ── actor_median_engagement_rate ──────────────────────────────────────────────


def test_actor_median_single_campaign():
    camps = [_camp("k1", reach=1000.0, engagement=100.0)]
    assert actor_median_engagement_rate(camps) == pytest.approx(0.1)


def test_actor_median_multiple_campaigns():
    camps = [
        _camp("k1", reach=1000.0, engagement=100.0),  # er=0.1
        _camp("k2", reach=1000.0, engagement=300.0),  # er=0.3
        _camp("k3", reach=1000.0, engagement=200.0),  # er=0.2
    ]
    assert actor_median_engagement_rate(camps) == pytest.approx(0.2)


def test_actor_median_ignores_none():
    """Кампанії без reach/engagement (er=None) не впливають на медіану."""
    camps = [
        _camp("k1", reach=1000.0, engagement=100.0),  # er=0.1
        _camp("k2", reach=None, engagement=50.0),     # er=None — пропускаємо
        _camp("k3", reach=1000.0, engagement=300.0),  # er=0.3
    ]
    assert actor_median_engagement_rate(camps) == pytest.approx(0.2)  # median(0.1,0.3)


def test_actor_median_all_none_returns_none():
    camps = [
        _camp("k1", reach=None, engagement=None),
        _camp("k2", reach=0.0, engagement=10.0),
    ]
    assert actor_median_engagement_rate(camps) is None


def test_actor_median_empty_list_returns_none():
    assert actor_median_engagement_rate([]) is None


# ── rel_resonance_map (тепер reach-резонанс vs медіана каналу) ───────────────


def test_rel_resonance_above_and_below_channel_median():
    """reach вище медіани каналу → rel > 1; нижче → rel < 1."""
    baselines = {"chX": 1000.0}
    camps = [
        _camp("k1", reach=500.0, handle="chX"),   # 0.5
        _camp("k2", reach=1000.0, handle="chX"),  # 1.0
        _camp("k3", reach=2000.0, handle="chX"),  # 2.0
    ]
    m = rel_resonance_map(camps, baselines)
    assert m["k1"] == pytest.approx(0.5)
    assert m["k2"] == pytest.approx(1.0)
    assert m["k3"] == pytest.approx(2.0)
    assert m["k3"] > 1.0


def test_rel_resonance_none_when_no_reach():
    """Немає reach → rel=None (не 0)."""
    baselines = {"chX": 1000.0}
    camps = [
        _camp("k1", reach=None, handle="chX"),
        _camp("k2", reach=1000.0, handle="chX"),
    ]
    m = rel_resonance_map(camps, baselines)
    assert m["k1"] is None
    assert m["k2"] is not None


def test_rel_resonance_none_when_handle_not_in_baselines():
    """Канал без бази у baselines → rel=None (honest null)."""
    camps = [_camp("k1", reach=1000.0, handle="unknownch")]
    m = rel_resonance_map(camps, {"chX": 1000.0})
    assert m["k1"] is None


def test_rel_resonance_none_when_no_handle():
    """Немає handle у provenance → rel=None."""
    camps = [_camp("k1", reach=1000.0, handle=None)]
    m = rel_resonance_map(camps, {"chX": 1000.0})
    assert m["k1"] is None


def test_rel_resonance_returns_all_ids():
    """Повертає ключ для кожної кампанії."""
    camps = [
        _camp("k1", reach=1000.0, handle="chX"),
        _camp("k2", reach=None, handle="chX"),
    ]
    m = rel_resonance_map(camps, {"chX": 1000.0})
    assert set(m.keys()) == {"k1", "k2"}
