"""Unit — what_raises_most (вісь грошей) + goal_success_rate (% цілі з amount/goal).

Дисципліна: honest null — ключ із недостатньою к-стю amount/goal-кампаній (n<min_n)
ВИПУСКАЄТЬСЯ (не показуємо як 0). Кожен запис несе знаменник n.
"""
from __future__ import annotations

import pytest

from fundrec.analyze import goal_success_rate, what_raises_most
from fundrec.schema import Campaign


def _camp(
    id: str,
    *,
    channels: list[str] | None = None,
    tone: list[str] | None = None,
    goal: str = "military",
    amount_uah: float | None = None,
    goal_amount: float | None = None,
) -> Campaign:
    return Campaign(
        id=id, actor_id="a1", title=f"c {id}", goal=goal, type="online_ad",
        channels=channels or [], tone=tone or [],
        amount_uah=amount_uah, goal_amount=goal_amount,
    )


# ── what_raises_most ──────────────────────────────────────────────────────────


def test_what_raises_most_median_amount():
    camps = [
        _camp("k1", channels=["telegram"], amount_uah=100.0),
        _camp("k2", channels=["telegram"], amount_uah=300.0),
        _camp("k3", channels=["telegram"], amount_uah=200.0),
    ]
    rows = what_raises_most(camps, by="channels", min_n=3)
    assert len(rows) == 1
    r = rows[0]
    assert r["key"] == "telegram"
    assert r["median_amount_uah"] == pytest.approx(200.0)
    assert r["n_with_amount"] == 3
    assert r["n_total"] == 3


def test_what_raises_most_skips_below_min_n():
    """Ключ із < min_n amount-кампаній пропускається (honest)."""
    camps = [
        _camp("k1", channels=["telegram"], amount_uah=100.0),
        _camp("k2", channels=["telegram"], amount_uah=200.0),  # лише 2 amount
        _camp("k3", channels=["youtube"], amount_uah=50.0),
        _camp("k4", channels=["youtube"], amount_uah=60.0),
        _camp("k5", channels=["youtube"], amount_uah=70.0),
    ]
    rows = what_raises_most(camps, by="channels", min_n=3)
    keys = {r["key"] for r in rows}
    assert "telegram" not in keys
    assert "youtube" in keys


def test_what_raises_most_ignores_null_amounts():
    """Кампанії без amount не рахуються у знаменник."""
    camps = [
        _camp("k1", channels=["telegram"], amount_uah=100.0),
        _camp("k2", channels=["telegram"], amount_uah=None),
        _camp("k3", channels=["telegram"], amount_uah=200.0),
    ]
    rows = what_raises_most(camps, by="channels", min_n=2)
    r = rows[0]
    assert r["n_with_amount"] == 2
    assert r["n_total"] == 3
    assert r["median_amount_uah"] == pytest.approx(150.0)


def test_what_raises_most_sorted_desc():
    camps = [
        _camp("k1", channels=["lo"], amount_uah=10.0),
        _camp("k2", channels=["lo"], amount_uah=20.0),
        _camp("k3", channels=["lo"], amount_uah=30.0),
        _camp("k4", channels=["hi"], amount_uah=1000.0),
        _camp("k5", channels=["hi"], amount_uah=2000.0),
        _camp("k6", channels=["hi"], amount_uah=3000.0),
    ]
    rows = what_raises_most(camps, by="channels", min_n=3)
    assert rows[0]["key"] == "hi"
    assert [r["median_amount_uah"] for r in rows] == sorted(
        [r["median_amount_uah"] for r in rows], reverse=True)


def test_what_raises_most_empty_when_no_amounts():
    camps = [_camp("k1", channels=["telegram"], amount_uah=None)]
    assert what_raises_most(camps, by="channels", min_n=1) == []


# ── goal_success_rate ─────────────────────────────────────────────────────────


def test_goal_success_rate_amount_vs_goal():
    """Успіх = amount_uah >= goal_amount серед кампаній де обидва відомі."""
    camps = [
        _camp("k1", tone=["urgency"], amount_uah=1000.0, goal_amount=800.0),   # reached
        _camp("k2", tone=["urgency"], amount_uah=500.0, goal_amount=1000.0),   # not
        _camp("k3", tone=["urgency"], amount_uah=1200.0, goal_amount=1000.0),  # reached
    ]
    rows = goal_success_rate(camps, axis="tone", min_n=3)
    assert len(rows) == 1
    r = rows[0]
    assert r["key"] == "urgency"
    assert r["n"] == 3
    assert r["value"] == pytest.approx(2 / 3)


def test_goal_success_rate_denominator_only_both_known():
    """Знаменник — лише кампанії де ОБА amount і goal відомі."""
    camps = [
        _camp("k1", tone=["x"], amount_uah=1000.0, goal_amount=800.0),  # qualifies, reached
        _camp("k2", tone=["x"], amount_uah=None, goal_amount=800.0),    # excluded
        _camp("k3", tone=["x"], amount_uah=900.0, goal_amount=None),    # excluded
        _camp("k4", tone=["x"], amount_uah=200.0, goal_amount=900.0),   # qualifies, not
        _camp("k5", tone=["x"], amount_uah=950.0, goal_amount=900.0),   # qualifies, reached
    ]
    rows = goal_success_rate(camps, axis="tone", min_n=3)
    r = rows[0]
    assert r["n"] == 3  # лише k1,k4,k5
    assert r["value"] == pytest.approx(2 / 3)


def test_goal_success_rate_omits_below_min_n():
    """Ключ із знаменником < min_n випускається (honest «недостатньо даних»)."""
    camps = [
        _camp("k1", tone=["small"], amount_uah=1000.0, goal_amount=800.0),
        _camp("k2", tone=["small"], amount_uah=900.0, goal_amount=800.0),  # лише 2
    ]
    rows = goal_success_rate(camps, axis="tone", min_n=3)
    assert rows == []


def test_goal_success_rate_empty_when_no_qualifying():
    camps = [_camp("k1", tone=["x"], amount_uah=None, goal_amount=None)]
    assert goal_success_rate(camps, axis="tone", min_n=1) == []
