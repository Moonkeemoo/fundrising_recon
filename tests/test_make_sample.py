"""Тести генератора ілюстративного зразка (hermetic — tmp шляхи)."""
import json

from fundrec import make_sample


def _build(tmp_path):
    db = tmp_path / "sample.sqlite"
    out = tmp_path / "cases.json"
    make_sample.build_sample(db_path=db, out_path=out, _client=lambda url: [])
    return json.loads(out.read_text(encoding="utf-8"))


def test_build_sample_writes_json(tmp_path):
    data = _build(tmp_path)
    assert data["count"] >= 15
    assert isinstance(data["cases"], list)


def test_every_case_has_required_fields(tmp_path):
    data = _build(tmp_path)
    for c in data["cases"]:
        assert c.get("id")
        assert c.get("goal")
        assert c.get("verification_status")


def test_analytics_kpi_count_matches(tmp_path):
    data = _build(tmp_path)
    assert data["analytics"]["kpis"]["count"] == data["count"]


def test_virality_has_null_and_nonnull(tmp_path):
    data = _build(tmp_path)
    vir = [c["virality_score"] for c in data["cases"]]
    assert any(v is None for v in vir), "очікуємо хоча б один null virality"
    assert any(v is not None for v in vir), "очікуємо хоча б один non-null virality"


def test_has_conflict_status(tmp_path):
    data = _build(tmp_path)
    statuses = {c["verification_status"] for c in data["cases"]}
    assert "conflict" in statuses


def test_marked_illustrative(tmp_path):
    data = _build(tmp_path)
    assert all("ILLUSTRATIVE" in (c.get("verdict_reason") or "") for c in data["cases"])


def test_spans_all_goal_categories(tmp_path):
    data = _build(tmp_path)
    cats = {(c["goal"].split("/")[0]) for c in data["cases"]}
    # принаймні 8 із 9 категорій присутні
    assert len(cats) >= 8


# ── F5: кампанії / креативи / партнери у зразку ──────────────────────────────


def test_sample_has_campaigns(tmp_path):
    data = _build(tmp_path)
    assert "campaigns" in data
    assert len(data["campaigns"]) >= 10


def test_sample_campaigns_marked_illustrative(tmp_path):
    data = _build(tmp_path)
    assert all(
        "ILLUSTRATIVE SAMPLE" in (c.get("verdict_reason") or "")
        for c in data["campaigns"]
    )


def test_sample_has_null_and_nonnull_campaign_metrics(tmp_path):
    data = _build(tmp_path)
    spends = [c["spend"] for c in data["campaigns"]]
    assert any(s is None for s in spends), "очікуємо хоча б один null spend"
    assert any(s is not None for s in spends), "очікуємо хоча б один non-null spend"


def test_sample_has_creatives_with_media(tmp_path):
    data = _build(tmp_path)
    assert "creatives" in data
    assert len(data["creatives"]) >= 10
    assert any(a.get("media_url") for a in data["creatives"])


def test_sample_has_partners(tmp_path):
    data = _build(tmp_path)
    assert "partners" in data
    assert len(data["partners"]) >= 1


def test_sample_campaign_analytics_populated(tmp_path):
    data = _build(tmp_path)
    ca = data["analytics"]["campaign_analytics"]
    assert ca["kpis"]["n_campaigns"] >= 10
    # at least one crosstab has cells (axes populated)
    assert any(len(cells) > 0 for cells in ca["crosstabs"].values())


def test_sample_campaigns_span_channels(tmp_path):
    data = _build(tmp_path)
    chans = set()
    for c in data["campaigns"]:
        chans.update(c.get("channels") or [])
    # spans several distinct channels
    assert len(chans) >= 5
