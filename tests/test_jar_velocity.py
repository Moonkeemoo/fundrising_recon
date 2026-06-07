"""Тести fundrec.jars.jar_velocity — чиста функція velocity (₴/день)."""

from __future__ import annotations

import pytest

from fundrec.jars import jar_velocity


_TS_DAY0 = "2024-01-01T10:00:00+00:00"
_TS_DAY1 = "2024-01-02T10:00:00+00:00"   # рівно 1 день після
_TS_DAY2 = "2024-01-03T10:00:00+00:00"   # 2 дні після початку
_TS_HALF = "2024-01-01T22:00:00+00:00"   # 12 год після (0.5 дня)


def _snap(ts: str, amount: float, goal: float | None = 1_000_000.0) -> dict:
    return {"ts": ts, "amount_uah": amount, "goal_amount": goal}


# ---------------------------------------------------------------------------
# Основні сценарії
# ---------------------------------------------------------------------------


def test_two_snapshots_one_day_100k():
    """2 snapshot'и 1 день, +100 000 → 100 000 ₴/день."""
    h = [_snap(_TS_DAY0, 0.0), _snap(_TS_DAY1, 100_000.0)]
    v = jar_velocity(h)
    assert v["uah_per_day"] == pytest.approx(100_000.0)
    assert v["delta_uah"] == pytest.approx(100_000.0)
    assert v["span_days"] == pytest.approx(1.0)
    assert v["pct_per_day"] == pytest.approx(10.0)  # 100k / 1M * 100


def test_same_amount_zero_velocity():
    """Та сама сума → 0 ₴/день (не None)."""
    h = [_snap(_TS_DAY0, 500_000.0), _snap(_TS_DAY1, 500_000.0)]
    v = jar_velocity(h)
    assert v["uah_per_day"] == pytest.approx(0.0)
    assert v["delta_uah"] == pytest.approx(0.0)
    assert v["span_days"] == pytest.approx(1.0)
    assert v["pct_per_day"] == pytest.approx(0.0)


def test_fractional_days():
    """12 год проміжок → span_days = 0.5."""
    h = [_snap(_TS_DAY0, 0.0), _snap(_TS_HALF, 50_000.0)]
    v = jar_velocity(h)
    assert v["span_days"] == pytest.approx(0.5, rel=1e-4)
    assert v["uah_per_day"] == pytest.approx(100_000.0, rel=1e-4)


def test_one_snapshot_returns_none():
    """1 snapshot → всі поля None."""
    v = jar_velocity([_snap(_TS_DAY0, 100_000.0)])
    assert v["uah_per_day"] is None
    assert v["delta_uah"] is None
    assert v["span_days"] is None
    assert v["pct_per_day"] is None


def test_empty_history_returns_none():
    """Порожня history → всі поля None."""
    v = jar_velocity([])
    assert v["uah_per_day"] is None


def test_none_amount_returns_none():
    """None amount_uah → всі поля None."""
    h = [
        {"ts": _TS_DAY0, "amount_uah": None, "goal_amount": 1_000_000.0},
        {"ts": _TS_DAY1, "amount_uah": 100_000.0, "goal_amount": 1_000_000.0},
    ]
    v = jar_velocity(h)
    assert v["uah_per_day"] is None


def test_none_last_amount_returns_none():
    """None в останньому amount_uah → всі поля None."""
    h = [
        {"ts": _TS_DAY0, "amount_uah": 100_000.0, "goal_amount": 1_000_000.0},
        {"ts": _TS_DAY1, "amount_uah": None, "goal_amount": 1_000_000.0},
    ]
    v = jar_velocity(h)
    assert v["uah_per_day"] is None


def test_no_goal_pct_per_day_is_none():
    """Без goal_amount → pct_per_day = None, решта обчислюється нормально."""
    h = [
        {"ts": _TS_DAY0, "amount_uah": 0.0, "goal_amount": None},
        {"ts": _TS_DAY1, "amount_uah": 50_000.0, "goal_amount": None},
    ]
    v = jar_velocity(h)
    assert v["uah_per_day"] == pytest.approx(50_000.0)
    assert v["pct_per_day"] is None


def test_uses_first_and_last_snapshots_only():
    """З 3 snapshot-ів беремо перший і останній."""
    h = [
        _snap(_TS_DAY0, 0.0),
        _snap(_TS_DAY1, 999_999.0),  # середній ігнорується
        _snap(_TS_DAY2, 200_000.0),
    ]
    v = jar_velocity(h)
    # delta = 200k - 0 = 200k за 2 дні = 100k/день
    assert v["uah_per_day"] == pytest.approx(100_000.0)
    assert v["span_days"] == pytest.approx(2.0)


def test_negative_delta():
    """Від'ємна delta (банка зменшилась) → від'ємна velocity (не None)."""
    h = [_snap(_TS_DAY0, 500_000.0), _snap(_TS_DAY1, 400_000.0)]
    v = jar_velocity(h)
    assert v["uah_per_day"] == pytest.approx(-100_000.0)
    assert v["delta_uah"] == pytest.approx(-100_000.0)
