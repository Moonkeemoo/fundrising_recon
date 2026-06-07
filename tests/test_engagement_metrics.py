"""Unit 1 — engagement_rate, actor_median_engagement_rate, rel_resonance_map.

Дисципліна: None≠0; rel_resonance >1 коли вище медіани актора;
один збір → медіана = саме значення → rel=1.0.
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
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"camp {id}",
        goal="military",
        type="online_ad",
        reach=reach,
        engagement=engagement,
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


# ── rel_resonance_map ─────────────────────────────────────────────────────────


def test_rel_resonance_above_median():
    """er вищий за медіану актора → rel > 1.0."""
    camps = [
        _camp("k1", "a1", reach=1000.0, engagement=100.0),  # er=0.1
        _camp("k2", "a1", reach=1000.0, engagement=200.0),  # er=0.2
        _camp("k3", "a1", reach=1000.0, engagement=300.0),  # er=0.3
    ]
    # median(0.1,0.2,0.3) = 0.2
    m = rel_resonance_map(camps)
    assert m["k1"] == pytest.approx(0.1 / 0.2)  # 0.5
    assert m["k2"] == pytest.approx(0.2 / 0.2)  # 1.0
    assert m["k3"] == pytest.approx(0.3 / 0.2)  # 1.5
    assert m["k3"] > 1.0


def test_rel_resonance_single_campaign_equals_one():
    """Один збір актора → медіана = er → rel = 1.0."""
    camps = [_camp("k1", "a1", reach=1000.0, engagement=200.0)]
    m = rel_resonance_map(camps)
    assert m["k1"] == pytest.approx(1.0)


def test_rel_resonance_none_when_no_signal():
    """Немає er (reach=None) → rel=None (не 0)."""
    camps = [
        _camp("k1", "a1", reach=None, engagement=50.0),
        _camp("k2", "a1", reach=1000.0, engagement=100.0),
    ]
    m = rel_resonance_map(camps)
    # k1 has no er → None regardless of actor median
    assert m["k1"] is None
    assert m["k2"] is not None


def test_rel_resonance_none_when_actor_median_none():
    """Якщо всі кампанії актора без er → медіана None → rel для всіх None."""
    camps = [
        _camp("k1", "a1", reach=None, engagement=None),
        _camp("k2", "a1", reach=0.0, engagement=50.0),
    ]
    m = rel_resonance_map(camps)
    assert m["k1"] is None
    assert m["k2"] is None


def test_rel_resonance_multiple_actors_independent():
    """Нормалізація окремо для кожного актора."""
    camps = [
        _camp("k1", "a1", reach=1000.0, engagement=100.0),  # er=0.1 → a1 median=0.1 → rel=1.0
        _camp("k2", "a2", reach=1000.0, engagement=500.0),  # er=0.5 → a2 median=0.5 → rel=1.0
    ]
    m = rel_resonance_map(camps)
    assert m["k1"] == pytest.approx(1.0)
    assert m["k2"] == pytest.approx(1.0)


def test_rel_resonance_returns_all_ids():
    """Повертає ключ для кожної кампанії."""
    camps = [
        _camp("k1", "a1", reach=1000.0, engagement=100.0),
        _camp("k2", "a1", reach=None, engagement=None),
    ]
    m = rel_resonance_map(camps)
    assert set(m.keys()) == {"k1", "k2"}
