"""End-to-end tests for pipeline_analyze — DB orchestrator for ANALYZE phase."""
from __future__ import annotations

import pytest

from fundrec import store
from fundrec.schema import Actor, Source, Case
from fundrec.pipeline_analyze import analyze_all, build_analytics


# ── helpers ──────────────────────────────────────────────────────────────────

def _setup_db(tmp_path):
    conn = store.connect(tmp_path / "pa.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_actor(conn, Actor(id="a2", name="ComeBackAlive", type="foundation"))
    store.upsert_source(
        conn,
        Source(url="https://mono.ua/1", type="structured", tier=1,
               access="public", license="unknown", actor_id="a1"),
    )
    return conn


def _insert_case(conn, id, goal="military", amount_uah=None, date_start=None,
                 date_end=None, year=None, actor_id="a1", style=None, method=None,
                 verification_status="auto"):
    c = Case(
        id=id, title=f"t{id}", actor_id=actor_id,
        url="https://mono.ua/1", goal=goal,
        amount_uah=amount_uah,
        date_start=date_start, date_end=date_end,
        year=year,
        style=style or [], method=method or [],
        verification_status=verification_status,
    )
    store.upsert_case(conn, c)


# ── analyze_all ───────────────────────────────────────────────────────────────

def test_analyze_all_returns_summary(tmp_path):
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", amount_uah=390_000.0, date_start="2024-01-01", year=2024)
    _insert_case(conn, "c2", amount_uah=1_000_000.0, date_start="2023-05-01", year=2023)

    def fake_client(url):
        return []  # force fallback rate

    summary = analyze_all(conn, _client=fake_client)
    assert isinstance(summary, dict)
    assert "cases_processed" in summary
    assert summary["cases_processed"] == 2


def test_analyze_all_fills_amount_usd(tmp_path):
    """After analyze_all, cases with amount_uah should have amount_usd set."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", amount_uah=39_000.0, date_start="2024-03-15", year=2024)

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    cases = store.load_cases(conn)
    c = next(c for c in cases if c.id == "c1")
    assert c.amount_usd is not None
    assert c.amount_usd == pytest.approx(39_000.0 / 39.0)  # fallback 2024 = 39.0


def test_analyze_all_fills_volume_score(tmp_path):
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", goal="military", amount_uah=100_000.0,
                 date_start="2024-01-01", year=2024)
    _insert_case(conn, "c2", goal="military", amount_uah=10_000_000.0,
                 date_start="2024-01-01", year=2024)

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    cases = store.load_cases(conn)
    by_id = {c.id: c for c in cases}
    assert by_id["c1"].volume_score is not None
    assert by_id["c2"].volume_score is not None
    # c2 has higher amount → higher volume_score
    assert by_id["c2"].volume_score > by_id["c1"].volume_score


def test_analyze_all_fills_speed(tmp_path):
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", amount_uah=1_000_000.0,
                 date_start="2024-01-01", date_end="2024-01-11", year=2024)

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    cases = store.load_cases(conn)
    c = cases[0]
    # 1_000_000 / 10 days = 100_000
    assert c.speed == pytest.approx(100_000.0)


def test_analyze_all_fills_virality_from_signals(tmp_path):
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", year=2024)
    _insert_case(conn, "c2", year=2024)

    def fake_client(url):
        return []

    signals = {
        "c1": {"mentions": 5000, "shares": 2000},
        # c2 has no signals
    }
    analyze_all(conn, signals_by_case=signals, _client=fake_client)
    cases = store.load_cases(conn)
    by_id = {c.id: c for c in cases}
    assert by_id["c1"].virality_score is not None
    assert by_id["c2"].virality_score is None


def test_analyze_all_fills_repeatability(tmp_path):
    conn = _setup_db(tmp_path)
    # a1 has 3 campaigns, a2 has 1
    _insert_case(conn, "c1", actor_id="a1", year=2022)
    _insert_case(conn, "c2", actor_id="a1", year=2023)
    _insert_case(conn, "c3", actor_id="a1", year=2024)
    _insert_case(conn, "c4", actor_id="a2", year=2024)

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    cases = store.load_cases(conn)
    by_id = {c.id: c for c in cases}
    # a1's campaigns should have higher repeatability
    assert by_id["c1"].repeatability > by_id["c4"].repeatability


def test_analyze_all_no_amount_uah_leaves_usd_none(tmp_path):
    """Case with no amount_uah should have amount_usd=None."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", year=2024)  # no amount_uah

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    cases = store.load_cases(conn)
    assert cases[0].amount_usd is None


# ── build_analytics ───────────────────────────────────────────────────────────

def test_build_analytics_returns_expected_shape(tmp_path):
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", goal="military/fpv", amount_uah=390_000.0,
                 date_start="2024-01-01", year=2024,
                 style=["urgency"], method=["monobank_jar"],
                 verification_status="verified")
    _insert_case(conn, "c2", goal="humanitarian", amount_uah=100_000.0,
                 date_start="2023-06-01", year=2023,
                 style=["grassroots"], method=["platform"])

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    result = build_analytics(conn)

    assert "kpis" in result
    assert "trends" in result
    assert "crosstabs" in result
    assert "generated_for_counts" in result

    # kpis
    k = result["kpis"]
    assert "total_usd" in k
    assert "count" in k
    assert "median_speed" in k
    assert "n_verified" in k
    assert k["count"] == 2

    # trends
    t = result["trends"]
    assert "count_by_quarter" in t
    assert "volume_by_quarter" in t
    assert "count_by_goal" in t
    assert "count_by_method" in t

    # Every trend series point has n
    for series_name, series in t.items():
        for pt in series:
            assert "n" in pt, f"Missing n in {series_name} point {pt}"

    # crosstabs
    ct = result["crosstabs"]
    assert "goal_method" in ct
    assert "goal_style" in ct
    for cell in ct["goal_method"]:
        assert "a" in cell
        assert "b" in cell
        assert "n" in cell

    # generated_for_counts
    gc = result["generated_for_counts"]
    assert "total_cases" in gc
    assert gc["total_cases"] == 2


def test_build_analytics_honest_n(tmp_path):
    """Every aggregate in build_analytics carries n."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", goal="military", amount_uah=500_000.0,
                 date_start="2024-02-01", year=2024,
                 method=["monobank_jar"])

    def fake_client(url):
        return []

    analyze_all(conn, _client=fake_client)
    result = build_analytics(conn)

    for series in result["trends"].values():
        for pt in series:
            assert "n" in pt

    for cells in result["crosstabs"].values():
        for cell in cells:
            assert "n" in cell
