"""Unit 3 — what_works_now.

Дисципліна: actor-нормалізований engagement_rate; min_n фільтрує малі групи;
None-сигнали виключаються; recent-вікно через parse_campaign_date.
"""
from __future__ import annotations

from fundrec.analyze import what_works_now
from fundrec.schema import Campaign


def _camp(
    id: str,
    *,
    actor_id: str = "a1",
    date_start: str | None = None,
    channels: list[str] | None = None,
    tone: list[str] | None = None,
    reach: float | None = None,
    engagement: float | None = None,
    goal: str = "military",
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"camp {id}",
        goal=goal,
        type="online_ad",
        date_start=date_start,
        channels=channels or [],
        tone=tone or [],
        reach=reach,
        engagement=engagement,
    )


# ── базові ────────────────────────────────────────────────────────────────────


def test_what_works_now_higher_rel_resonance_ranks_first():
    """Channel A з вищим actor-нормалізованим er → перший у рейтингу."""
    now = "2024-02-15"
    # actor a1 має 2 кампанії: er=0.1 та er=0.3 → median=0.2
    # channel telegram: er=0.3 → rel=1.5
    # channel youtube: er=0.1 → rel=0.5
    camps = [
        _camp("k1", actor_id="a1", date_start="2024-02-10",
              channels=["telegram"], reach=1000.0, engagement=300.0),  # er=0.3
        _camp("k2", actor_id="a1", date_start="2024-02-08",
              channels=["telegram"], reach=1000.0, engagement=300.0),  # er=0.3
        _camp("k3", actor_id="a1", date_start="2024-02-05",
              channels=["youtube"], reach=1000.0, engagement=100.0),   # er=0.1
        _camp("k4", actor_id="a1", date_start="2024-02-03",
              channels=["youtube"], reach=1000.0, engagement=100.0),   # er=0.1
    ]
    # actor a1 median of all 4 er: median(0.3,0.3,0.1,0.1)=0.2
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=2)
    assert len(rows) >= 2
    # telegram повинен бути першим (score вищий)
    assert rows[0]["key"] == "telegram"
    assert rows[0]["score"] > rows[1]["score"]


def test_what_works_now_result_shape():
    """Кожен рядок має key, score, n."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k2", date_start="2024-02-05", channels=["telegram"],
              reach=1000.0, engagement=300.0),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=1)
    assert len(rows) >= 1
    for r in rows:
        assert "key" in r
        assert "score" in r
        assert "n" in r


def test_what_works_now_min_n_filters_small_groups():
    """Групи з n < min_n не потрапляють у вихід."""
    now = "2024-02-15"
    # telegram: 2 кампанії; youtube: 1 кампанія
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k3", date_start="2024-02-06", channels=["youtube"],
              reach=1000.0, engagement=100.0),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=2)
    keys = {r["key"] for r in rows}
    assert "telegram" in keys
    assert "youtube" not in keys  # n=1 < min_n=2


def test_what_works_now_excludes_no_signal_groups():
    """Групи, де всі rel_resonance=None, не потрапляють у вихід."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=None, engagement=None),  # no signal
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=None, engagement=None),  # no signal
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=1)
    # Telegram has no er → rel_resonance all None → excluded
    assert rows == []


def test_what_works_now_only_recent_campaigns():
    """Кампанії поза recent-вікном не враховуються."""
    now = "2024-02-15"
    camps = [
        # recent (within 30 days)
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k2", date_start="2024-02-05", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        # old (outside 30-day window)
        _camp("k3", date_start="2023-12-01", channels=["youtube"],
              reach=1000.0, engagement=200.0),
        _camp("k4", date_start="2023-11-01", channels=["youtube"],
              reach=1000.0, engagement=200.0),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=1)
    keys = {r["key"] for r in rows}
    assert "telegram" in keys
    assert "youtube" not in keys  # old campaigns excluded


def test_what_works_now_sorted_desc():
    """Вихід відсортований за score по спаданню."""
    now = "2024-02-15"
    # actor a1: 4 кампанії. median er = median(0.05,0.05,0.3,0.3) = 0.175
    camps = [
        _camp("k1", actor_id="a1", date_start="2024-02-10",
              channels=["youtube"], reach=1000.0, engagement=300.0),  # er=0.3
        _camp("k2", actor_id="a1", date_start="2024-02-09",
              channels=["youtube"], reach=1000.0, engagement=300.0),  # er=0.3
        _camp("k3", actor_id="a1", date_start="2024-02-08",
              channels=["facebook"], reach=1000.0, engagement=50.0),  # er=0.05
        _camp("k4", actor_id="a1", date_start="2024-02-07",
              channels=["facebook"], reach=1000.0, engagement=50.0),  # er=0.05
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=2)
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0]["key"] == "youtube"


def test_what_works_now_n_field_counts_recent():
    """n = кількість recent-кампаній у групі."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=1000.0, engagement=200.0),
        _camp("k3", date_start="2024-02-06", channels=["telegram"],
              reach=1000.0, engagement=200.0),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels", min_n=1)
    tg = next(r for r in rows if r["key"] == "telegram")
    assert tg["n"] == 3


def test_what_works_now_empty_returns_empty():
    rows = what_works_now([], now="2024-02-15", window_days=30, by="channels", min_n=1)
    assert rows == []


def test_what_works_now_tone_axis():
    """Вісь tone — аналогічна channels."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", tone=["urgency"],
              reach=1000.0, engagement=400.0),
        _camp("k2", date_start="2024-02-08", tone=["urgency"],
              reach=1000.0, engagement=400.0),
        _camp("k3", date_start="2024-02-06", tone=["humor"],
              reach=1000.0, engagement=100.0),
        _camp("k4", date_start="2024-02-04", tone=["humor"],
              reach=1000.0, engagement=100.0),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="tone", min_n=2)
    keys = [r["key"] for r in rows]
    assert "urgency" in keys
    assert keys[0] == "urgency"  # urgency has higher rel_resonance
