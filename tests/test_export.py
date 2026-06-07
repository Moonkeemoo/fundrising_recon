import json

from fundrec import export, store
from fundrec.pipeline_analyze import analyze_all
from fundrec.schema import Actor, Case, Source


def _setup_basic(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(url="https://x", type="structured", tier=1,
                                     access="public", license="unknown", actor_id="a1"))
    store.upsert_case(conn, Case(id="c1", title="FPV", actor_id="a1", url="https://x",
                                 goal="military", style=["urgency"], method=["monobank_jar"]))
    return conn


def test_export_writes_cases_json(tmp_path):
    conn = _setup_basic(tmp_path)
    out = tmp_path / "cases.json"
    n = export.export_cases(conn, out)
    assert n == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["count"] == 1
    assert data["cases"][0]["id"] == "c1"
    assert data["cases"][0]["style"] == ["urgency"]


def test_export_includes_analytics_key(tmp_path):
    """export_cases embeds analytics block in the payload."""
    conn = _setup_basic(tmp_path)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "analytics" in data


def test_export_analytics_has_kpis_trends_crosstabs(tmp_path):
    """Analytics block has expected top-level keys."""
    conn = _setup_basic(tmp_path)
    # Run analyze_all first to populate axes
    analyze_all(conn, _client=lambda url: [])
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    analytics = data["analytics"]
    assert "kpis" in analytics
    assert "trends" in analytics
    assert "crosstabs" in analytics
    assert "generated_for_counts" in analytics


def test_export_analytics_kpis_count_matches(tmp_path):
    """kpis.count in analytics equals the cases count."""
    conn = _setup_basic(tmp_path)
    analyze_all(conn, _client=lambda url: [])
    out = tmp_path / "cases.json"
    n = export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["analytics"]["kpis"]["count"] == n


def test_export_backward_compatible(tmp_path):
    """count and cases keys still present after adding analytics."""
    conn = _setup_basic(tmp_path)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    # Original contract still satisfied
    assert data["count"] == 1
    assert isinstance(data["cases"], list)
    assert data["cases"][0]["id"] == "c1"
