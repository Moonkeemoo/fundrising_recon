"""Unit 2 — parse_campaign_date, trend_momentum.

Дисципліна: pure functions; now передається ззовні (не datetime.now);
None-дати виключаються; мульти-значні осі (channels) внесок у кожен тег.
"""
from __future__ import annotations

import pytest

from fundrec.analyze import parse_campaign_date, trend_momentum
from fundrec.schema import Campaign


def _camp(
    id: str,
    *,
    actor_id: str = "a1",
    date_start: str | None = None,
    year: int | None = None,
    channels: list[str] | None = None,
    tone: list[str] | None = None,
    goal: str = "military",
    reach: float | None = None,
    engagement: float | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"camp {id}",
        goal=goal,
        type="online_ad",
        date_start=date_start,
        year=year,
        channels=channels or [],
        tone=tone or [],
        reach=reach,
        engagement=engagement,
    )


# ── parse_campaign_date ──────────────────────────────────────────────────────


def test_parse_date_from_date_start():
    c = _camp("k1", date_start="2024-03-15")
    assert parse_campaign_date(c) == "2024-03-15"


def test_parse_date_year_month_only():
    c = _camp("k1", date_start="2024-03")
    assert parse_campaign_date(c) == "2024-03-01"


def test_parse_date_year_only_string():
    c = _camp("k1", date_start="2024")
    assert parse_campaign_date(c) == "2024-01-01"


def test_parse_date_fallback_to_year_int():
    c = _camp("k1", year=2023)
    assert parse_campaign_date(c) == "2023-01-01"


def test_parse_date_date_start_takes_priority_over_year():
    c = _camp("k1", date_start="2024-06-01", year=2023)
    assert parse_campaign_date(c) == "2024-06-01"


def test_parse_date_no_info_returns_none():
    c = _camp("k1")
    assert parse_campaign_date(c) is None


# ── trend_momentum ───────────────────────────────────────────────────────────


def test_momentum_basic_counts():
    """Кампанії у recent вікні → momentum > 0."""
    now = "2024-02-15"
    # recent: 2024-01-16 … 2024-02-15  (window=30)
    # prior:  2023-12-17 … 2024-01-15
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"]),  # recent
        _camp("k2", date_start="2024-02-05", channels=["telegram"]),  # recent
        _camp("k3", date_start="2024-01-05", channels=["telegram"]),  # prior
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    tg = by_key["telegram"]
    assert tg["recent_n"] == 2
    assert tg["prior_n"] == 1
    assert tg["momentum"] == 1  # 2 - 1


def test_momentum_none_dates_excluded():
    """Кампанії без дати не потрапляють ні в recent, ні в prior."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"]),  # recent
        _camp("k2", channels=["telegram"]),  # no date → excluded
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert by_key["telegram"]["recent_n"] == 1
    assert by_key["telegram"]["prior_n"] == 0


def test_momentum_zero_when_no_movement():
    """Однакова к-сть в обох вікнах → momentum = 0."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"]),  # recent
        _camp("k2", date_start="2024-01-05", channels=["telegram"]),  # prior
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert by_key["telegram"]["momentum"] == 0


def test_momentum_multivalued_axis():
    """channels=[telegram,youtube] → внесок у обидва ключі."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram", "youtube"]),  # recent
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert "telegram" in by_key
    assert "youtube" in by_key
    assert by_key["telegram"]["recent_n"] == 1
    assert by_key["youtube"]["recent_n"] == 1


def test_momentum_tone_axis():
    """Вісь tone — аналогічно channels."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", tone=["urgency"]),   # recent
        _camp("k2", date_start="2024-02-08", tone=["urgency"]),   # recent
        _camp("k3", date_start="2024-01-05", tone=["emotional"]), # prior
    ]
    rows = trend_momentum(camps, axis="tone", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert by_key["urgency"]["recent_n"] == 2
    assert by_key["urgency"]["prior_n"] == 0
    assert by_key["urgency"]["momentum"] == 2
    assert by_key["emotional"]["prior_n"] == 1
    assert by_key["emotional"]["recent_n"] == 0
    assert by_key["emotional"]["momentum"] == -1


def test_momentum_goal_axis():
    """Вісь goal (скалярна — category)."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", goal="military/fpv"),  # recent
        _camp("k2", date_start="2024-01-05", goal="military"),       # prior
    ]
    rows = trend_momentum(camps, axis="goal", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert "military" in by_key
    m = by_key["military"]
    assert m["recent_n"] == 1
    assert m["prior_n"] == 1


def test_momentum_result_shape():
    """Кожен рядок має обов'язкові поля."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"]),
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    assert len(rows) >= 1
    for r in rows:
        assert "key" in r
        assert "recent_n" in r
        assert "prior_n" in r
        assert "momentum" in r
        assert "recent_resonance" in r


def test_momentum_recent_resonance_mean_er():
    """recent_resonance = середнє engagement_rate recent-кампаній (None-safe)."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, engagement=100.0),  # er=0.1
        _camp("k2", date_start="2024-02-05", channels=["telegram"],
              reach=1000.0, engagement=300.0),  # er=0.3
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    tg = by_key["telegram"]
    assert tg["recent_resonance"] == pytest.approx(0.2)  # mean(0.1, 0.3)


def test_momentum_recent_resonance_none_when_no_er():
    """Якщо жодна recent-кампанія не має er → recent_resonance = None."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=None, engagement=None),
    ]
    rows = trend_momentum(camps, axis="channels", now=now, window_days=30)
    by_key = {r["key"]: r for r in rows}
    assert by_key["telegram"]["recent_resonance"] is None


def test_momentum_empty_camps_returns_empty():
    rows = trend_momentum([], axis="channels", now="2024-02-15", window_days=30)
    assert rows == []
