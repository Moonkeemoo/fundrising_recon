"""Unit 3 — what_works_now (тепер канал-нормалізований reach-резонанс).

Дисципліна: reach vs медіана каналу (baselines); min_n фільтрує малі групи;
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
    handle: str | None = None,
    goal: str = "military",
) -> Campaign:
    prov = {}
    if handle is not None:
        prov["reach"] = {"source_url": f"https://t.me/{handle}/1"}
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
        provenance=prov,
    )


# Спільна база каналів: handle "ch" з медіаною 1000.
_BL = {"chHi": 1000.0, "chLo": 1000.0, "ch": 1000.0}


# ── базові ────────────────────────────────────────────────────────────────────


def test_what_works_now_higher_resonance_ranks_first():
    """Channel-група з вищим reach-резонансом → перша у рейтингу."""
    now = "2024-02-15"
    camps = [
        # telegram: reach 2000 на каналі з медіаною 1000 → rr=2.0
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=2000.0, handle="chHi"),
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=2000.0, handle="chHi"),
        # youtube: reach 500 → rr=0.5
        _camp("k3", date_start="2024-02-05", channels=["youtube"],
              reach=500.0, handle="chLo"),
        _camp("k4", date_start="2024-02-03", channels=["youtube"],
              reach=500.0, handle="chLo"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=2, baselines=_BL)
    assert len(rows) >= 2
    assert rows[0]["key"] == "telegram"
    assert rows[0]["score"] > rows[1]["score"]


def test_what_works_now_result_shape():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k2", date_start="2024-02-05", channels=["telegram"],
              reach=1500.0, handle="ch"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=1, baselines=_BL)
    assert len(rows) >= 1
    for r in rows:
        assert "key" in r
        assert "score" in r
        assert "n" in r


def test_what_works_now_min_n_filters_small_groups():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k3", date_start="2024-02-06", channels=["youtube"],
              reach=1000.0, handle="ch"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=2, baselines=_BL)
    keys = {r["key"] for r in rows}
    assert "telegram" in keys
    assert "youtube" not in keys  # n=1 < min_n=2


def test_what_works_now_excludes_no_signal_groups():
    """Групи, де всі reach_resonance=None, не потрапляють у вихід."""
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=None),  # no signal
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=None),  # no signal
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=1, baselines=_BL)
    assert rows == []


def test_what_works_now_only_recent_campaigns():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k2", date_start="2024-02-05", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k3", date_start="2023-12-01", channels=["youtube"],
              reach=1000.0, handle="ch"),
        _camp("k4", date_start="2023-11-01", channels=["youtube"],
              reach=1000.0, handle="ch"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=1, baselines=_BL)
    keys = {r["key"] for r in rows}
    assert "telegram" in keys
    assert "youtube" not in keys  # old campaigns excluded


def test_what_works_now_sorted_desc():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["youtube"],
              reach=3000.0, handle="ch"),  # rr=3.0
        _camp("k2", date_start="2024-02-09", channels=["youtube"],
              reach=3000.0, handle="ch"),  # rr=3.0
        _camp("k3", date_start="2024-02-08", channels=["facebook"],
              reach=500.0, handle="ch"),   # rr=0.5
        _camp("k4", date_start="2024-02-07", channels=["facebook"],
              reach=500.0, handle="ch"),   # rr=0.5
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=2, baselines=_BL)
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0]["key"] == "youtube"


def test_what_works_now_n_field_counts_recent():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k2", date_start="2024-02-08", channels=["telegram"],
              reach=1000.0, handle="ch"),
        _camp("k3", date_start="2024-02-06", channels=["telegram"],
              reach=1000.0, handle="ch"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="channels",
                          min_n=1, baselines=_BL)
    tg = next(r for r in rows if r["key"] == "telegram")
    assert tg["n"] == 3


def test_what_works_now_empty_returns_empty():
    rows = what_works_now([], now="2024-02-15", window_days=30, by="channels",
                          min_n=1, baselines=_BL)
    assert rows == []


def test_what_works_now_tone_axis():
    now = "2024-02-15"
    camps = [
        _camp("k1", date_start="2024-02-10", tone=["urgency"],
              reach=4000.0, handle="ch"),  # rr=4.0
        _camp("k2", date_start="2024-02-08", tone=["urgency"],
              reach=4000.0, handle="ch"),
        _camp("k3", date_start="2024-02-06", tone=["humor"],
              reach=1000.0, handle="ch"),  # rr=1.0
        _camp("k4", date_start="2024-02-04", tone=["humor"],
              reach=1000.0, handle="ch"),
    ]
    rows = what_works_now(camps, now=now, window_days=30, by="tone",
                          min_n=2, baselines=_BL)
    keys = [r["key"] for r in rows]
    assert "urgency" in keys
    assert keys[0] == "urgency"  # urgency has higher reach-resonance
