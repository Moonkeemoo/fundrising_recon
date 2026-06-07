"""Tests for analyze.py — 4 axes + trends + crosstabs (pure functions)."""
from __future__ import annotations

import pytest

from fundrec.analyze import (
    goal_category,
    compute_volume_scores,
    compute_speed,
    time_to_goal_days,
    compute_virality,
    compute_repeatability,
    quarter,
    trend_series,
    crosstab,
    kpis,
)
from fundrec.schema import Case


# ── helper ────────────────────────────────────────────────────────────────────

def _case(
    id: str = "c1",
    goal: str = "military",
    amount_usd: float | None = None,
    amount_uah: float | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    year: int | None = None,
    style: list[str] | None = None,
    method: list[str] | None = None,
    actor_id: str = "a1",
) -> Case:
    return Case(
        id=id,
        title=f"case {id}",
        actor_id=actor_id,
        url=f"https://example.com/{id}",
        goal=goal,
        style=style or [],
        method=method or [],
        date_start=date_start,
        date_end=date_end,
        year=year,
        amount_uah=amount_uah,
        amount_usd=amount_usd,
    )


# ── goal_category ─────────────────────────────────────────────────────────────

def test_goal_category_with_slash():
    assert goal_category("military/fpv") == "military"


def test_goal_category_no_slash():
    assert goal_category("humanitarian") == "humanitarian"


# ── compute_volume_scores ──────────────────────────────────────────────────────

def test_volume_scores_none_amount_gives_none():
    cases = [_case("c1", goal="military", amount_usd=None)]
    scores = compute_volume_scores(cases)
    assert scores["c1"] is None


def test_volume_scores_singleton_category_gives_1():
    cases = [_case("c1", goal="military", amount_usd=1000.0)]
    scores = compute_volume_scores(cases)
    assert scores["c1"] == pytest.approx(1.0)


def test_volume_scores_percentile_within_category():
    """3 military cases: smallest=0, middle=0.5, largest=1."""
    cases = [
        _case("c1", goal="military", amount_usd=100.0),
        _case("c2", goal="military", amount_usd=1_000.0),
        _case("c3", goal="military", amount_usd=10_000.0),
    ]
    scores = compute_volume_scores(cases)
    # log10 values: 2, 3, 4 → percentile ranks 0, 0.5, 1
    assert scores["c1"] == pytest.approx(0.0)
    assert scores["c2"] == pytest.approx(0.5)
    assert scores["c3"] == pytest.approx(1.0)


def test_volume_scores_cross_category_independent():
    """Military and humanitarian scored independently."""
    cases = [
        _case("m1", goal="military", amount_usd=100.0),
        _case("m2", goal="military", amount_usd=10_000.0),
        _case("h1", goal="humanitarian", amount_usd=50.0),   # only one in category
    ]
    scores = compute_volume_scores(cases)
    # h1 is singleton → 1.0
    assert scores["h1"] == pytest.approx(1.0)
    # military: m1 lowest→0, m2 highest→1
    assert scores["m1"] == pytest.approx(0.0)
    assert scores["m2"] == pytest.approx(1.0)


def test_volume_scores_mixed_none_and_values():
    cases = [
        _case("c1", goal="military", amount_usd=None),
        _case("c2", goal="military", amount_usd=500.0),
        _case("c3", goal="military", amount_usd=5000.0),
    ]
    scores = compute_volume_scores(cases)
    assert scores["c1"] is None
    assert scores["c2"] == pytest.approx(0.0)
    assert scores["c3"] == pytest.approx(1.0)


# ── compute_speed & time_to_goal_days ─────────────────────────────────────────

def test_time_to_goal_days_valid():
    case = _case(date_start="2024-01-01", date_end="2024-01-11")
    assert time_to_goal_days(case) == 10


def test_time_to_goal_days_same_day_returns_1():
    case = _case(date_start="2024-06-01", date_end="2024-06-01")
    assert time_to_goal_days(case) == 1


def test_time_to_goal_days_missing_date_returns_none():
    assert time_to_goal_days(_case(date_start="2024-01-01")) is None
    assert time_to_goal_days(_case(date_end="2024-01-11")) is None
    assert time_to_goal_days(_case()) is None


def test_compute_speed_valid():
    """10 days, 1_000_000 UAH → velocity = 100_000."""
    case = _case(
        date_start="2024-01-01",
        date_end="2024-01-11",
        amount_uah=1_000_000.0,
    )
    speed = compute_speed(case)
    assert speed == pytest.approx(100_000.0)


def test_compute_speed_no_amount_returns_none():
    case = _case(date_start="2024-01-01", date_end="2024-01-11", amount_uah=None)
    assert compute_speed(case) is None


def test_compute_speed_no_dates_returns_none():
    assert compute_speed(_case(amount_uah=500_000.0)) is None


# ── compute_virality ──────────────────────────────────────────────────────────

def test_virality_none_signals_returns_none():
    assert compute_virality(None) is None


def test_virality_all_none_fields_returns_none():
    assert compute_virality({"mentions": None, "shares": None, "peak": None}) is None


def test_virality_never_zero_for_missing():
    # Should be None, never 0
    result = compute_virality({})
    assert result is None


def test_virality_with_partial_signals():
    result = compute_virality({"mentions": 1000, "shares": None, "peak": None})
    assert result is not None
    assert 0.0 < result <= 1.0


def test_virality_with_full_signals():
    result = compute_virality({"mentions": 5000, "shares": 2000, "peak": 8000})
    assert result is not None
    assert 0.0 < result <= 1.0


def test_virality_higher_signals_higher_score():
    low = compute_virality({"mentions": 10, "shares": 5})
    high = compute_virality({"mentions": 10_000, "shares": 5_000})
    assert high > low


# ── compute_repeatability ─────────────────────────────────────────────────────

def test_repeatability_single_case():
    cases = [_case("c1", year=2024)]
    score = compute_repeatability("a1", cases)
    assert 0.0 <= score <= 1.0


def test_repeatability_many_cases_higher_than_one():
    one_case = [_case("c1", year=2024)]
    many_cases = [_case(f"c{i}", year=2022 + i // 4, actor_id="a1") for i in range(12)]
    s1 = compute_repeatability("a1", one_case)
    sm = compute_repeatability("a1", many_cases)
    assert sm > s1


def test_repeatability_recurring_bonus():
    """Campaigns across different quarters → higher than same-quarter campaigns."""
    same_q = [_case(f"c{i}", date_start="2024-01-15", actor_id="a1") for i in range(3)]
    diff_q = [
        _case("d1", date_start="2024-01-15", actor_id="a1"),
        _case("d2", date_start="2024-04-10", actor_id="a1"),
        _case("d3", date_start="2024-07-20", actor_id="a1"),
    ]
    s_same = compute_repeatability("a1", same_q)
    s_diff = compute_repeatability("a1", diff_q)
    assert s_diff >= s_same


# ── quarter helper ────────────────────────────────────────────────────────────

def test_quarter_date():
    assert quarter("2024-01-15") == "2024-Q1"
    assert quarter("2024-04-01") == "2024-Q2"
    assert quarter("2024-07-31") == "2024-Q3"
    assert quarter("2024-10-01") == "2024-Q4"


def test_quarter_year_only():
    assert quarter("2023") == "2023-Q1"


# ── trend_series ──────────────────────────────────────────────────────────────

def _trend_cases():
    return [
        _case("c1", goal="military", amount_usd=1000.0, date_start="2022-02-28"),
        _case("c2", goal="military", amount_usd=2000.0, date_start="2023-06-01"),
        _case("c3", goal="humanitarian", amount_usd=500.0, date_start="2024-01-15"),
        _case("c4", goal="military", amount_usd=1500.0,
              date_start="2025-01-01", date_end="2025-01-31", amount_uah=60_000.0),
    ]


def test_trend_series_count_no_dimension():
    series = trend_series(_trend_cases(), dimension=None, metric="count")
    assert isinstance(series, list)
    # Each point has required keys
    for pt in series:
        assert "period" in pt
        assert "value" in pt
        assert "n" in pt
    # Total count across all periods should sum to number of cases
    total = sum(pt["n"] for pt in series)
    assert total == 4


def test_trend_series_volume_usd():
    series = trend_series(_trend_cases(), dimension=None, metric="volume_usd")
    non_zero = [pt for pt in series if pt["value"] is not None and pt["value"] > 0]
    assert len(non_zero) >= 1
    for pt in non_zero:
        assert pt["n"] > 0


def test_trend_series_with_goal_dimension():
    series = trend_series(_trend_cases(), dimension="goal", metric="count")
    # Should have entries for military and humanitarian
    keys = {pt.get("key") for pt in series}
    assert "military" in keys
    assert "humanitarian" in keys
    # Each point has n
    for pt in series:
        assert "n" in pt
        assert "key" in pt


def test_trend_series_points_have_honest_n():
    """Every aggregate carries N."""
    series = trend_series(_trend_cases(), dimension=None, metric="count")
    for pt in series:
        assert isinstance(pt["n"], int)
        assert pt["n"] >= 0


def test_trend_series_median_speed():
    series = trend_series(_trend_cases(), dimension=None, metric="median_speed")
    # 2025-Q1 has a case with speed; others don't
    for pt in series:
        assert "value" in pt
        assert "n" in pt


# ── crosstab ──────────────────────────────────────────────────────────────────

def _crosstab_cases():
    return [
        _case("c1", goal="military", method=["monobank_jar"], amount_usd=1000.0),
        _case("c2", goal="military", method=["monobank_jar", "crypto"], amount_usd=2000.0),
        _case("c3", goal="humanitarian", method=["platform"], amount_usd=500.0),
        _case("c4", goal="medical", method=["monobank_jar"], amount_usd=300.0),
    ]


def test_crosstab_goal_method_shape():
    cells = crosstab(_crosstab_cases(), axis_a="goal", axis_b="method", metric="count")
    assert isinstance(cells, list)
    for cell in cells:
        assert "a" in cell
        assert "b" in cell
        assert "value" in cell
        assert "n" in cell


def test_crosstab_military_monobank():
    cells = crosstab(_crosstab_cases(), axis_a="goal", axis_b="method", metric="count")
    mil_mono = [c for c in cells if c["a"] == "military" and c["b"] == "monobank_jar"]
    assert len(mil_mono) == 1
    # Both c1 and c2 have military + monobank_jar
    assert mil_mono[0]["n"] == 2


def test_crosstab_multi_tag_contributes_all():
    """c2 has method=[monobank_jar, crypto] → appears in both cells."""
    cells = crosstab(_crosstab_cases(), axis_a="goal", axis_b="method", metric="count")
    mil_crypto = [c for c in cells if c["a"] == "military" and c["b"] == "crypto"]
    assert len(mil_crypto) == 1
    assert mil_crypto[0]["n"] == 1


def test_crosstab_volume_usd_metric():
    cells = crosstab(_crosstab_cases(), axis_a="goal", axis_b="method", metric="volume_usd")
    mil_mono = [c for c in cells if c["a"] == "military" and c["b"] == "monobank_jar"]
    assert len(mil_mono) == 1
    # c1=1000 + c2=2000
    assert mil_mono[0]["value"] == pytest.approx(3000.0)
    assert mil_mono[0]["n"] == 2


# ── kpis ──────────────────────────────────────────────────────────────────────

def test_kpis_shape():
    cases = _trend_cases()
    result = kpis(cases)
    assert "total_usd" in result
    assert "count" in result
    assert "median_speed" in result
    assert "n_verified" in result


def test_kpis_total_usd():
    cases = _trend_cases()
    result = kpis(cases)
    # c1+c2+c3+c4 = 1000+2000+500+1500 = 5000
    assert result["total_usd"] == pytest.approx(5000.0)


def test_kpis_count():
    result = kpis(_trend_cases())
    assert result["count"] == 4


def test_kpis_empty_list():
    result = kpis([])
    assert result["count"] == 0
    assert result["total_usd"] == 0.0
    assert result["median_speed"] is None
