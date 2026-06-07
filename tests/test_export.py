import json

from fundrec import export, store
from fundrec.pipeline_analyze import analyze_all
from fundrec.schema import Actor, Campaign, Case, CreativeAsset, Partner, Source


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


# ── F5: campaigns / creatives / partners + campaign_analytics ────────────────


def _setup_with_campaigns(tmp_path):
    conn = _setup_basic(tmp_path)
    store.upsert_partner(conn, Partner(id="p1", name="Спонсор", role="sponsor",
                                       links=["https://sponsor.example"]))
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1", title="Кампанія FPV", goal="military/fpv",
        type="online_ad", channels=["facebook", "instagram"], form_factor=["video"],
        tone=["urgency"], cta_type="donate_link", face="soldier", cadence="series",
        amount_uah=1_000_000.0, reach=50000.0, engagement=2500.0, spend=30000.0,
        partner_ids=["p1"], verdict_reason="ILLUSTRATIVE SAMPLE"))
    store.upsert_creative(conn, CreativeAsset(
        id="cr1", campaign_id="k1", platform="facebook", format="video",
        copy_text="Допоможи зібрати на дрони", media_url="https://picsum.photos/seed/1/320/180"))
    return conn


def test_export_includes_campaign_entities(tmp_path):
    conn = _setup_with_campaigns(tmp_path)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "campaigns" in data and len(data["campaigns"]) == 1
    assert data["campaigns"][0]["id"] == "k1"
    assert "creatives" in data and data["creatives"][0]["id"] == "cr1"
    assert "partners" in data and data["partners"][0]["id"] == "p1"


def test_export_analytics_has_campaign_block(tmp_path):
    conn = _setup_with_campaigns(tmp_path)
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    ca = data["analytics"]["campaign_analytics"]
    assert ca["kpis"]["n_campaigns"] == 1
    assert ca["kpis"]["n_creatives"] == 1
    assert "crosstabs" in ca and "axis_summaries" in ca
